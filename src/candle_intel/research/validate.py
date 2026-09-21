"""Strategy Validation Lab — does the edge survive honest tests? (MASTER_PROMPT §6 "Validate")

One validation = these steps, each stored:

1. Backtests on tier A (development), tier B (validation) and A∪B (continuous).
2. Walk-forward over A∪B. With a parameter grid: re-optimise on each training window
   (12 months) and trade the next 3 months with the winner — only those out-of-sample
   months count. Without a grid: the fixed spec, window by window (is it stable in time?).
3. Ambiguity-policy sensitivity: A∪B again with the optimistic intrabar policy — if
   the result depends on it, the edge lives inside single M1 bars and needs ticks.
4. Robustness from the A∪B run: stationary-bootstrap CI, Monte Carlo drawdown, cost stress.
5. The §15 checklist, with every failure named.

Tier C is never touched here; it has its own one-time unseal.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import polars as pl

from candle_intel.backtest import engine, metrics
from candle_intel.backtest.market import Market
from candle_intel.research import checklist, optimize, runs
from candle_intel.research.ledger import Ledger
from candle_intel.strategy.spec import StrategySpec, with_params

TRAIN_MONTHS = 12
TEST_MONTHS = 3


def _add_months(t: datetime, n: int) -> datetime:
    m = t.month - 1 + n
    return t.replace(year=t.year + m // 12, month=m % 12 + 1, day=1)


def folds(start: datetime, end: datetime) -> list[tuple[datetime, datetime, datetime]]:
    """(train_start, test_start, test_end) — rolling 12-month train, 3-month test."""
    first = _add_months(start.replace(day=1), 1) if start.day > 1 else start
    out = []
    ts = first
    while True:
        test_start = _add_months(ts, TRAIN_MONTHS)
        test_end = min(_add_months(test_start, TEST_MONTHS), end)
        if test_start >= end or (test_end - test_start) < timedelta(days=20):
            break
        out.append((ts, test_start, test_end))
        ts = _add_months(ts, TEST_MONTHS)
    return out


def walk_forward(
    spec: StrategySpec,
    mk: Market,
    ledger: Ledger,
    params: list[dict[str, Any]] | None,
    progress=None,
) -> dict[str, Any]:
    start, end = mk.split.a_start, mk.split.c_start
    fs = folds(start, end)
    oos: list[pl.DataFrame] = []
    rows = []
    for k, (tr0, te0, te1) in enumerate(fs):
        if progress:
            progress(k / max(len(fs), 1), f"fold {k + 1} / {len(fs)}")
        chosen, train_best = spec, None
        if params:
            res = optimize.optimize(spec, params, mk, ledger, None, window=(tr0, te0), record=True)
            train_best = res["best"]
            if train_best:
                chosen = with_params(spec, train_best["params"])
        trades, _ = engine.run(chosen, mk, (te0, te1), ("pessimistic",))
        m = metrics.summarise(trades, spec.sizing.initial_equity_usd)
        oos.append(trades)
        rows.append(
            {
                "train": [tr0.isoformat(), te0.isoformat()],
                "test": [te0.isoformat(), te1.isoformat()],
                "chosen_params": train_best["params"] if train_best else None,
                "train_expectancy_r": train_best["expectancy_r"] if train_best else None,
                "n": m["n"],
                "expectancy_r": m.get("expectancy_r"),
                "total_r": m.get("total_r"),
            }
        )
    all_oos = pl.concat(oos) if oos else pl.DataFrame()
    summary = metrics.summarise(all_oos, spec.sizing.initial_equity_usd) if oos else {"n": 0}
    pos = [r for r in rows if r["expectancy_r"] is not None and r["n"] >= 10]
    return {
        "mode": "re-optimised per fold" if params else "fixed spec per window",
        "train_months": TRAIN_MONTHS,
        "test_months": TEST_MONTHS,
        "folds": rows,
        "positive_folds": sum(1 for r in pos if r["expectancy_r"] > 0),
        "scored_folds": len(pos),
        "oos": {
            k: summary.get(k)
            for k in ("n", "expectancy_r", "profit_factor", "max_dd_r", "win_rate", "total_r", "equity")
        },
    }


def validate(
    spec: StrategySpec,
    mk: Market,
    ledger: Ledger,
    params: list[dict[str, Any]] | None = None,
    progress=None,
) -> dict[str, Any]:
    def step(lo: float, hi: float, msg: str):
        return (lambda f, m: progress(lo + (hi - lo) * f, f"{msg}: {m}")) if progress else None

    docs = {}
    for i, tier in enumerate(("A", "B", "AB")):
        if progress:
            progress(0.05 + 0.15 * i, f"backtest tier {tier}")
        docs[tier] = runs.run_backtest(spec, tier, mk, ledger, kind="backtest", source="validate")
    wf = walk_forward(spec, mk, ledger, params, step(0.5, 0.9, "walk-forward"))
    if progress:
        progress(0.92, "ambiguity sensitivity")
    t_opt, _ = engine.run(spec, mk, "AB", ("pessimistic",), policy="optimistic")
    m_opt = metrics.summarise(t_opt, spec.sizing.initial_equity_usd)
    pess_ab = docs["AB"]["results"]["pessimistic"]
    ambiguity = {
        "pessimistic_policy_expectancy_r": pess_ab.get("expectancy_r"),
        "optimistic_policy_expectancy_r": m_opt.get("expectancy_r"),
        "difference_r": None
        if m_opt.get("expectancy_r") is None or pess_ab.get("expectancy_r") is None
        else round(m_opt["expectancy_r"] - pess_ab["expectancy_r"], 4),
    }
    ho = ledger.holdout_status(spec.meta.family)
    c_doc = None
    if ho and ho["strategy_id"] == spec.spec_hash:
        c_runs = [r for r in ledger.runs(spec.spec_hash) if r["tier"] == "C" and r["kind"] == "backtest"]
        if c_runs:
            c_doc = runs.load_run(c_runs[0]["run_id"])
    check = checklist.evaluate(docs["A"], docs["B"], docs["AB"], c_doc, 1 if ho else 0)
    run_id = runs.new_run_id("validate", spec.spec_hash, "AB")
    doc = {
        "run_id": run_id,
        "kind": "validate",
        "spec_hash": spec.spec_hash,
        "family": spec.meta.family,
        "name": spec.meta.name,
        "spec": spec.model_dump(mode="json"),
        "tier": "AB",
        "backtests": {k: v["run_id"] for k, v in docs.items()},
        "tiers": {
            k: {
                s: {
                    kk: v["results"][s].get(kk)
                    for kk in ("n", "expectancy_r", "profit_factor", "max_dd_r", "win_rate")
                }
                for s in ("optimistic", "base", "pessimistic")
            }
            for k, v in docs.items()
        },
        "walk_forward": wf,
        "ambiguity_sensitivity": ambiguity,
        "robustness": docs["AB"]["robustness"],
        "deflated_sharpe": docs["AB"]["deflated_sharpe"],
        "stability": pess_ab.get("stability"),
        "by_year": pess_ab.get("by_year"),
        "by_session": pess_ab.get("by_session"),
        "by_vol_regime": pess_ab.get("by_vol_regime"),
        "checklist": check,
        "holdout": ho,
        "holdout_run": c_doc["run_id"] if c_doc else None,
        "split": mk.split.to_dict(),
    }
    runs.write_doc(run_id, doc)
    ledger.record_run(
        run_id,
        "validate",
        spec.spec_hash,
        spec.meta.family,
        "AB",
        {
            "name": spec.meta.name,
            "verdict": check["verdict"],
            "failed": check["failed"],
            "pending": check["pending"],
            "expectancy_r": pess_ab.get("expectancy_r"),
            "n": pess_ab.get("n"),
            "oos_expectancy_r": wf["oos"].get("expectancy_r"),
            "family_trials": docs["AB"]["family_trials"],
        },
    )
    if progress:
        progress(1.0, "done")
    return doc


def unseal_and_test(
    spec: StrategySpec, mk: Market, ledger: Ledger, reason: str, progress=None
) -> dict[str, Any]:
    """The family's single look at tier C. Logged before anything is computed."""
    ledger.unseal(spec.meta.family, spec.spec_hash, reason)
    if progress:
        progress(0.1, "holdout unsealed — running tier C")
    return runs.run_backtest(spec, "C", mk, ledger, kind="backtest", source="holdout", progress=progress)
