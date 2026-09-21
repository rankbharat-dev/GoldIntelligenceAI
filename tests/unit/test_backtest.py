"""Backtester checked by hand on tiny, fully known price paths (blueprint §7.3)."""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest

from candle_intel.backtest import engine, metrics
from candle_intel.backtest.market import Market
from candle_intel.backtest.split import Split
from candle_intel.costs.execution import Commission
from candle_intel.strategy.spec import StrategySpec, with_params

SPEC = {
    "point": 0.001,
    "trade_contract_size": 100.0,
    "volume_step": 0.01,
    "volume_min": 0.01,
    "volume_max": 200.0,
    "swap_mode": 1,
    "swap_long": -50.0,
    "swap_short": 20.0,
    "swap_rollover3days": 3,
}
SPLIT = Split(datetime(2025, 1, 1), datetime(2025, 3, 1), datetime(2025, 4, 1))
T0 = datetime(2025, 3, 12, 10, 0)  # Wednesday, London session, far from rollover
ATR = 1000.0  # points = 1.00 USD


def market(bars: list[tuple[float, float, float, float]], side_dir: int = 1, spread: float = 100.0) -> Market:
    """M1 bars from T0+5 min (the first fill bar); one M5 decision bar at T0 whose
    feature ``dir`` = ``side_dir``."""
    times = [T0 + timedelta(minutes=5 + i) for i in range(len(bars))]
    m1 = pl.DataFrame(
        {
            "ts_utc": times,
            "open": [b[0] for b in bars],
            "high": [b[1] for b in bars],
            "low": [b[2] for b in bars],
            "close": [b[3] for b in bars],
        }
    ).with_columns(pl.col("ts_utc").cast(pl.Datetime("us")))
    costs = pl.DataFrame(
        {
            "ts_utc": times,
            "spread_optimistic": [spread] * len(bars),
            "spread_base": [spread] * len(bars),
            "spread_pessimistic": [2 * spread] * len(bars),
            "spread_source": ["measured"] * len(bars),
            "in_rollover_window": [False] * len(bars),
        }
    ).with_columns(pl.col("ts_utc").cast(pl.Datetime("us")))
    feats = pl.DataFrame(
        {
            "event_time": [T0],
            "available_at": [T0 + timedelta(minutes=5)],
            "in_research_window": [True],
            "dir": [side_dir],
            "hyg_no_entry": [False],
            "atr_pts": [ATR],
            "session": ["london"],
            "vol_regime": ["mid"],
            "hour_utc": [10],
            "dow": [3],
            "spread_rel": [1.0],
        }
    ).with_columns(pl.col("event_time", "available_at").cast(pl.Datetime("us")), pl.col("dir").cast(pl.Int8))
    return Market.from_frames(m1, costs, feats, SPEC, SPLIT, Commission())


def spec(side: str = "long", **exit_: float) -> StrategySpec:
    return StrategySpec.model_validate(
        {
            "meta": {"name": "t", "family": "unit"},
            "entries": [
                {
                    "side": side,
                    "conditions": [{"feature": "dir", "op": "==", "value": 1 if side == "long" else -1}],
                }
            ],
            "exit": {"stop_atr": 1.0, "target_atr": 2.0, "flat_before_weekend": False} | exit_,
        }
    )


def one(mk: Market, s: StrategySpec, scenario: str = "optimistic", policy="pessimistic") -> dict:
    trades, _ = engine.run(s, mk, "B", (scenario,), policy)
    assert trades.height == 1
    return trades.row(0, named=True)


FLAT = (2900.0, 2900.05, 2899.95, 2900.0)


def test_long_target_by_hand() -> None:
    mk = market([(2900.0, 2900.3, 2899.8, 2900.2), (2900.2, 2902.2, 2900.1, 2902.0), FLAT])
    t = one(mk, spec())
    # optimistic: ask = bid 2900.000 + 100 pts spread, no market slippage
    assert t["entry_time"] == T0 + timedelta(minutes=5)
    assert t["entry_price"] == pytest.approx(2900.100)
    assert t["stop_initial"] == pytest.approx(2899.100)
    assert t["target"] == pytest.approx(2902.100)
    assert t["exit_reason"] == "target" and t["exit_time"] == T0 + timedelta(minutes=6)
    assert t["exit_price"] == pytest.approx(2902.100)  # limit: no slippage
    assert t["r_net"] == pytest.approx(2.0)
    assert t["cost_spread_r"] == pytest.approx(0.1)
    assert t["r_before_costs"] == pytest.approx(2.1)
    assert not t["ambiguous"]


def test_base_scenario_adds_market_slippage() -> None:
    mk = market([(2900.0, 2900.3, 2899.8, 2900.2), (2900.2, 2902.2, 2900.1, 2902.0)])
    t = one(mk, spec(), "base")
    # base market slippage = 5 pts + 1 % of ATR (10 pts) = 15 pts
    assert t["entry_price"] == pytest.approx(2900.0 + 0.100 + 0.015)
    assert t["r_net"] == pytest.approx(2.0)  # the target moves with the fill


