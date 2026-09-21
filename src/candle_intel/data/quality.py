"""M1 data-quality gate (blueprint §5).

Blocking checks fail the build. Everything else is measured and reported, because
"is this data good enough" is a research judgement that needs numbers, not a
silent filter. Input: M1 bars with ``ts_utc`` (see ``clock.to_utc``).
"""

from __future__ import annotations

from typing import Any

import polars as pl

NY = "America/New_York"

# Gap classification thresholds (minutes between consecutive bar opens, minus one).
DAILY_BREAK_NY_WINDOW = ("16:40", "17:20")  # where the daily break is allowed to start
DAILY_BREAK_MINUTES = (30, 150)
JUMP_RANGE_MULTIPLE = 15.0  # bar range vs rolling median range
JUMP_GAP_MULTIPLE = 10.0  # |open - prev close| vs rolling median range
ROLLING_BARS = 240


def _ny(col: str = "ts_utc") -> pl.Expr:
    return pl.col(col).dt.replace_time_zone("UTC").dt.convert_time_zone(NY)


def _hhmm(e: pl.Expr) -> pl.Expr:
    return e.dt.strftime("%H:%M")


def classify_gaps(m1: pl.DataFrame) -> pl.DataFrame:
    """One row per gap (>1 minute between consecutive bars) with a category."""
    g = (
        m1.select("ts_utc")
        .with_columns(nxt=pl.col("ts_utc").shift(-1))
        .with_columns(gap_minutes=(pl.col("nxt") - pl.col("ts_utc")).dt.total_minutes() - 1)
        .filter(pl.col("gap_minutes") > 0)
        .with_columns(
            start_ny=_ny("ts_utc") + pl.duration(minutes=1),
            end_ny=_ny("nxt"),
        )
        .with_columns(start_hhmm=_hhmm(pl.col("start_ny")), start_dow=pl.col("start_ny").dt.weekday())
    )
    lo, hi = DAILY_BREAK_NY_WINDOW
    is_weekend = (pl.col("start_dow") >= 5) & (pl.col("gap_minutes") >= 24 * 60)
    is_daily = pl.col("start_hhmm").is_between(pl.lit(lo), pl.lit(hi)) & pl.col("gap_minutes").is_between(
        *DAILY_BREAK_MINUTES
    )
    return g.with_columns(
        category=pl.when(is_weekend)
        .then(pl.lit("weekend"))
        .when(is_daily)
        .then(pl.lit("daily_break"))
        .when(pl.col("gap_minutes") >= DAILY_BREAK_MINUTES[1])
        .then(pl.lit("closure"))  # holiday / early close / outage
        .when(pl.col("gap_minutes") >= 30)
        .then(pl.lit("long_intraday"))
        .otherwise(pl.lit("short_intraday"))
    )


def research_window(m1: pl.DataFrame, min_share_of_median: float = 0.8) -> tuple[Any, Any, list[str]]:
    """Trim thin leading weeks (partial history at the start of the broker archive).

    A week is 'full' when it has at least 80% of the median weekly bar count. The
    window starts at the first full week; the final week is kept even if partial,
    since it is simply the present.
    """
    weekly = (
        m1.group_by(week=pl.col("ts_utc").dt.truncate("1w"))
        .agg(bars=pl.len(), first=pl.col("ts_utc").min(), last=pl.col("ts_utc").max())
        .sort("week")
    )
    threshold = weekly["bars"].median() * min_share_of_median
    full = weekly.filter(pl.col("bars") >= threshold)
    start = full["first"].min()
    excluded = weekly.filter(pl.col("week") < full["week"].min())["week"].dt.strftime("%Y-%m-%d").to_list()
    return start, m1["ts_utc"].max(), excluded


