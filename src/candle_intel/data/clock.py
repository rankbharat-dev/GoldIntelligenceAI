"""Broker-server clock → UTC, inferred from the data itself.

Spot gold's daily maintenance break starts at 17:00 America/New_York, year-round
(so its UTC time moves with US daylight saving). For every weekday we find the
break in the broker's M1 bars, compare its start with 17:00 New York expressed in
UTC, and read off the broker's offset for that day. Per-week modal offsets are
then applied to every bar.

Nothing is assumed about the broker's timezone or DST rules; they are measured.
Weeks where no clean break is visible (holidays, thin data) inherit the offset of
the nearest measured week and are flagged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl

NEW_YORK = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")

MIN_BREAK_MINUTES = 30  # a gap shorter than this is not the daily break
MAX_BREAK_MINUTES = 150  # longer than this is a holiday / outage, not the daily break
MIN_DAYS_PER_WEEK = 3  # fewer measured days → week inherits from neighbours
MIN_AGREEMENT = 0.6  # share of a week's days that must agree on its offset


@dataclass(frozen=True)
class ClockModel:
    weekly: pl.DataFrame  # iso_year, iso_week, offset_hours, source, n_days, agreement
    days_measured: int
    days_consistent: float  # share of measured days agreeing with their week's offset
    distinct_offsets: list[float]

    def summary(self) -> dict:
        counts = self.weekly.group_by("offset_hours").len().sort("offset_hours")
        return {
            "method": "daily break anchored at 17:00 America/New_York",
            "days_measured": self.days_measured,
            "days_consistent_with_week": round(self.days_consistent, 4),
            "distinct_offsets_hours": self.distinct_offsets,
            "weeks_by_offset": dict(
                zip(counts["offset_hours"].to_list(), counts["len"].to_list(), strict=True)
            ),
            "weeks_inferred_from_neighbours": int((self.weekly["source"] == "neighbour").sum()),
        }


def _ny_break_start_utc(d: date) -> datetime:
    """17:00 New York on date d, as naive UTC."""
    return datetime(d.year, d.month, d.day, 17, tzinfo=NEW_YORK).astimezone(UTC_TZ).replace(tzinfo=None)


def daily_breaks(m1: pl.DataFrame) -> pl.DataFrame:
    """Per server-date, the longest intraday gap between consecutive M1 bars if it looks
    like the daily break. Columns: day, break_start_server, gap_minutes."""
    gaps = (
        m1.select("ts_server")
        .sort("ts_server")
        .with_columns(nxt=pl.col("ts_server").shift(-1))
        .with_columns(gap_minutes=(pl.col("nxt") - pl.col("ts_server")).dt.total_minutes())
        .filter(pl.col("gap_minutes").is_between(MIN_BREAK_MINUTES, MAX_BREAK_MINUTES))
        # The break starts one minute after the last bar before it.
        .with_columns(break_start_server=pl.col("ts_server") + pl.duration(minutes=1))
        .with_columns(day=pl.col("break_start_server").dt.date())
        .filter(pl.col("break_start_server").dt.weekday() <= 5)  # Mon..Fri
    )
    return (
        gaps.sort("gap_minutes", descending=True)
        .unique("day", keep="first")
        .select("day", "break_start_server", "gap_minutes")
        .sort("day")
    )


def infer_clock(m1: pl.DataFrame) -> ClockModel:
    breaks = daily_breaks(m1)
    if breaks.is_empty():
        raise ValueError("No daily break found in M1 data; cannot infer broker clock.")

    # The break is keyed by its *server* date, which is not always the New York date:
    # on the common "New York + 7 h" broker clock the break starts at 00:00 server
    # time, the next calendar day. The raw difference is therefore wrapped into
    # [-12 h, +12 h), which covers every MT5 broker clock in practice (UTC-5 .. UTC+3).
    expected = [_ny_break_start_utc(d) for d in breaks["day"].to_list()]
    diff_min = (pl.col("break_start_server") - pl.col("expected_utc")).dt.total_minutes()
    wrapped = ((diff_min + 720) % 1440) - 720
    raw_offset = (wrapped / 30).round() / 2
    per_day = breaks.with_columns(expected_utc=pl.Series(expected, dtype=pl.Datetime("us"))).with_columns(
        offset_hours=pl.when(raw_offset == 0).then(0.0).otherwise(raw_offset),  # no "-0.0"
        iso_year=pl.col("day").dt.iso_year(),
        iso_week=pl.col("day").dt.week(),
    )

    weekly = (
        per_day.group_by("iso_year", "iso_week")
        .agg(
            offset_hours=pl.col("offset_hours").mode().first(),
            n_days=pl.len(),
            agreement=(pl.col("offset_hours") == pl.col("offset_hours").mode().first()).mean(),
        )
        .with_columns(source=pl.lit("measured"))
        # A week needs enough, consistent evidence to count as measured.
        .filter((pl.col("n_days") >= MIN_DAYS_PER_WEEK) & (pl.col("agreement") >= MIN_AGREEMENT))
    )
    if weekly.is_empty():
        raise ValueError("No week has a consistent daily break; cannot infer broker clock.")

    # Every ISO week that has bars gets an offset; unmeasured weeks borrow the nearest.
    bar_weeks = (
        m1.select(iso_year=pl.col("ts_server").dt.iso_year(), iso_week=pl.col("ts_server").dt.week())
        .unique()
        .with_columns(key=pl.col("iso_year") * 100 + pl.col("iso_week"))
        .sort("key")
    )
    weekly = weekly.with_columns(key=pl.col("iso_year") * 100 + pl.col("iso_week")).sort("key")
    missing = bar_weeks.join(weekly.select("key"), on="key", how="anti")
    if missing.height:
        filled = missing.join_asof(
            weekly.select("key", "offset_hours"), on="key", strategy="nearest"
        ).with_columns(
            n_days=pl.lit(0, pl.UInt32), agreement=pl.lit(None, pl.Float64), source=pl.lit("neighbour")
        )
        weekly = pl.concat([weekly, filled.select(weekly.columns)], how="vertical_relaxed").sort("key")

    per_day = per_day.filter(pl.col("offset_hours").is_between(-12, 14))
    consistent = (
        per_day.join(
            weekly.select("iso_year", "iso_week", week_offset="offset_hours"), on=["iso_year", "iso_week"]
        )
        .select((pl.col("offset_hours") == pl.col("week_offset")).mean())
        .item()
    )

    return ClockModel(
        weekly=weekly.drop("key"),
        days_measured=per_day.height,
        days_consistent=float(consistent),
        distinct_offsets=sorted(weekly["offset_hours"].unique().to_list()),
    )


def to_utc(df: pl.DataFrame, clock: ClockModel, ts_col: str = "ts_server") -> pl.DataFrame:
    """Add ``ts_utc`` = ts_server − weekly offset. Keeps ts_server for traceability."""
    return (
        df.with_columns(iso_year=pl.col(ts_col).dt.iso_year(), iso_week=pl.col(ts_col).dt.week())
        .join(
            clock.weekly.select("iso_year", "iso_week", "offset_hours"),
            on=["iso_year", "iso_week"],
            how="left",
        )
        .with_columns(
            ts_utc=(pl.col(ts_col) - pl.duration(minutes=(pl.col("offset_hours") * 60).cast(pl.Int64)))
        )
        .drop("iso_year", "iso_week")
        .rename({"offset_hours": "server_offset_hours"})
    )


def ny_session_date_break(d: date) -> tuple[datetime, datetime]:
    """Expected daily-break window [17:00, 18:00) New York for date d, naive UTC."""
    start = _ny_break_start_utc(d)
    return start, start + timedelta(hours=1)
