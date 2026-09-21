"""Event-driven backtester (blueprint §6, §7.3; MASTER_PROMPT §7).

Timing, fixed for every strategy:

1. A signal is decided at the close of an M5 bar (its ``available_at``).
2. The entry fills at the **open of the first M1 bar at or after** that moment,
   as a market order: long pays the ask (bid + scenario spread) plus slippage,
   short sells the bid minus slippage. If the market is closed (next M1 bar more
   than ``MAX_ENTRY_DELAY_S`` later) the signal is dropped.
3. Stop and target are resolved on the **M1 path** from the entry bar on. Long exits
   sell at the bid; short exits buy at the ask (bid + that bar's spread). When stop
   and target are both reachable inside one M1 bar the ambiguity policy decides
   (default pessimistic: the stop) and the trade is flagged ambiguous.
4. A bar that opens beyond the stop fills at its open (gap); a target is a limit
   order and fills at its price.
5. Time exit, flat-before-weekend and end-of-tier exits are market orders at an M1 open.
6. One position at a time. A new signal is taken only after the previous exit.

Prices are bid prices (dataset ``price_side``); all distances in the spec are
multiples of the decision bar's ATR(14). Every quantity is deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import numpy as np
import polars as pl

from candle_intel.backtest.market import SCENARIOS, Market
from candle_intel.backtest.split import Tier
from candle_intel.costs import execution
from candle_intel.strategy.signals import columns_needed, signals
from candle_intel.strategy.spec import StrategySpec

AmbiguityPolicy = Literal["pessimistic", "optimistic"]
MAX_ENTRY_DELAY_S = 300  # the next M1 open must fall inside the M5 bar after the signal
M5 = 300
Window = tuple[datetime, datetime]


def window_of(mk: Market, tier: Tier | Window) -> tuple[datetime, datetime | None]:
    if isinstance(tier, tuple):
        start, end = tier
        if end > mk.split.c_start:
            raise ValueError("an explicit window may not reach into the sealed tier C")
        return start, end
    return mk.split.bounds(tier)


TRADE_SCHEMA = {
    "scenario": pl.String,
    "side": pl.Int8,
    "decision_time": pl.Datetime("us"),
    "entry_time": pl.Datetime("us"),
    "exit_time": pl.Datetime("us"),
    "entry_price": pl.Float64,
    "exit_price": pl.Float64,
    "stop_initial": pl.Float64,
    "target": pl.Float64,
    "exit_reason": pl.String,
    "ambiguous": pl.Boolean,
    "atr_pts": pl.Float64,
    "risk_pts": pl.Float64,
    "r_net": pl.Float64,
    "r_before_costs": pl.Float64,
    "cost_spread_r": pl.Float64,
    "cost_slippage_r": pl.Float64,
    "cost_commission_r": pl.Float64,
    "cost_swap_r": pl.Float64,
    "mfe_r": pl.Float64,
    "mae_r": pl.Float64,
    "bars_held_m1": pl.Int32,
    "spread_measured": pl.Boolean,
    "lots": pl.Float64,
    "pnl_usd": pl.Float64,
    "equity_usd": pl.Float64,
}


@dataclass
class _Exit:
    i: int  # M1 bar index of the fill
    price: float  # bid-side price for long, ask-side for short, before slippage
    reason: str
    ambiguous: bool = False
    order: execution.OrderType = "market"


def _utc(ts: int) -> datetime:
    return datetime.fromtimestamp(int(ts), tz=UTC).replace(tzinfo=None)


def _epoch(t: datetime) -> int:
    return int(t.replace(tzinfo=UTC).timestamp())


def _lots(equity: float, risk_pct: float, risk_price: float, spec: dict) -> float:
    step = float(spec.get("volume_step", 0.01)) or 0.01
    vmin = float(spec.get("volume_min", step))
    vmax = float(spec.get("volume_max", 100.0)) or 100.0
    raw = equity * risk_pct / 100.0 / (risk_price * float(spec["trade_contract_size"]))
    lots = np.floor(raw / step + 1e-9) * step
    return float(min(max(lots, vmin), vmax))


def _find_exit(
    mk: Market,
    scen: str,
    side: int,
    ei: int,
    end: int,
    stop: float,
    target: float | None,
    trail_pts: float | None,
    policy: AmbiguityPolicy,
) -> tuple[_Exit | None, float]:
    """Stop / target on bars [ei, end). Returns (exit or None, final stop)."""
    sp = mk.spread_px[scen]
    if trail_pts is None:
        sl = slice(ei, end)
        o, h, lo = mk.o[sl], mk.h[sl], mk.l[sl]
        s = sp[sl]
        if side > 0:
            stop_hit, tgt_hit = lo <= stop, (h >= target) if target is not None else np.zeros(len(o), bool)
        else:
            stop_hit = h + s >= stop
            tgt_hit = (lo + s <= target) if target is not None else np.zeros(len(o), bool)
        hit = np.flatnonzero(stop_hit | tgt_hit)
        if hit.size == 0:
            return None, stop
        return _resolve(mk, sp, side, ei, ei + int(hit[0]), stop, target, policy), stop

    # Trailing stop: sequential, the stop moves only at M5 closes and applies from the next bar.
    for j in range(ei, end):
        ex = _resolve_bar(mk, sp, side, ei, j, stop, target, policy)
        if ex is not None:
            return ex, stop
        if (mk.t[j] // 60 + 1) % 5 == 0:  # this M1 bar closes an M5 bar
            if side > 0:
                stop = max(stop, mk.c[j] - trail_pts * mk.point)
            else:
                stop = min(stop, mk.c[j] + sp[j] + trail_pts * mk.point)
    return None, stop


def _resolve(mk, sp, side, ei, j, stop, target, policy) -> _Exit:
    ex = _resolve_bar(mk, sp, side, ei, j, stop, target, policy)
    assert ex is not None
    return ex


def _resolve_bar(mk, sp, side, ei, j, stop, target, policy) -> _Exit | None:
    o, h, lo, s = mk.o[j], mk.h[j], mk.l[j], sp[j]
    if side > 0:
        if j > ei and target is not None and o >= target:
            return _Exit(j, target, "target", order="limit")
        if j > ei and o <= stop:
            return _Exit(j, o, "stop_gap", order="stop")
        sh, th = lo <= stop, target is not None and h >= target
    else:
        ask_o = o + s
        if j > ei and target is not None and ask_o <= target:
            return _Exit(j, target, "target", order="limit")
        if j > ei and ask_o >= stop:
            return _Exit(j, ask_o, "stop_gap", order="stop")
        sh, th = h + s >= stop, target is not None and lo + s <= target
    if sh and th:
        if policy == "pessimistic":
            return _Exit(j, stop, "stop", ambiguous=True, order="stop")
        return _Exit(j, target, "target", ambiguous=True, order="limit")
    if sh:
        return _Exit(j, stop, "stop", order="stop")
    if th:
        return _Exit(j, target, "target", order="limit")
    return None


def simulate(
    spec: StrategySpec,
    mk: Market,
    tier: Tier | Window,
    scenario: str,
    sigs: pl.DataFrame,
    policy: AmbiguityPolicy = "pessimistic",
    overlap: bool = False,
) -> pl.DataFrame:
    """Trades of one cost scenario on one tier (or an explicit [start, end) window
    inside the development/validation tiers, for walk-forward folds).

    ``overlap=True`` labels every signal independently (event studies, blueprint §8.1
    triple-barrier labels): same fills and costs, but no one-position-at-a-time rule.
    Its USD equity path is meaningless; use the R columns."""
    sc = execution.SCENARIOS[scenario]
    start, end_t = window_of(mk, tier)
    t0 = _epoch(start)
    t1 = _epoch(end_t) if end_t is not None else None
    n = len(mk.t)
    tier_end_i = int(np.searchsorted(mk.t, t1, "left")) if t1 is not None else n

    dts = sigs["decision_time"].dt.epoch("s").to_numpy()
    sides = sigs["side"].to_numpy()
    atrs = sigs["atr_pts"].to_numpy()
    first_i = np.searchsorted(mk.t, dts, "left")
    ex_spec = spec.exit
    comm_per_lot = mk.commission.usd(1.0, sc)
    cs = mk.contract_size
    pt = mk.point

    rows: list[dict] = []
    equity = spec.sizing.initial_equity_usd
    free_from = -1
    for k in range(len(dts)):
        dt = int(dts[k])
        if dt < t0 or (t1 is not None and dt >= t1) or dt < free_from:
            continue
        ei = int(first_i[k])
        if ei >= tier_end_i or mk.t[ei] - dt > MAX_ENTRY_DELAY_S:
            continue
        side, atr = int(sides[k]), float(atrs[k])
        slip_in = execution.slippage_points("market", atr, sc)
        spread_in = mk.spread[scenario][ei]
        entry = mk.o[ei] + (spread_in + slip_in) * pt if side > 0 else mk.o[ei] - slip_in * pt
        risk = ex_spec.stop_atr * atr * pt
        stop = entry - side * risk
        target = entry + side * ex_spec.target_atr * atr * pt if ex_spec.target_atr is not None else None

        # Hard end of the search: time exit, weekend, tier end, data end.
        end, reason = tier_end_i, "end_of_tier" if t1 is not None else "end_of_data"
        if ex_spec.time_exit_bars is not None:
            te = int(np.searchsorted(mk.t, dt + ex_spec.time_exit_bars * M5, "left"))
            if te < end:
                end, reason = te, "time"
        if ex_spec.flat_before_weekend:
            wf = np.flatnonzero(mk.weekend_flat[ei + 1 : end])
            if wf.size:
                end, reason = ei + 1 + int(wf[0]), "weekend"
        trail = ex_spec.trail_atr * atr if ex_spec.trail_atr is not None else None
        ex, _ = _find_exit(mk, scenario, side, ei, end, stop, target, trail, policy)
        if ex is None:
            if end >= n:  # no bar left to exit on — close at the last close
                j = n - 1
                ex = _Exit(j, mk.c[j] if side > 0 else mk.c[j] + mk.spread[scenario][j] * pt, "end_of_data")
            else:
                j = end
                px = mk.o[j] if side > 0 else mk.o[j] + mk.spread[scenario][j] * pt
                ex = _Exit(j, px, reason)
        slip_out = execution.slippage_points(ex.order, atr, sc, bool(mk.in_window[ex.i]))
        exit_px = ex.price - side * slip_out * pt

        entry_t, exit_t = _utc(mk.t[ei]), _utc(mk.t[ex.i])
        swap_usd_lot = execution.swap_usd(
            "long" if side > 0 else "short", 1.0, entry_t, exit_t, mk.symbol_spec
        )
        gross = (exit_px - entry) * side
        spread_out = mk.spread[scenario][ex.i] if side < 0 else 0.0
        spread_pts = spread_in if side > 0 else spread_out
        comm_px = comm_per_lot / cs
        swap_px = swap_usd_lot / cs
        r_net = (gross - comm_px - swap_px) / risk
        cost_spread_r = spread_pts * pt / risk
        cost_slip_r = (slip_in + slip_out) * pt / risk
        path = slice(ei, ex.i + 1)
        if side > 0:
            mfe, mae = mk.h[path].max() - entry, entry - mk.l[path].min()
        else:
            ask = mk.spread_px[scenario][path]
            mfe, mae = entry - (mk.l[path] + ask).min(), (mk.h[path] + ask).max() - entry
        # An account at or below zero is blown: R results continue (they do not depend on
        # size), the USD path stops — it cannot trade the minimum lot with no money.
        lots = _lots(equity, spec.sizing.risk_pct, risk, mk.symbol_spec) if equity > 0 else 0.0
        pnl = max(r_net * risk * cs * lots, -equity) if lots else 0.0
        equity += pnl
        rows.append(
            {
                "scenario": scenario,
                "side": side,
                "decision_time": _utc(dt),
                "entry_time": entry_t,
                "exit_time": exit_t,
                "entry_price": entry,
                "exit_price": exit_px,
                "stop_initial": stop,
                "target": target,
                "exit_reason": ex.reason,
                "ambiguous": ex.ambiguous,
                "atr_pts": atr,
                "risk_pts": risk / pt,
                "r_net": r_net,
                "r_before_costs": r_net + cost_spread_r + cost_slip_r + (comm_px + swap_px) / risk,
                "cost_spread_r": cost_spread_r,
                "cost_slippage_r": cost_slip_r,
                "cost_commission_r": comm_px / risk,
                "cost_swap_r": swap_px / risk,
                "mfe_r": max(mfe, 0.0) / risk,
                "mae_r": max(mae, 0.0) / risk,
                "bars_held_m1": ex.i - ei + 1,
                "spread_measured": bool(mk.measured[ei] if side > 0 else mk.measured[ex.i]),
                "lots": lots,
                "pnl_usd": pnl,
                "equity_usd": equity,
            }
        )
        # Next decision strictly after this exit bar has opened.
        if not overlap:
            free_from = int(mk.t[ex.i]) + 1
    return pl.DataFrame(rows, schema=TRADE_SCHEMA)


def run(
    spec: StrategySpec,
    mk: Market,
    tier: Tier | Window,
    scenarios: tuple[str, ...] = SCENARIOS,
    policy: AmbiguityPolicy = "pessimistic",
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(trades of every scenario, signals). Trades carry the decision bar's context
    columns (session, vol regime, weekday) for breakdowns."""
    feats = mk.features(columns_needed(spec))
    sigs = signals(spec, feats)
    parts = [simulate(spec, mk, tier, s, sigs, policy) for s in scenarios]
    trades = pl.concat(parts) if parts else pl.DataFrame(schema=TRADE_SCHEMA)
    ctx = feats.select(
        pl.col("available_at").alias("decision_time"), "session", "vol_regime", pl.col("dow").alias("weekday")
    )
    trades = trades.join(ctx, on="decision_time", how="left")
    return trades, sigs
