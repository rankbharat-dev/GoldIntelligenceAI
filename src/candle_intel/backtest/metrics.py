"""Metrics of one scenario's trade list (blueprint §10, §15).

Everything is in R (net result ÷ initial risk) first; USD follows from sizing.
Breakdowns by year / month / session / weekday / volatility regime / side feed the
stability score: the share of buckets whose expectancy has the same sign as the
overall one (§10 requires ≥ 70 % for years and sessions).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import polars as pl

MIN_BUCKET_TRADES = 10  # buckets smaller than this are shown but not scored for stability
EQUITY_POINTS = 1500


def _f(x: Any, d: int = 4) -> float | None:
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) or math.isinf(x) else round(x, d)


def drawdown(values: np.ndarray, start: float = 0.0) -> float:
    """Largest peak-to-trough fall of a cumulative series (same units)."""
    if values.size == 0:
        return 0.0
    path = np.concatenate([[start], values])
    return float((np.maximum.accumulate(path) - path).max())


def profit_factor(r: np.ndarray) -> float | None:
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    if losses == 0:
        return None if gains == 0 else float("inf")
    return float(gains / losses)


def breakdown(trades: pl.DataFrame, key: pl.Expr, name: str) -> list[dict[str, Any]]:
    if trades.is_empty():
        return []
    g = (
        trades.group_by(key.alias(name))
        .agg(
            n=pl.len(),
            expectancy_r=pl.col("r_net").mean(),
            total_r=pl.col("r_net").sum(),
            win_rate=(pl.col("r_net") > 0).mean(),
        )
        .sort(name)
    )
    return [
        {name: r[name], "n": r["n"]} | {k: _f(r[k]) for k in ("expectancy_r", "total_r", "win_rate")}
        for r in g.iter_rows(named=True)
    ]


def stability(buckets: list[dict[str, Any]]) -> dict[str, Any]:
    """Share of buckets (≥ MIN_BUCKET_TRADES trades) with positive expectancy.

    §10 asks for the edge to be "same-signed" in ≥ 70 % of buckets. The edge being
    promoted is a profit (r_net already folds in long/short), so the sign that counts is
    positive: a strategy that loses consistently is stable, but not an edge."""
    scored = [b for b in buckets if b["n"] >= MIN_BUCKET_TRADES and b["expectancy_r"] is not None]
    if not scored:
        return {"score": None, "buckets_scored": 0}
    pos = sum(1 for b in scored if b["expectancy_r"] > 0)
    return {"score": round(pos / len(scored), 4), "buckets_scored": len(scored), "positive": pos}


def equity_curve(trades: pl.DataFrame) -> dict[str, list]:
    if trades.is_empty():
        return {"time": [], "cum_r": [], "equity_usd": []}
    t = trades.sort("exit_time")
    cum = t["r_net"].cum_sum()
    idx = np.unique(np.linspace(0, t.height - 1, min(t.height, EQUITY_POINTS)).astype(int))
    return {
        "time": t["exit_time"].dt.epoch("s").gather(idx).to_list(),
        "cum_r": [round(v, 4) for v in cum.gather(idx).to_list()],
        "equity_usd": [round(v, 2) for v in t["equity_usd"].gather(idx).to_list()],
    }


def _ruin(t: pl.DataFrame) -> str | None:
    """When the simulated account first hit zero (the USD path stops there)."""
    blown = t.filter(pl.col("equity_usd") <= 0)
    return None if blown.is_empty() else blown["exit_time"].min().isoformat()


def summarise(trades: pl.DataFrame, initial_equity: float) -> dict[str, Any]:
    t = trades.sort("exit_time")
    r = t["r_net"].to_numpy()
    n = len(r)
    base: dict[str, Any] = {"n": n}
    if n == 0:
        return base | {"expectancy_r": None, "profit_factor": None, "max_dd_r": 0.0, "note": "no trades"}
    mean, sd = float(r.mean()), float(r.std(ddof=1)) if n > 1 else 0.0
    z = (r - mean) / sd if sd > 0 else np.zeros(n)
    eq = t["equity_usd"].to_numpy()
    peak = np.maximum.accumulate(np.concatenate([[initial_equity], eq]))
    dd_pct = float(((peak[1:] - eq) / peak[1:]).max()) if n else 0.0
    by_year = breakdown(t, pl.col("decision_time").dt.year(), "year")
    by_session = breakdown(t, pl.col("session"), "session")
    return base | {
        "wins": int((r > 0).sum()),
        "win_rate": _f((r > 0).mean()),
        "expectancy_r": _f(mean),
        "median_r": _f(np.median(r)),
        "std_r": _f(sd),
        "stderr_r": _f(sd / math.sqrt(n)) if n > 1 else None,
        "total_r": _f(r.sum(), 2),
        "profit_factor": _f(profit_factor(r)),
        "max_dd_r": _f(drawdown(np.cumsum(r)), 2),
        "max_dd_pct": _f(dd_pct),
        "final_equity_usd": _f(eq[-1], 2),
        "return_pct": _f((eq[-1] / initial_equity - 1) * 100, 2),
        "ruined_at": _ruin(t),
        "sharpe_per_trade": _f(mean / sd) if sd > 0 else None,
        "skew": _f((z**3).mean()),
        "kurtosis": _f((z**4).mean()),  # non-excess (normal = 3)
        "avg_hold_minutes": _f(t["bars_held_m1"].mean(), 1),
        "ambiguity_rate": _f(t["ambiguous"].mean()),
        "measured_spread_share": _f(t["spread_measured"].mean()),
        "expectancy_before_costs_r": _f(t["r_before_costs"].mean()),
        "costs_r": {
            k.removeprefix("cost_").removesuffix("_r"): _f(t[k].mean())
            for k in ("cost_spread_r", "cost_slippage_r", "cost_commission_r", "cost_swap_r")
        },
        "long_trades": int((t["side"] > 0).sum()),
        "short_trades": int((t["side"] < 0).sum()),
        "exit_reasons": dict(t.group_by("exit_reason").len().sort("exit_reason").iter_rows()),
        "first_trade": t["decision_time"].min().isoformat(),
        "last_trade": t["decision_time"].max().isoformat(),
        "by_year": by_year,
        "by_month": breakdown(t, pl.col("decision_time").dt.strftime("%Y-%m"), "month"),
        "by_session": by_session,
        "by_weekday": breakdown(t, pl.col("weekday"), "weekday"),
        "by_vol_regime": breakdown(t, pl.col("vol_regime").fill_null("unknown"), "vol_regime"),
        "by_side": breakdown(
            t, pl.when(pl.col("side") > 0).then(pl.lit("long")).otherwise(pl.lit("short")), "side"
        ),
        "stability": {"year": stability(by_year), "session": stability(by_session)},
        "equity": equity_curve(t),
    }
