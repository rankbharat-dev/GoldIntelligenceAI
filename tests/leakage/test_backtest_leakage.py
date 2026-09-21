"""Backtester truth tests on a synthetic random walk with the real gold calendar.

1. Shifted-target canary (§7.2): on a random walk an honest strategy has ~zero edge
   before costs; the same strategy fed a feature shifted from the future shows a huge
   edge — so the check is not blind.
2. Planted edge: a known drift after a pattern is found, with the right sign.
3. Entries never happen before the decision; decisions never before the bar closes.
4. Determinism: two runs give identical trades.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import polars as pl
import pytest

from candle_intel.backtest import engine, metrics
from candle_intel.backtest.market import Market
from candle_intel.backtest.split import Split
from candle_intel.features.compute import Bars, compute_features
from tests.unit.test_backtest import SPEC

SPLIT = Split(datetime(2025, 2, 10), datetime(2025, 3, 15), datetime(2025, 3, 29))


def costs(m1: pl.DataFrame) -> pl.DataFrame:
    s = m1["spread_points"].clip(lower_bound=1).cast(pl.Float64)
    return pl.DataFrame(
        {
            "ts_utc": m1["ts_utc"],
            "spread_optimistic": s,
            "spread_base": s,
            "spread_pessimistic": s * 1.5,
            "spread_source": ["modeled"] * m1.height,
            "in_rollover_window": [False] * m1.height,
        }
    )


@pytest.fixture(scope="module")
def syn(syn_m1):
    feats = compute_features(Bars.from_m1(syn_m1), 0.001, research_start=SPLIT.a_start)
    return syn_m1, feats


def mk_of(m1: pl.DataFrame, feats: pl.DataFrame) -> Market:
    return Market.from_frames(
        m1.select("ts_utc", "open", "high", "low", "close"), costs(m1), feats, SPEC, SPLIT
    )


def spec(cond: list[dict], side: str = "long") -> engine.StrategySpec:
    return engine.StrategySpec.model_validate(
        {
            "meta": {"name": "syn", "family": "syn"},
            "entries": [{"side": side, "conditions": cond}],
            "exit": {"stop_atr": 1.0, "target_atr": 1.0, "time_exit_bars": 6},
        }
    )


def before_costs(s, mk: Market, tier="AB") -> dict:
    trades, _ = engine.run(s, mk, tier, ("optimistic",))
    return metrics.summarise(trades, 10_000) | {"_trades": trades}


def test_honest_vs_shifted_target_canary(syn) -> None:
    m1, feats = syn
    s = spec([{"feature": "ret_atr", "op": ">", "value": 0.3}])
    honest = before_costs(s, mk_of(m1, feats))
    # Leak: this bar's row carries the NEXT bar's return (known only 5 minutes later).
    leaky_feats = feats.sort("event_time").with_columns(pl.col("ret_atr").shift(-1))
    leaky = before_costs(s, mk_of(m1, leaky_feats))
    assert honest["n"] > 300 and leaky["n"] > 300
    assert abs(honest["expectancy_before_costs_r"]) < 0.08  # random walk → no edge
    assert leaky["expectancy_before_costs_r"] > 0.3  # the canary sings


def plant(m1: pl.DataFrame, feats: pl.DataFrame, when: pl.Expr, size: float = 1.5) -> pl.DataFrame:
    """After every M5 bar where ``when`` holds, price drifts up by ``size`` × that bar's
    ATR over the next 30 minutes, then fades back over 30 minutes."""
    f = feats.filter(when).select("available_at", "atr_pts").drop_nulls()
    t = m1["ts_utc"].dt.epoch("s").to_numpy()
    bump = np.zeros(len(t))
    for at, atr in f.iter_rows():
        i0 = np.searchsorted(
            t, int(at.timestamp() if at.tzinfo else (at - datetime(1970, 1, 1)).total_seconds())
        )
        k = np.arange(60)
        shape = np.where(k < 30, (k + 1) / 30, (60 - k) / 30)
        seg = slice(i0, min(i0 + 60, len(t)))
        bump[seg] += size * atr * 0.001 * shape[: seg.stop - seg.start]
    return m1.with_columns([(pl.col(c) + pl.Series(bump)).alias(c) for c in ("open", "high", "low", "close")])


def test_planted_edge_is_found(syn) -> None:
    m1, feats = syn
    planted = plant(m1, feats, pl.col("dirs_3") == "DDU")
    s = spec([{"feature": "dirs_3", "op": "==", "value": "DDU"}])
    found = before_costs(s, mk_of(planted, feats))
    control = before_costs(s, mk_of(m1, feats))
    assert found["n"] > 300
    assert found["expectancy_before_costs_r"] > 0.3
    assert abs(control["expectancy_before_costs_r"]) < 0.08
    # the mirror strategy (short the same pattern) must lose on the planted data
    short = before_costs(
        spec([{"feature": "dirs_3", "op": "==", "value": "DDU"}], "short"), mk_of(planted, feats)
    )
    assert short["expectancy_before_costs_r"] < -0.3


def test_entries_follow_decisions(syn) -> None:
    m1, feats = syn
    s = spec([{"feature": "close_loc", "op": ">", "value": 0.8}])
    trades, sigs = engine.run(s, mk_of(m1, feats), "AB")
    assert trades.height > 0
    assert (trades["entry_time"] >= trades["decision_time"]).all()
    assert (trades["entry_time"] - trades["decision_time"] <= timedelta(minutes=5)).all()
    assert (trades["exit_time"] >= trades["entry_time"]).all()
    # a decision is a bar close: 5 minutes after an M5 open
    assert (sigs["decision_time"] - sigs["event_time"] == timedelta(minutes=5)).all()
    # one position at a time: each entry after the previous exit, per scenario
    for sc in ("optimistic", "base", "pessimistic"):
        x = trades.filter(pl.col("scenario") == sc).sort("entry_time")
        assert (x["entry_time"].shift(-1).drop_nulls() > x["exit_time"].head(x.height - 1)).all()
    # pessimistic is never cheaper than optimistic per trade on the same entries
    o = trades.filter(pl.col("scenario") == "optimistic")
    p = trades.filter(pl.col("scenario") == "pessimistic")
    both = o.join(p, on="decision_time", suffix="_p")
    assert (
        both["cost_spread_r_p"] + both["cost_slippage_r_p"]
        >= both["cost_spread_r"] + both["cost_slippage_r"] - 1e-12
    ).all()


def test_deterministic(syn) -> None:
    m1, feats = syn
    s = spec([{"feature": "dirs_3", "op": "in", "value": ["UUD", "DDU"]}])
    a, _ = engine.run(s, mk_of(m1, feats), "AB")
    b, _ = engine.run(s, mk_of(m1, feats), "AB")
    assert a.equals(b)
