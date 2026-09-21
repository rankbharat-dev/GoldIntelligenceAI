"""M5 volatility regime used to condition the spread model (blueprint §6, Layer 1).

Raw ATR is useless as a regime label across 2021–2026: gold went from ~1,800 to
~4,400 and M5 ATR roughly sextupled, so a fixed ATR tercile would put almost the
whole tick window in "high". The regime is therefore *relative*: ATR(14) divided
by its own trailing ~20-trading-day median. Terciles of that ratio are stable
across the price history.

Every value is known at the bar's open (computed from completed bars only), so
the bucket can be used at entry time without look-ahead.
"""

from __future__ import annotations

import polars as pl

ATR_BARS = 14
BASELINE_BARS = 288 * 20  # ~20 trading days of M5 bars
MIN_BASELINE_BARS = 288 * 5
BUCKETS = ("low", "mid", "high")


def m5_volatility(m5: pl.DataFrame, point: float) -> pl.DataFrame:
    """ts_utc, atr_points, vol_ratio — both from bars strictly before ts_utc."""
    prev_close = pl.col("close").shift()
    tr = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - prev_close).abs(),
        (pl.col("low") - prev_close).abs(),
    )
    atr = tr.rolling_mean(ATR_BARS).shift()  # known at the open of the bar
    return (
        m5.sort("ts_utc")
        .select("ts_utc", atr_points=atr / point)
        .with_columns(
            vol_ratio=pl.col("atr_points")
            / pl.col("atr_points").rolling_median(BASELINE_BARS, min_samples=MIN_BASELINE_BARS)
        )
    )


def tercile_edges(vol: pl.DataFrame, start=None) -> tuple[float, float]:
    """Tercile boundaries of vol_ratio over the research window (from ``start``)."""
    v = vol if start is None else vol.filter(pl.col("ts_utc") >= start)
    r = v["vol_ratio"].drop_nulls()
    return float(r.quantile(1 / 3)), float(r.quantile(2 / 3))


def bucket(edges: tuple[float, float]) -> pl.Expr:
    lo, hi = edges
    r = pl.col("vol_ratio")
    return (
        pl.when(r.is_null())
        .then(pl.lit("mid"))  # warm-up bars: no baseline yet → neutral regime
        .when(r < lo)
        .then(pl.lit("low"))
        .when(r < hi)
        .then(pl.lit("mid"))
        .otherwise(pl.lit("high"))
        .alias("vol_bucket")
    )
