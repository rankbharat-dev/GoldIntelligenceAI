"""Everything one backtest reads, loaded once: the M1 execution path, per-M1-bar
spreads of the three cost scenarios, the frozen symbol spec and the feature set.

Parquet only (never MT5). The three inputs must belong to the same dataset; their
ids are carried into every result for lineage.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from candle_intel.backtest.split import Split, load_or_freeze
from candle_intel.config import get_settings
from candle_intel.costs.execution import Commission
from candle_intel.features.store import FEATURES_FILE, MANIFEST_FILE

SCENARIOS = ("optimistic", "base", "pessimistic")
# Flat before the weekend: from Friday 16:50 New York the position is closed at market
# (the week closes at 17:00 NY; the last 3 M5 bars are already no-entry bars).
WEEKEND_FLAT_NY_MINUTE = 16 * 60 + 50


@dataclass
class Market:
    dataset_id: str
    cost_model_id: str
    feature_set_id: str
    symbol_spec: dict[str, Any]
    commission: Commission
    split: Split
    t: np.ndarray  # int64 epoch seconds, M1 bar open (UTC)
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray  # noqa: E741 — OHLC naming
    c: np.ndarray
    spread: dict[str, np.ndarray]  # scenario → points per M1 bar
    measured: np.ndarray  # bool: spread measured from ticks (else modeled)
    in_window: np.ndarray  # bool: rollover window (stop slippage widens)
    weekend_flat: np.ndarray  # bool: Friday ≥ 16:50 NY
    features_path: Path
    spread_px: dict[str, np.ndarray] = field(default_factory=dict, repr=False)  # scenario → price units
    _feature_cache: dict[tuple[str, ...], pl.DataFrame] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.spread_px = {s: v * float(self.symbol_spec["point"]) for s, v in self.spread.items()}

    @property
    def point(self) -> float:
        return float(self.symbol_spec["point"])

    @property
    def contract_size(self) -> float:
        return float(self.symbol_spec["trade_contract_size"])

    def features(self, columns: list[str]) -> pl.DataFrame:
        """Research-window rows of the feature set, only the requested columns."""
        key = tuple(sorted(set(columns)))
        if key not in self._feature_cache:
            cols = ["event_time", "available_at", "in_research_window", *key]
            if self.features_path.is_file():
                f = pl.read_parquet(self.features_path, columns=list(dict.fromkeys(cols)))
            else:  # tests hand a frame directly
                f = self._frame.select(list(dict.fromkeys(cols)))
            self._feature_cache[key] = f.filter(pl.col("in_research_window")).sort("available_at")
            if len(self._feature_cache) > 16:
                self._feature_cache.pop(next(iter(self._feature_cache)))
        return self._feature_cache[key]

    @classmethod
    def from_frames(
        cls,
        m1: pl.DataFrame,
        m1_costs: pl.DataFrame,
        features: pl.DataFrame,
        symbol_spec: dict[str, Any],
        split: Split,
        commission: Commission | None = None,
        ids: tuple[str, str, str] = ("test", "test", "test"),
    ) -> Market:
        m1 = m1.sort("ts_utc").join(
            m1_costs.select(
                "ts_utc",
                *[f"spread_{s}" for s in SCENARIOS],
                "spread_source",
                "in_rollover_window",
            ),
            on="ts_utc",
            how="left",
        )
        ny = pl.col("ts_utc").dt.replace_time_zone("UTC").dt.convert_time_zone("America/New_York")
        m1 = m1.with_columns(
            _wf=(ny.dt.weekday() == 5)
            & (ny.dt.hour().cast(pl.Int32) * 60 + ny.dt.minute() >= WEEKEND_FLAT_NY_MINUTE)
        )
        for s in SCENARIOS:  # a bar without a cost row pays the scenario's median — never zero
            col = f"spread_{s}"
            m1 = m1.with_columns(pl.col(col).fill_null(pl.col(col).median()))
        mk = cls(
            dataset_id=ids[0],
            cost_model_id=ids[1],
            feature_set_id=ids[2],
            symbol_spec=symbol_spec,
            commission=commission or Commission(),
            split=split,
            t=m1["ts_utc"].dt.epoch("s").to_numpy(),
            o=m1["open"].to_numpy(),
            h=m1["high"].to_numpy(),
            l=m1["low"].to_numpy(),
            c=m1["close"].to_numpy(),
            spread={s: m1[f"spread_{s}"].to_numpy().astype(np.float64) for s in SCENARIOS},
            measured=(m1["spread_source"] == "measured").fill_null(False).to_numpy(),
            in_window=m1["in_rollover_window"].fill_null(False).to_numpy(),
            weekend_flat=m1["_wf"].to_numpy(),
            features_path=Path("<memory>"),
        )
        mk._frame = features  # type: ignore[attr-defined]
        return mk


def research_root() -> Path:
    return get_settings().storage_root / "research"


def _newest(root: Path, marker: str) -> Path:
    items = sorted(p for p in root.iterdir() if (p / marker).exists()) if root.exists() else []
    if not items:
        raise FileNotFoundError(f"nothing built under {root}")
    return items[-1]


@lru_cache(maxsize=2)
def load(dataset_dir: Path) -> Market:
    """The newest cost model and feature set of a dataset, with the frozen split."""
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    cm = _newest(dataset_dir / "costs", "cost_model.json")
    fs = _newest(dataset_dir / "features", MANIFEST_FILE)
    cm_doc = json.loads((cm / "cost_model.json").read_text(encoding="utf-8"))
    c = cm_doc["execution"]["commission"]
    commission = Commission(
        per_lot_round_turn_usd=c["per_lot_round_turn_usd"],
        confirmed=c["confirmed"],
        unconfirmed_pessimistic_usd=c["unconfirmed_pessimistic_usd"],
    )
    rw = manifest["research_window_utc"]
    split = load_or_freeze(
        research_root() / "split.json", datetime.fromisoformat(rw[0]), datetime.fromisoformat(rw[1])
    )
    m1 = pl.read_parquet(dataset_dir / "M1.parquet", columns=["ts_utc", "open", "high", "low", "close"])
    costs = pl.read_parquet(
        cm / "M1_costs.parquet",
        columns=["ts_utc", *[f"spread_{s}" for s in SCENARIOS], "spread_source", "in_rollover_window"],
    )
    mk = Market.from_frames(
        m1,
        costs,
        pl.DataFrame(),
        manifest["symbol_spec"],
        split,
        commission,
        (manifest["dataset_id"], cm.name, fs.name),
    )
    mk.features_path = fs / FEATURES_FILE
    return mk


def latest_dataset_dir() -> Path:
    return _newest(get_settings().storage_root / "derived" / "xauusd", "manifest.json")