def run(m1: pl.DataFrame) -> dict[str, Any]:
    m1 = m1.sort("ts_utc")
    n = m1.height
    report: dict[str, Any] = {"bars": n}

    # ---------------------------------------------------------------- blocking
    dup = n - m1["ts_utc"].n_unique()
    non_monotonic = int((m1["ts_utc"].diff().dt.total_seconds() <= 0).sum())
    ohlc_bad = m1.filter(
        (pl.col("high") < pl.max_horizontal("open", "close"))
        | (pl.col("low") > pl.min_horizontal("open", "close"))
        | (pl.col("low") > pl.col("high"))
    ).height
    nonpositive = m1.filter(pl.min_horizontal("open", "high", "low", "close") <= 0).height
    blocking = {
        "duplicate_timestamps": dup,
        "non_monotonic": non_monotonic,
        "invalid_ohlc": ohlc_bad,
        "nonpositive_price": nonpositive,
    }
    report["blocking"] = blocking
    report["passed"] = all(v == 0 for v in blocking.values())

    # ---------------------------------------------------------------- gaps
    gaps = classify_gaps(m1)
    by_cat = gaps.group_by("category").agg(count=pl.len(), missing_minutes=pl.col("gap_minutes").sum())
    report["gaps"] = {
        r["category"]: {"count": r["count"], "missing_minutes": r["missing_minutes"]}
        for r in by_cat.sort("category").iter_rows(named=True)
    }
    daily = gaps.filter(pl.col("category") == "daily_break")
    report["daily_break_ny"] = {
        "typical_start": daily["start_hhmm"].mode().sort().first() if daily.height else None,
        "typical_minutes": int(daily["gap_minutes"].median()) if daily.height else None,
        "days_observed": daily.height,
    }
    closures = gaps.filter(pl.col("category").is_in(["closure", "long_intraday"])).sort(
        "gap_minutes", descending=True
    )
    report["largest_unexpected_gaps"] = [
        {"start_ny": str(r["start_ny"])[:16], "minutes": r["gap_minutes"], "category": r["category"]}
        for r in closures.head(15).iter_rows(named=True)
    ]
    short = gaps.filter(pl.col("category") == "short_intraday")
    report["short_intraday_missing_share"] = round(short["gap_minutes"].sum() / max(n, 1), 6)

    # ---------------------------------------------------------------- price anomalies
    feats = m1.with_columns(
        rng=pl.col("high") - pl.col("low"),
        jump=(pl.col("open") - pl.col("close").shift()).abs(),
    ).with_columns(med=pl.col("rng").rolling_median(ROLLING_BARS, min_samples=60).shift())
    spikes = feats.filter(
        (pl.col("med") > 0)
        & (
            (pl.col("rng") > JUMP_RANGE_MULTIPLE * pl.col("med"))
            | (pl.col("jump") > JUMP_GAP_MULTIPLE * pl.col("med"))
        )
    )
    report["price_anomalies"] = {
        "count": spikes.height,
        "rule": f"range > {JUMP_RANGE_MULTIPLE}x or open-gap > {JUMP_GAP_MULTIPLE}x rolling median range",
        "largest": [
            {
                "ts_utc": str(r["ts_utc"]),
                "range": round(r["rng"], 3),
                "open_gap": round(r["jump"] or 0, 3),
                "median_range": round(r["med"], 3),
            }
            for r in spikes.sort("rng", descending=True).head(10).iter_rows(named=True)
        ],
    }
    report["flat_bars_share"] = round(feats.filter(pl.col("rng") == 0).height / max(n, 1), 6)

    # ---------------------------------------------------------------- spread
    sp = m1["spread_points"]
    p99 = sp.quantile(0.99)
    report["spread_points"] = {
        "p50": sp.quantile(0.50),
        "p90": sp.quantile(0.90),
        "p99": p99,
        "max": sp.max(),
        "nonpositive": int((sp <= 0).sum()),
        "above_5x_p99": int((sp > 5 * p99).sum()),
    }

    # ---------------------------------------------------------------- coverage
    start, end, excluded = research_window(m1)
    report["coverage"] = {
        "first_ts_utc": str(m1["ts_utc"].min()),
        "last_ts_utc": str(m1["ts_utc"].max()),
        "research_window_utc": [str(start), str(end)],
        "thin_leading_weeks_excluded": excluded,
        "years": round((end - start).total_seconds() / (365.25 * 86400), 2),
    }
    return report
