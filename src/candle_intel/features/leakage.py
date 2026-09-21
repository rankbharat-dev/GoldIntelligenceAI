"""Leakage checks for feature pipelines (blueprint §7.2). Used by the leakage test
suite on synthetic data and by ``ci-features build`` on the real data.

A pipeline is a function ``Bars -> DataFrame`` with ``event_time`` / ``available_at``.

* **Recomputation** — features computed on the history known at ``T`` (M1 bars closed
  by ``T``, re-aggregated, so the last M15 / H1 bar is still forming) must equal the
  full-history features for every row with ``available_at <= T``.
* **Future perturbation** — replacing every price and spread after ``T`` with a
  different path must not change any row with ``available_at <= T``.
* **Availability audit** — ``available_at >= event_time`` on every row, and
  higher-timeframe context never closes after the row's ``available_at``.

Each check returns the columns that changed (and how many rows), so a deliberately
leaky feature is *named*, not just detected.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta

import numpy as np
import polars as pl

from candle_intel.features.compute import Bars

Pipeline = Callable[[Bars], pl.DataFrame]
KEY = "event_time"
REL_TOL = 1e-9


def diff_columns(a: pl.DataFrame, b: pl.DataFrame) -> Counter[str]:
    """Rows present in only one frame count under ``__rows__``; otherwise per column,
    the number of rows whose values differ (nulls equal nulls; floats to REL_TOL)."""
    out: Counter[str] = Counter()
    j = a.join(b, on=KEY, how="full", suffix="__b", coalesce=True)
    extra = j.filter(pl.col("available_at").is_null() | pl.col("available_at__b").is_null()).height
    if extra:
        out["__rows__"] = extra
    j = j.filter(pl.col("available_at").is_not_null() & pl.col("available_at__b").is_not_null())
    for col in a.columns:
        if col == KEY:
            continue
        x, y = pl.col(col), pl.col(f"{col}__b")
        if a.schema[col].is_float():
            tol = REL_TOL * pl.max_horizontal(pl.lit(1.0), x.abs(), y.abs())
            same = (x.is_null() & y.is_null()) | ((x - y).abs() <= tol) | (x.is_nan() & y.is_nan())
        else:
            same = x.eq_missing(y)
        n = j.select((~same.fill_null(False)).sum()).item()
        if n:
            out[col] = int(n)
    return out


def known_at(features: pl.DataFrame, t: datetime) -> pl.DataFrame:
    return features.filter(pl.col("available_at") <= t)


def recomputation_check(pipeline: Pipeline, bars: Bars, cutoffs: Iterable[datetime]) -> dict[str, int]:
    full = pipeline(bars)
    total: Counter[str] = Counter()
    for t in cutoffs:
        total += diff_columns(known_at(full, t), known_at(pipeline(bars.truncated(t)), t))
    return dict(total)


def perturb_after(m1: pl.DataFrame, t: datetime, seed: int = 7) -> pl.DataFrame:
    """A different, still valid, future: bars after ``t`` get new OHLC (a re-shuffled
    return path at 3× the size), new volume and new spreads. The past is untouched."""
    rng = np.random.default_rng(seed)
    past = m1.filter(pl.col("ts_utc") < t)
    fut = m1.filter(pl.col("ts_utc") >= t)
    if fut.is_empty():
        return m1
    n = fut.height
    anchor = float(past["close"][-1]) if past.height else float(fut["open"][0])
    steps = rng.permutation(np.diff(np.log(m1["close"].to_numpy()), prepend=np.log(anchor)))[:n] * 3.0
    close = anchor * np.exp(np.cumsum(steps))
    opn = np.concatenate([[anchor], close[:-1]])
    wiggle = np.abs(rng.normal(0, 0.0004, n)) * close
    fut = fut.with_columns(
        open=pl.Series(opn),
        close=pl.Series(close),
        high=pl.Series(np.maximum(opn, close) + wiggle),
        low=pl.Series(np.minimum(opn, close) - wiggle),
        tick_volume=pl.Series(rng.integers(1, 5000, n)).cast(fut.schema["tick_volume"]),
        spread_points=pl.Series(rng.integers(1, 400, n)).cast(fut.schema["spread_points"]),
    )
    return pl.concat([past, fut.select(past.columns)])


def perturbation_check(pipeline: Pipeline, bars: Bars, cutoffs: Iterable[datetime]) -> dict[str, int]:
    full = pipeline(bars)
    total: Counter[str] = Counter()
    for i, t in enumerate(cutoffs):
        # M1 bars opening at or after t are "future" for rows available at t.
        other = Bars.from_m1(perturb_after(bars.m1, t, seed=i + 1))
        total += diff_columns(known_at(full, t), known_at(pipeline(other), t))
    return dict(total)


def availability_audit(features: pl.DataFrame, bar: timedelta = timedelta(minutes=5)) -> dict[str, int]:
    """Row-level violations of the available_at contract (all counts must be 0)."""
    at = pl.col("available_at")
    checks = {
        "available_before_event": at < pl.col(KEY),
        "available_not_bar_close": at != pl.col(KEY) + bar,
        "m15_closes_after_available": pl.col("m15_close_utc") > at,
        "h1_closes_after_available": pl.col("h1_close_utc") > at,
    }
    return {k: int(features.select(v.fill_null(False).sum()).item()) for k, v in checks.items()}
