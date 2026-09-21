"""Run a spec, count it, store it — the only way results are produced.

Every call here:
1. validates the spec and saves it in the ledger (content hash),
2. refuses tier C unless the family's one-time unseal names this spec,
3. runs the event-driven engine for the three cost scenarios,
4. records the variant as a trial on its family (once per spec),
5. computes the Deflated Sharpe at the family's *current* trial count,
6. writes ``storage/research/runs/<run_id>/`` (run.json + trades.parquet) and indexes it.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from candle_intel.backtest import engine, metrics
from candle_intel.backtest.market import SCENARIOS, Market, research_root
from candle_intel.backtest.split import Tier
from candle_intel.provenance import code_version
from candle_intel.research.ledger import HoldoutError, Ledger
from candle_intel.statistics import robust
from candle_intel.strategy.spec import StrategySpec

Progress = Callable[[float, str], None]
PROMOTION_SCENARIO = "pessimistic"


def runs_root() -> Path:
    return research_root() / "runs"


def new_run_id(kind: str, spec_hash: str, tier: str) -> str:
    return f"{kind[:2]}_{datetime.now(UTC):%Y%m%dT%H%M%S}_{spec_hash[:8]}_{tier}_{secrets.token_hex(2)}"


def check_tier_access(spec: StrategySpec, tier: Tier, ledger: Ledger) -> None:
    if tier != "C":
        return
    h = ledger.holdout_status(spec.meta.family)
    if h is None:
        raise HoldoutError(
            f"Tier C is sealed for family {spec.meta.family!r}. Unseal it (one time, logged) from Validate."
        )
    if h["strategy_id"] != spec.spec_hash:
        raise HoldoutError(
            f"Family {spec.meta.family!r} already spent its holdout on strategy {h['strategy_id']}."
        )


def save_spec(spec: StrategySpec, ledger: Ledger, parent: str | None = None) -> str:
    ledger.save_spec(
        spec.spec_hash,
        spec.meta.family,
        spec.meta.name,
        spec.model_dump(mode="json"),
        spec.meta.created_by,
        parent,
    )
    return spec.spec_hash


def evaluate(
    spec: StrategySpec,
    mk: Market,
    tier: Tier,
    scenarios: tuple[str, ...] = SCENARIOS,
    policy: engine.AmbiguityPolicy = "pessimistic",
) -> tuple[pl.DataFrame, dict[str, dict[str, Any]], int]:
    """Pure evaluation (no ledger): trades, metrics per scenario, signal count."""
    trades, sigs = engine.run(spec, mk, tier, scenarios, policy)
    per = {
        s: metrics.summarise(trades.filter(pl.col("scenario") == s), spec.sizing.initial_equity_usd)
        for s in scenarios
    }
    return trades, per, sigs.height


def deflated(spec: StrategySpec, m: dict[str, Any], ledger: Ledger) -> dict[str, Any] | None:
    if not m.get("n") or m.get("sharpe_per_trade") is None:
        return None
    n_trials, sharpes = ledger.trials(spec.meta.family)
    return robust.deflated_sharpe(
        m["sharpe_per_trade"], m["n"], m["skew"] or 0.0, m["kurtosis"] or 3.0, n_trials, sharpes
    )


def robustness(trades: pl.DataFrame, mk: Market) -> dict[str, Any]:
    t = trades.filter(pl.col("scenario") == PROMOTION_SCENARIO).sort("exit_time")
    r = t["r_net"].to_numpy()
    return {
        "bootstrap_expectancy_ci": robust.stationary_bootstrap_ci(r),
        "monte_carlo_drawdown_r": robust.monte_carlo_drawdown(r),
        "cost_stress": robust.cost_stress(r, t["risk_pts"].to_numpy(), mk.point, mk.contract_size),
    }


def run_backtest(
    spec: StrategySpec,
    tier: Tier,
    mk: Market,
    ledger: Ledger,
    kind: str = "backtest",
    source: str = "backtest",
    policy: engine.AmbiguityPolicy = "pessimistic",
    progress: Progress | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    check_tier_access(spec, tier, ledger)
    save_spec(spec, ledger)
    if progress:
        progress(0.05, "signals and trades")
    trades, per, n_signals = evaluate(spec, mk, tier, SCENARIOS, policy)
    pess = per[PROMOTION_SCENARIO]
    n_trials = ledger.record_trial(
        spec.meta.family, spec.spec_hash, tier[0], pess.get("sharpe_per_trade"), pess["n"], source
    )
    if progress:
        progress(0.7, "robustness statistics")
    start, end = mk.split.bounds(tier)
    run_id = new_run_id(kind, spec.spec_hash, tier)
    doc = {
        "run_id": run_id,
        "kind": kind,
        "created_utc": datetime.now(UTC).isoformat(),
        "spec_hash": spec.spec_hash,
        "family": spec.meta.family,
        "name": spec.meta.name,
        "spec": spec.model_dump(mode="json"),
        "tier": tier,
        "tier_bounds_utc": [start.isoformat(), end.isoformat() if end else None],
        "split": mk.split.to_dict(),
        "ambiguity_policy": policy,
        "lineage": {
            "dataset_id": mk.dataset_id,
            "cost_model_id": mk.cost_model_id,
            "cost_profile": mk.cost_profile,
            "cost_profile_status": mk.cost_status,
            "feature_set_id": mk.feature_set_id,
            "code_version": code_version(),
            "engine": "event-driven M1 v1",
        },
        "signals": n_signals,
        "family_trials": n_trials,
        "deflated_sharpe": deflated(spec, pess, ledger),
        "results": per,
        "robustness": robustness(trades, mk),
    } | (extra or {})
    out = write_doc(run_id, doc)
    trades.write_parquet(out / "trades.parquet", compression="zstd")
    ledger.record_run(run_id, kind, spec.spec_hash, spec.meta.family, tier, headline(doc))
    if progress:
        progress(1.0, "done")
    return doc


def write_doc(run_id: str, doc: dict[str, Any]) -> Path:
    out = runs_root() / run_id
    out.mkdir(parents=True, exist_ok=False)
    (out / "run.json").write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
    return out


def headline(doc: dict[str, Any]) -> dict[str, Any]:
    p = doc["results"][PROMOTION_SCENARIO]
    keys = ("n", "expectancy_r", "profit_factor", "max_dd_r", "win_rate", "total_r", "ambiguity_rate")
    return {k: p.get(k) for k in keys} | {
        "name": doc["name"],
        "family_trials": doc["family_trials"],
        "base_expectancy_r": doc["results"]["base"].get("expectancy_r"),
        "deflated_excess": (doc.get("deflated_sharpe") or {}).get("deflated_excess"),
    }


def _run_dir(run_id: str) -> Path:
    """Only ids that exist under the runs root are accepted (no path building from input)."""
    root = runs_root()
    names = {p.name for p in root.iterdir()} if root.exists() else set()
    if run_id not in names:
        raise FileNotFoundError(run_id)
    return root / run_id


def load_run(run_id: str) -> dict[str, Any]:
    return json.loads((_run_dir(run_id) / "run.json").read_text(encoding="utf-8"))


def load_trades(run_id: str, scenario: str = PROMOTION_SCENARIO) -> pl.DataFrame:
    return pl.read_parquet(_run_dir(run_id) / "trades.parquet").filter(pl.col("scenario") == scenario)


def jsonable_trades(t: pl.DataFrame) -> list[dict[str, Any]]:
    out = []
    for r in t.sort("entry_time").iter_rows(named=True):
        d = {}
        for k, v in r.items():
            if isinstance(v, datetime):
                d[k] = int(v.replace(tzinfo=UTC).timestamp())
            elif isinstance(v, float):
                d[k] = None if not np.isfinite(v) else round(v, 5)
            else:
                d[k] = v
        out.append(d)
    return out
