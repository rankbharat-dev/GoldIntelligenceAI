"""Clock inference, aggregation and quality gate on synthetic gold-like M1 data.

The synthetic broker runs its server clock at New York + 7 h (UTC+2 in US winter,
UTC+3 in US summer) — deliberately different from the Exness demo (UTC+0), so the
test proves the method measures the offset rather than assuming it.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
import pytest

from candle_intel.data import aggregate, clock, quality

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _synthetic_m1(start_ny: datetime, weeks: int, server_minus_ny_hours: int = 7) -> pl.DataFrame:
    """Gold hours: Sun 18:00 → Fri 17:00 New York, daily break 17:00–18:00 New York."""
    rows = []
    t = start_ny
    end = start_ny + timedelta(weeks=weeks)
    price = 2000.0
    rng = np.random.default_rng(7)
    while t < end:
        wd, hm = t.weekday(), (t.hour, t.minute)
        closed = (
            wd == 5
            or (wd == 4 and hm >= (17, 0))
            or (wd == 6 and hm < (18, 0))
            or (hm >= (17, 0) and hm < (18, 0))
        )
        if not closed:
            utc = t.astimezone(UTC).replace(tzinfo=None)
            server = t.replace(tzinfo=None) + timedelta(hours=server_minus_ny_hours)
            o = price
            c = o + rng.normal(0, 0.3)
            h = max(o, c) + abs(rng.normal(0, 0.1))
            lo = min(o, c) - abs(rng.normal(0, 0.1))
            rows.append((server, utc, o, h, lo, c, 10, 20, 0))
            price = c
        t += timedelta(minutes=1)
    df = pl.DataFrame(
        rows,
        schema=[
            "ts_server",
            "true_utc",
            "open",
            "high",
            "low",
            "close",
            "tick_volume",
            "spread_points",
            "real_volume",
        ],
        orient="row",
    )
    return df.with_columns(
        pl.col("ts_server").cast(pl.Datetime("us")), pl.col("true_utc").cast(pl.Datetime("us"))
    )


@pytest.fixture(scope="module")
def m1_across_dst() -> pl.DataFrame:
    # Spans the US spring-forward on 2025-03-09.
    return _synthetic_m1(datetime(2025, 2, 23, 18, 0, tzinfo=NY), weeks=5)


def test_clock_offsets_are_measured_across_dst(m1_across_dst: pl.DataFrame) -> None:
    model = clock.infer_clock(m1_across_dst)
    assert model.distinct_offsets == [2.0, 3.0]
    assert model.days_consistent == 1.0


def test_to_utc_recovers_true_utc_for_every_bar(m1_across_dst: pl.DataFrame) -> None:
    converted = clock.to_utc(m1_across_dst, clock.infer_clock(m1_across_dst))
    assert converted.filter(pl.col("ts_utc") != pl.col("true_utc")).height == 0


def test_aggregation_matches_independent_resample(m1_across_dst: pl.DataFrame) -> None:
    m1 = clock.to_utc(m1_across_dst, clock.infer_clock(m1_across_dst))
    m5 = aggregate.aggregate(m1, "M5")
    bucket = (
        m1.with_columns(b=pl.col("ts_utc").dt.truncate("5m"))
        .group_by("b")
        .agg(pl.col("high").max(), pl.col("low").min(), pl.len().alias("n"))
    )
    j = m5.join(bucket, left_on="ts_utc", right_on="b")
    assert j.height == m5.height
    assert (j["high"] == j["high_right"]).all() and (j["low"] == j["low_right"]).all()
    assert (j["m1_bars"] == j["n"]).all()


def test_verification_detects_a_corrupted_bar(m1_across_dst: pl.DataFrame) -> None:
    m1 = clock.to_utc(m1_across_dst, clock.infer_clock(m1_across_dst))
    m5 = aggregate.aggregate(m1, "M5")
    native = m5.select("ts_server", "open", "high", "low", "close")
    assert aggregate.verify_against_reference(m5, native)["ohlc_match_rate"] == 1.0
    broken = native.with_columns(
        pl.when(pl.int_range(pl.len()) == 10).then(pl.col("high") + 1).otherwise(pl.col("high")).alias("high")
    )
    assert aggregate.verify_against_reference(m5, broken)["ohlc_exact_match"] == m5.height - 1


def test_quality_gate_classifies_breaks_and_passes_clean_data(m1_across_dst: pl.DataFrame) -> None:
    m1 = clock.to_utc(m1_across_dst, clock.infer_clock(m1_across_dst))
    report = quality.run(m1)
    assert report["passed"]
    assert report["gaps"]["weekend"]["count"] >= 4
    assert report["gaps"]["daily_break"]["count"] >= 15
    assert report["daily_break_ny"]["typical_start"] == "17:00"


def test_quality_gate_blocks_invalid_ohlc_and_duplicates(m1_across_dst: pl.DataFrame) -> None:
    m1 = clock.to_utc(m1_across_dst, clock.infer_clock(m1_across_dst))
    bad = pl.concat([m1, m1.head(3)]).with_columns(
        pl.when(pl.int_range(pl.len()) == 5).then(pl.col("low") - 50).otherwise(pl.col("high")).alias("high")
    )
    report = quality.run(bad)
    assert not report["passed"]
    assert report["blocking"]["duplicate_timestamps"] == 3
    assert report["blocking"]["invalid_ohlc"] >= 1
