"""Deterministic M1 → M5 / M15 / H1 aggregation, and verification against the
broker's own bars."""

from __future__ import annotations

from typing import Any

import polars as pl

EVERY = {"M5": "5m", "M15": "15m", "H1": "1h"}
MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60}


def aggregate(m1: pl.DataFrame, timeframe: str) -> pl.DataFrame:
    """Bars are labelled by their open time. ``m1_bars`` records how many M1 bars
    formed each bar, so incomplete bars stay visible rather than silently mixed in."""
    return (
        m1.sort("ts_utc")
        .group_by_dynamic("ts_utc", every=EVERY[timeframe], closed="left", label="left")
        .agg(
            ts_server=pl.col("ts_server").first().dt.truncate(EVERY[timeframe]),
            open=pl.col("open").first(),
            high=pl.col("high").max(),
            low=pl.col("low").min(),
            close=pl.col("close").last(),
            tick_volume=pl.col("tick_volume").sum(),
            spread_points_min=pl.col("spread_points").min(),
            spread_points_max=pl.col("spread_points").max(),
            m1_bars=pl.len().cast(pl.Int16),
        )
    )


def verify_against_reference(
    derived: pl.DataFrame, native: pl.DataFrame, tol: float = 1e-6
) -> dict[str, Any]:
    """Compare our bars with the broker's native bars on the broker clock.

    Differences are expected only where the broker has M1 bars missing from its
    archive; a low match rate means our aggregation or clock handling is wrong.
    """
    j = derived.join(native, on="ts_server", how="full", suffix="_native", coalesce=True)
    both = j.filter(pl.col("open").is_not_null() & pl.col("open_native").is_not_null())
    match = both.filter(
        ((pl.col("open") - pl.col("open_native")).abs() <= tol)
        & ((pl.col("high") - pl.col("high_native")).abs() <= tol)
        & ((pl.col("low") - pl.col("low_native")).abs() <= tol)
        & ((pl.col("close") - pl.col("close_native")).abs() <= tol)
    )
    return {
        "derived_bars": derived.height,
        "native_bars": native.height,
        "compared": both.height,
        "ohlc_exact_match": match.height,
        "ohlc_match_rate": round(match.height / both.height, 6) if both.height else None,
        "only_in_derived": j.filter(pl.col("open_native").is_null()).height,
        "only_in_native": j.filter(pl.col("open").is_null()).height,
    }
