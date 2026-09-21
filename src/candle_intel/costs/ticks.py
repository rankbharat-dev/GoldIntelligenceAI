"""Tick archive → time-weighted spread histograms (blueprint §6, Layer 1).

A spread that lasts ten seconds costs a random entry ten times more often than one
that lasts one second, so every quote is weighted by how long it prevailed (until
the next tick, capped). Counting ticks instead would over-weight busy moments.

Output of this module is one small table, ``tick_hist``:

    ts_utc (minute) · spread_points · seconds · ticks

i.e. per UTC minute, how many seconds each spread value was on screen. Every
downstream statistic (per-minute measured spread, conditional cells, validation)
is an aggregation of it, so the 70 M-tick archive is read exactly once.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import polars as pl

from candle_intel.data.clock import apply_weekly_offsets

log = logging.getLogger(__name__)

# A quote is assumed to stay on screen at most this long. Longer silences are
# breaks, closures or feed gaps, not a spread anyone could trade at.
QUOTE_CAP_SECONDS = 60.0
MIN_QUOTE_SECONDS = 0.001  # ticks sharing a millisecond still count


def tick_files(raw_dir: Path) -> list[tuple[str, Path]]:
    """(day, path) for every tick chunk in a raw dataset, hash-verified against its manifest."""
    manifest = json.loads((raw_dir / "manifest.json").read_text(encoding="utf-8"))
    out = []
    for c in manifest.get("tick_chunks", []):
        path = raw_dir / "ticks" / c["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != c["sha256"]:
            raise RuntimeError(f"Tick chunk {c['file']} does not match its manifest hash")
        out.append((c["day"], path))
    if not out:
        raise FileNotFoundError(f"{raw_dir.name} has no tick archive. Run: ci-ingest raw --ticks")
    return out


def histogram(
    ticks: pl.DataFrame, weekly: pl.DataFrame, point: float, allow_zero: bool = False
) -> tuple[pl.DataFrame, dict[str, int]]:
    """One day of raw ticks (ts_server, bid, ask) → per-minute spread histogram.

    Returns the histogram and counts of rejected ticks (non-positive spread or
    price, or a timestamp outside the clock model). ``allow_zero`` keeps zero-spread
    quotes: a Raw Spread account really quotes 0.0 at times; on a standard account a
    zero spread is a data fault."""
    t = apply_weekly_offsets(ticks.sort("ts_server"), weekly).with_columns(
        spread_points=((pl.col("ask") - pl.col("bid")) / point).round().cast(pl.Int32)
    )
    bad_spread = pl.col("spread_points") < 0 if allow_zero else pl.col("spread_points") <= 0
    bad_price = (pl.col("bid") <= 0) | (pl.col("ask") <= 0) | bad_spread
    rejected = {
        "nonpositive": int(t.select(bad_price.sum()).item()),
        "no_clock": int(t["ts_utc"].null_count()),
    }
    t = t.filter(~bad_price & pl.col("ts_utc").is_not_null())
    hist = (
        t.with_columns(
            seconds=(pl.col("ts_utc").shift(-1) - pl.col("ts_utc"))
            .dt.total_microseconds()
            .truediv(1e6)
            .fill_null(QUOTE_CAP_SECONDS)
            .clip(MIN_QUOTE_SECONDS, QUOTE_CAP_SECONDS),
            ts_utc=pl.col("ts_utc").dt.truncate("1m").cast(pl.Datetime("us")),
        )
        .group_by("ts_utc", "spread_points")
        .agg(seconds=pl.col("seconds").sum(), ticks=pl.len().cast(pl.Int32))
    )
    return hist, rejected


def build_histogram(
    raw_dir: Path, weekly: pl.DataFrame, point: float, allow_zero: bool = False
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Histogram over the whole tick archive, one day file at a time (bounded memory)."""
    parts, days, rejected, n_ticks = [], [], {"nonpositive": 0, "no_clock": 0}, 0
    for day, path in tick_files(raw_dir):
        ticks = pl.read_parquet(path, columns=["ts_server", "bid", "ask"])
        n_ticks += ticks.height
        if ticks.is_empty():
            continue
        h, rej = histogram(ticks, weekly, point, allow_zero)
        parts.append(h)
        days.append(day)
        for k, v in rej.items():
            rejected[k] += v
    hist = pl.concat(parts).sort("ts_utc", "spread_points")
    info = {
        "tick_days": len(days),
        "first_day": days[0],
        "last_day": days[-1],
        "ticks": n_ticks,
        "ticks_rejected": rejected,
        "quote_cap_seconds": QUOTE_CAP_SECONDS,
    }
    log.info("ticks: %d over %d days → %d histogram rows", n_ticks, len(days), hist.height)
    return hist, info


def minutes(hist: pl.DataFrame) -> pl.DataFrame:
    """Per-minute measured spread: time-weighted mean, min, max, ticks, seconds quoted."""
    return (
        hist.group_by("ts_utc")
        .agg(
            spread_twmean=(pl.col("spread_points") * pl.col("seconds")).sum() / pl.col("seconds").sum(),
            spread_min=pl.col("spread_points").min(),
            spread_max=pl.col("spread_points").max(),
            ticks=pl.col("ticks").sum(),
            seconds=pl.col("seconds").sum(),
        )
        .sort("ts_utc")
    )
