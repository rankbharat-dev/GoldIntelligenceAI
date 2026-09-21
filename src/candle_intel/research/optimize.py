"""Parameter search inside the §9 guardrails (Optimize page).

- Runs on tier A (development) only — B and C are never optimised on.
- Every variant is recorded as a trial on the family, so the Deflated Sharpe of the
  winner is judged against how many were tried.
- The sensitivity grid shows whether the best cell sits on a **plateau** (neighbours
  nearly as good — a real effect is usually smooth) or a **spike** (one lucky cell).
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from datetime import datetime
from typing import Any

import numpy as np
import polars as pl

from candle_intel.backtest import engine, metrics
from candle_intel.backtest.market import Market
from candle_intel.research import runs
from candle_intel.research.ledger import Ledger
from candle_intel.strategy.spec import StrategySpec, get_path, with_params

MAX_VARIANTS = 400
MIN_TRADES = 30
SCENARIO = "pessimistic"


def grid(params: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``[{"path": "exit.stop_atr", "values": [0.5, 1, 1.5]}, ...]`` → list of assignments."""
    if not params:
        raise ValueError("choose at least one parameter")
    if len(params) > 3:
        raise ValueError("at most 3 parameters at once (the grid grows multiplicatively)")
    paths = [p["path"] for p in params]
    combos = list(itertools.product(*[p["values"] for p in params]))
    if len(combos) > MAX_VARIANTS:
        raise ValueError(f"{len(combos)} variants — the limit is {MAX_VARIANTS}; narrow the ranges")
    return [dict(zip(paths, c, strict=True)) for c in combos]


def evaluate_variant(spec: StrategySpec, mk: Market, window) -> tuple[dict[str, Any], pl.DataFrame]:
    trades, _ = engine.run(spec, mk, window, (SCENARIO,))
    return metrics.summarise(trades, spec.sizing.initial_equity_usd), trades


def _row(assign: dict[str, Any], v: StrategySpec, m: dict[str, Any]) -> dict[str, Any]:
    keep = ("n", "expectancy_r", "profit_factor", "max_dd_r", "win_rate", "sharpe_per_trade", "total_r")
    return {"params": assign, "spec_hash": v.spec_hash} | {k: m.get(k) for k in keep}


def plateau(
    table: list[dict[str, Any]], params: list[dict[str, Any]], best: dict[str, Any]
) -> dict[str, Any]:
    """Mean expectancy of the best cell's grid neighbours ÷ the best's expectancy."""
    idx = {tuple(r["params"][p["path"]] for p in params): r for r in table}
    pos = [p["values"].index(best["params"][p["path"]]) for p in params]
    neigh = []
    for d in range(len(params)):
        for step in (-1, 1):
            q = list(pos)
            q[d] += step
            if 0 <= q[d] < len(params[d]["values"]):
                r = idx.get(tuple(params[i]["values"][q[i]] for i in range(len(params))))
                if r and r["expectancy_r"] is not None:
                    neigh.append(r["expectancy_r"])
    be = best["expectancy_r"]
    if not neigh or not be or be <= 0:
        return {"ratio": None, "neighbours": len(neigh), "verdict": "n/a"}
    ratio = float(np.mean(neigh)) / be
    verdict = "plateau" if ratio >= 0.7 else "slope" if ratio >= 0.4 else "spike"
    return {"ratio": round(ratio, 3), "neighbours": len(neigh), "verdict": verdict}


def optimize(
    spec: StrategySpec,
    params: list[dict[str, Any]],
    mk: Market,
    ledger: Ledger,
    progress: Callable[[float, str], None] | None = None,
    window: tuple[datetime, datetime] | None = None,
    record: bool = True,
) -> dict[str, Any]:
    for p in params:
        get_path(spec.model_dump(mode="json"), p["path"])  # KeyError on an unknown path
    assigns = grid(params)
    runs.save_spec(spec, ledger)
    win = window or "A"
    table: list[dict[str, Any]] = []
    for k, a in enumerate(assigns):
        if progress:
            progress(k / len(assigns), f"variant {k + 1} / {len(assigns)}")
        try:
            v = with_params(spec, a)
        except ValueError as e:
            table.append({"params": a, "spec_hash": None, "invalid": str(e).splitlines()[0]})
            continue
        m, _ = evaluate_variant(v, mk, win)
        if record:
            ledger.record_trial(
                v.meta.family, v.spec_hash, "A", m.get("sharpe_per_trade"), m["n"], "optimize"
            )
        table.append(_row(a, v, m))
    ok = [r for r in table if r.get("n", 0) >= MIN_TRADES and r.get("expectancy_r") is not None]
    best = max(ok, key=lambda r: r["expectancy_r"]) if ok else None
    out: dict[str, Any] = {
        "params": params,
        "window": "tier A" if window is None else [window[0].isoformat(), window[1].isoformat()],
        "scenario": SCENARIO,
        "min_trades": MIN_TRADES,
        "variants": len(assigns),
        "table": table,
        "best": best,
        "plateau": plateau(table, params, best) if best else None,
    }
    if best and record:
        n_trials, sharpes = ledger.trials(spec.meta.family)
        v = with_params(spec, best["params"])
        m, _ = evaluate_variant(v, mk, win)
        out["best_deflated_sharpe"] = runs.deflated(v, m, ledger)
        out["family_trials"] = n_trials
    return out


def run_optimize(spec, params, mk, ledger, progress=None) -> dict[str, Any]:
    """Optimise, then store it as a run (kind ``optimize``) so it appears in history."""
    res = optimize(spec, params, mk, ledger, progress)
    run_id = runs.new_run_id("optimize", spec.spec_hash, "A")
    doc = {
        "run_id": run_id,
        "kind": "optimize",
        "spec_hash": spec.spec_hash,
        "family": spec.meta.family,
        "name": spec.meta.name,
        "spec": spec.model_dump(mode="json"),
        "tier": "A",
        "lineage": {
            "dataset_id": mk.dataset_id,
            "cost_model_id": mk.cost_model_id,
            "feature_set_id": mk.feature_set_id,
        },
        "optimize": res,
    }
    runs.write_doc(run_id, doc)
    best = res.get("best") or {}
    ledger.record_run(
        run_id,
        "optimize",
        spec.spec_hash,
        spec.meta.family,
        "A",
        {
            "name": spec.meta.name,
            "variants": res["variants"],
            "best_params": best.get("params"),
            "expectancy_r": best.get("expectancy_r"),
            "n": best.get("n"),
            "plateau": (res.get("plateau") or {}).get("verdict"),
            "family_trials": res.get("family_trials"),
        },
    )
    return doc
