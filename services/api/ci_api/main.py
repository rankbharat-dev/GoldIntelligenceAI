"""Research API — serves validated datasets to the web app.

Reads derived Parquet datasets only (storage/derived/xauusd). It cannot reach MT5
or the MCP server; tests/leakage/test_mt5_boundary.py enforces that.

    ci-api                      → http://127.0.0.1:8000  (docs at /docs)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

import polars as pl
from fastapi import FastAPI, HTTPException, Query

from candle_intel.config import get_settings

Timeframe = Literal["M1", "M5", "M15", "H1"]
MAX_BARS = 5000

app = FastAPI(title="Candle Intelligence API", version="0.1.0", docs_url="/docs")


def _root() -> Path:
    return get_settings().storage_root / "derived" / "xauusd"


@lru_cache(maxsize=32)
def _manifest(dataset_id: str) -> dict[str, Any]:
    """Callers pass ids from _dataset_ids() / _resolve() only."""
    return json.loads((_root() / dataset_id / "manifest.json").read_text(encoding="utf-8"))


def _dataset_ids() -> list[str]:
    root = _root()
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "manifest.json").exists())


def _resolve(dataset: str) -> str:
    """Map a request's dataset to a known directory name. Only ids that exist on disk
    are accepted, so the parameter can never be used to build an arbitrary path."""
    ids = _dataset_ids()
    if dataset == "latest":
        if not ids:
            raise HTTPException(404, "No datasets yet. Run: ci-ingest raw, then ci-data build")
        return ids[-1]
    if dataset not in ids:
        raise HTTPException(404, f"Unknown dataset {dataset!r}")
    return dataset


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "datasets": len(_dataset_ids())}


@app.get("/api/datasets")
def datasets() -> list[dict[str, Any]]:
    out = []
    for ds in _dataset_ids():
        m = _manifest(ds)
        out.append(
            {
                "dataset_id": ds,
                "broker": m["broker"],
                "broker_server": m["broker_server"],
                "research_window_utc": m["research_window_utc"],
                "built_utc": m["built_utc"],
            }
        )
    return out


@app.get("/api/datasets/{dataset}/summary")
def summary(dataset: str) -> dict[str, Any]:
    ds = _resolve(dataset)
    m = _manifest(ds)
    q = json.loads((_root() / ds / "quality.json").read_text(encoding="utf-8"))
    return {
        "dataset_id": ds,
        "symbol": m["symbol"],
        "broker": m["broker"],
        "broker_server": m["broker_server"],
        "price_side": m["price_side"],
        "built_utc": m["built_utc"],
        "code_version": m["code_version"],
        "bars": {tf: f["rows"] for tf, f in m["files"].items()},
        "clock_model": m["clock_model"],
        "verification_vs_broker": m["verification_vs_broker"],
        "quality": q,
        "symbol_spec": m["symbol_spec"],
    }


@app.get("/api/candles")
def candles(
    tf: Timeframe = "M5",
    dataset: str = "latest",
    before: Annotated[int | None, Query(description="UTC epoch seconds; bars strictly before")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_BARS)] = 1500,
) -> dict[str, Any]:
    """Bars ending before `before` (default: the newest), oldest first — the shape
    TradingView Lightweight Charts expects, and what infinite scroll-back needs."""
    ds = _resolve(dataset)
    lf = pl.scan_parquet(_root() / ds / f"{tf}.parquet")
    if before is not None:
        cutoff = datetime.fromtimestamp(before, tz=UTC).replace(tzinfo=None)
        lf = lf.filter(pl.col("ts_utc") < cutoff)
    cols = ["ts_utc", "open", "high", "low", "close", "tick_volume"]
    if tf != "M1":
        cols.append("m1_bars")
    df = lf.select(cols).tail(limit).collect()
    expected_m1 = {"M1": 1, "M5": 5, "M15": 15, "H1": 60}[tf]
    return {
        "dataset_id": ds,
        "timeframe": tf,
        "count": df.height,
        "has_more": df.height == limit,
        "time": (df["ts_utc"].dt.epoch("s")).to_list(),
        "open": df["open"].to_list(),
        "high": df["high"].to_list(),
        "low": df["low"].to_list(),
        "close": df["close"].to_list(),
        "volume": df["tick_volume"].to_list(),
        # Bars built from fewer M1 bars than their length (gaps, session edges).
        "incomplete": (df["m1_bars"] < expected_m1).to_list() if tf != "M1" else None,
    }


def main() -> None:
    import uvicorn

    uvicorn.run("ci_api.main:app", host="127.0.0.1", port=8000, reload=False)
