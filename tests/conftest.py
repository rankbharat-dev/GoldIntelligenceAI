"""Shared fixtures: a synthetic XAUUSD-like M1 history with the real market calendar."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
import pytest

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def market_open(t_utc: datetime) -> bool:
    """Gold hours in New York time: Sunday 18:00 → Friday 17:00, daily break 17:00–18:00."""
    ny = t_utc.replace(tzinfo=UTC).astimezone(NY)
    wd, hm = ny.weekday(), ny.hour * 60 + ny.minute  # Monday = 0
    if wd == 5 or (wd == 4 and hm >= 17 * 60) or (wd == 6 and hm < 18 * 60):
        return False
    return not (17 * 60 <= hm < 18 * 60)


def synthetic_m1(start: datetime, end: datetime, seed: int = 11) -> pl.DataFrame:
    """Random-walk M1 bid bars on the gold calendar (DST-aware), with spread tiers,
    spread spikes, zero-spread quirks and a few missing minutes."""
    rng = np.random.default_rng(seed)
    times = []
    t = start
    while t < end:
        if market_open(t):
            times.append(t)
        t += timedelta(minutes=1)
    n = len(times)
    keep = rng.random(n) > 0.003  # a few missing minutes
    times = [x for x, k in zip(times, keep, strict=True) if k]
    n = len(times)
    vol = 0.00035 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))  # drifting volatility
    close = 2900.0 * np.exp(np.cumsum(rng.normal(0, 1, n) * vol))
    opn = np.concatenate([[2900.0], close[:-1]]) + rng.normal(0, 0.05, n)
    wick = np.abs(rng.normal(0, 1, (2, n))) * vol * close
    high = np.maximum(opn, close) + wick[0]
    low = np.minimum(opn, close) - wick[1]
    tier = np.where(np.arange(n) < n // 2, 60, 90)
    spread = tier + rng.integers(0, 6, n)
    spikes = rng.random(n) < 0.002
    spread[spikes] *= 6
    spread[rng.random(n) < 0.002] = 0  # the broker's ≤ 0 quirk
    return pl.DataFrame(
        {
            "ts_utc": times,
            "ts_server": times,
            "open": np.round(opn, 3),
            "high": np.round(high, 3),
            "low": np.round(low, 3),
            "close": np.round(close, 3),
            "tick_volume": rng.integers(20, 400, n),
            "spread_points": spread.astype(np.int32),
            "real_volume": np.zeros(n, dtype=np.int64),
        }
    ).with_columns(pl.col("ts_utc", "ts_server").cast(pl.Datetime("us")))


# Spans the US (Mar 9) and UK (Mar 30) DST switches and three month boundaries,
# long enough for every warm-up (regime terciles need 10 trading days first).
SYN_START = datetime(2025, 2, 2, 22, 0)
SYN_END = datetime(2025, 4, 12)


@pytest.fixture(scope="session")
def syn_m1() -> pl.DataFrame:
    return synthetic_m1(SYN_START, SYN_END)