def test_short_stop_uses_the_ask() -> None:
    # short sells the bid 2900.000; stop = 2901.000 on the ASK, i.e. bid high ≥ 2900.900
    mk = market([(2900.0, 2900.5, 2899.9, 2900.4), (2900.4, 2900.95, 2900.3, 2900.8)], side_dir=-1)
    t = one(mk, spec("short"))
    assert t["entry_price"] == pytest.approx(2900.0)
    assert t["exit_reason"] == "stop"
    # optimistic stop slippage 0.5 % of ATR = 5 pts, adverse (buying higher)
    assert t["exit_price"] == pytest.approx(2901.005)
    assert t["r_net"] == pytest.approx(-1.005)
    assert t["cost_spread_r"] == pytest.approx(0.1)


def test_ambiguous_bar_follows_the_policy() -> None:
    bars = [(2900.0, 2900.3, 2899.8, 2900.2), (2900.2, 2902.5, 2898.5, 2900.0)]
    pess = one(market(bars), spec(), policy="pessimistic")
    opt = one(market(bars), spec(), policy="optimistic")
    assert pess["ambiguous"] and pess["exit_reason"] == "stop" and pess["r_net"] < -1
    assert opt["ambiguous"] and opt["exit_reason"] == "target" and opt["r_net"] == pytest.approx(2.0)


def test_gap_through_stop_fills_at_the_open() -> None:
    mk = market([(2900.0, 2900.3, 2899.8, 2900.2), (2898.0, 2898.2, 2897.9, 2898.1)])
    t = one(mk, spec())
    assert t["exit_reason"] == "stop_gap"
    assert t["exit_price"] == pytest.approx(2898.0 - 0.005)  # open minus stop slippage
    assert t["r_net"] == pytest.approx((2897.995 - 2900.1) / 1.0)


def test_time_exit_at_market() -> None:
    bars = [FLAT] * 20
    t = one(market(bars), spec(time_exit_bars=2))
    # decision T0+5; two M5 bars later = T0+15 → market exit at that M1 open (bid, no slippage optimistic)
    assert t["exit_reason"] == "time" and t["exit_time"] == T0 + timedelta(minutes=15)
    assert t["exit_price"] == pytest.approx(2900.0)
    assert t["r_net"] == pytest.approx(-0.1)


def test_trailing_stop_ratchets_at_m5_closes() -> None:
    up = [(2900.0 + 0.5 * i, 2900.1 + 0.5 * i, 2899.95 + 0.5 * i, 2900.0 + 0.5 * (i + 1)) for i in range(10)]
    drop = [(2905.0, 2905.0, 2903.0, 2903.2)]
    t = one(market(up + drop), spec(target_atr=None, trail_atr=1.0))
    assert t["exit_reason"] == "stop" and t["r_net"] > 1.0  # locked in profit


def test_no_trade_when_hygiene_blocks() -> None:
    mk = market([FLAT] * 5)
    mk._frame = mk._frame.with_columns(hyg_no_entry=pl.lit(True))
    trades, sigs = engine.run(spec(), mk, "B", ("optimistic",))
    assert sigs.height == 0 and trades.height == 0


def test_tier_boundary_is_respected() -> None:
    trades, _ = engine.run(spec(), market([FLAT] * 3), "A", ("optimistic",))
    assert trades.height == 0  # the decision is in tier B


def test_commission_and_swap_in_pessimistic() -> None:
    # hold across 17:00 NY (21:00 UTC in EDT) with a long time exit → one swap night
    s = spec(target_atr=None, time_exit_bars=150, stop_atr=5.0)
    mk = market([FLAT] * 800)
    t = one(mk, s, "pessimistic")
    risk = 5.0  # USD price distance
    assert t["cost_commission_r"] == pytest.approx(7.0 / 100 / risk)  # $7 / lot unconfirmed → price units
    # 10:05 → 22:35 UTC crosses the 21:00 UTC (17:00 NY, EDT) rollover on a Wednesday, the
    # triple-swap day: 3 nights × 50 pts × $0.1 = $15 / lot = 0.15 price → 0.03 R
    assert t["cost_swap_r"] == pytest.approx(0.03)
    # the exit is 150 M5 bars after decision
    assert t["exit_time"] == T0 + timedelta(minutes=5 + 750)


def test_metrics_summary_basic() -> None:
    mk = market([(2900.0, 2900.3, 2899.8, 2900.2), (2900.2, 2902.2, 2900.1, 2902.0)])
    trades, _ = engine.run(spec(), mk, "B", ("optimistic",))
    m = metrics.summarise(trades, 10_000)
    assert m["n"] == 1 and m["expectancy_r"] == pytest.approx(2.0) and m["win_rate"] == 1.0
    assert m["final_equity_usd"] == pytest.approx(10_000 + 2.0 * 1.0 * 100 * 1.0)  # 1 % of 10k = $100 = 1 lot


def test_spec_validation_and_params() -> None:
    s = spec()
    with pytest.raises(ValueError):
        StrategySpec.model_validate(s.model_dump() | {"exit": {"stop_atr": 1.0}})  # no exit besides stop
    with pytest.raises(ValueError):
        with_params(s, {"entries.0.conditions.0.feature": "not_a_feature"})
    with pytest.raises(ValueError, match="enforced"):
        with_params(s, {"entries.0.conditions.0.feature": "hyg_no_entry"})
    s2 = with_params(s, {"exit.stop_atr": 1.5})
    assert s2.spec_hash != s.spec_hash
    renamed = StrategySpec.model_validate(s.model_dump() | {"meta": s.meta.model_dump() | {"name": "other"}})
    assert renamed.spec_hash == s.spec_hash  # the name is not part of the rules
