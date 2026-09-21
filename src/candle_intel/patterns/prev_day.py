"""Previous-day high / low liquidity sweeps (M5) — an explicit, code-defined pattern.

The idea traders describe as "price ran the stops above yesterday's high and came
back" becomes a rule a computer checks the same way every time:

    trading day   gold's day runs 17:00 → 17:00 New York (the daily rollover), DST-aware
    PDH / PDL     highest high / lowest low of the previous trading day in the data
    PDH sweep     an M5 bar whose high goes above PDH by at least ``min_depth_atr`` ATR
                  (and at most ``max_depth_atr``), and whose close is back below PDH
                  → short idea (the breakout failed)
    PDL sweep     mirror image below PDL → long idea
    options       ``first_only``: only the day's first sweep of that level (a later one
                  is not "first" even if the first failed a depth or session filter);
                  ``no_prior_acceptance``: skip it if an earlier M5 bar of the same day
                  already *closed* beyond the level (price accepted it, not a sweep);
                  ``sessions``: only bars in these sessions (london, new_york, …)

Everything is known at the bar's close: PDH / PDL come from a finished day and the
per-day flags use earlier bars only (tests/unit/test_patterns.py checks that a future
bar cannot change a past event). ATR is the feature store's ATR(14) of M5
(``atr_pts``), so the depth is in the same units as every study and backtest.

Honest limits: bid prices from one broker's feed; the previous day can be short
(holidays, data gaps); M5 bars only (no tick sequence inside the bar).
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import polars as pl

from candle_intel.backtest.market import Market

RULE_VERSION = 1
DAY_ROLL_HOURS = 7  # 17:00 New York + 7 h = next calendar day 00:00 → trading-day date

Level = Literal["pdh", "pdl"]


def m5_bars(mk: Market) -> pl.DataFrame:
    """M5 OHLC built from the market's M1 bid bars (bar open = ``event_time``, UTC)."""
    t = mk.t - mk.t % 300
    df = pl.DataFrame({"t": t, "o": mk.o, "h": mk.h, "l": mk.l, "c": mk.c})
    return (
        df.group_by("t", maintain_order=True)
        .agg(pl.col("o").first(), pl.col("h").max(), pl.col("l").min(), pl.col("c").last())
        .sort("t")
        .with_columns(event_time=pl.from_epoch("t", "s").cast(pl.Datetime("us")))
        .drop("t")
    )


def with_levels(m5: pl.DataFrame) -> pl.DataFrame:
    """Add the trading day and the previous trading day's high / low to every M5 bar."""
    ny = pl.col("event_time").dt.replace_time_zone("UTC").dt.convert_time_zone("America/New_York")
    m5 = m5.with_columns(day=(ny + pl.duration(hours=DAY_ROLL_HOURS)).dt.date())
    daily = (
        m5.group_by("day")
        .agg(day_high=pl.col("h").max(), day_low=pl.col("l").min(), day_bars=pl.len())
        .sort("day")
        .with_columns(
            pdh=pl.col("day_high").shift(1),
            pdl=pl.col("day_low").shift(1),
            prev_day_bars=pl.col("day_bars").shift(1),
        )
        .select("day", "pdh", "pdl", "prev_day_bars")
    )
    return m5.join(daily, on="day", how="left")


def detect(
    mk: Market,
    level: Level,
    min_depth_atr: float = 0.0,
    max_depth_atr: float | None = 1.5,
    first_only: bool = True,
    no_prior_acceptance: bool = True,
    sessions: list[str] | None = None,
    min_prev_day_bars: int = 120,
) -> pl.DataFrame:
    """Sweep events of one level, one row per event: ``decision_time`` (bar close),
    ``event_time``, ``side`` (−1 PDH / +1 PDL), ``atr_pts``, ``level``, ``depth_atr``,
    ``day``, ``session``. ``min_prev_day_bars`` drops days after a short previous day
    (≥ 120 M5 bars = 10 h of trading)."""
    feats = mk.features(["atr_pts", "session", "vol_regime"])
    bars = with_levels(m5_bars(mk)).join(
        feats.select("event_time", "available_at", "atr_pts", "session"), on="event_time", how="inner"
    )
    atr_px = pl.col("atr_pts") * mk.point
    if level == "pdh":
        lvl, side = pl.col("pdh"), -1
        beyond = pl.col("h") - lvl
        back = pl.col("c") < lvl
        closed_beyond = pl.col("c") > lvl
    else:
        lvl, side = pl.col("pdl"), 1
        beyond = lvl - pl.col("l")
        back = pl.col("c") > lvl
        closed_beyond = pl.col("c") < lvl
    depth = beyond / atr_px
    raw = ((beyond > 0) & back).fill_null(False)  # any sweep of the level (counts for first_only)
    cond = raw & (depth >= min_depth_atr) & (pl.col("atr_pts") > 0)
    if max_depth_atr is not None:
        cond = cond & (depth <= max_depth_atr)
    cond = cond & lvl.is_not_null() & (pl.col("prev_day_bars") >= min_prev_day_bars)
    bars = bars.sort("event_time").with_columns(
        _sweep=cond.fill_null(False),
        _nth=raw.cast(pl.Int32).cum_sum().over("day"),
        _accepted_before=closed_beyond.fill_null(False)
        .cast(pl.Int32)
        .cum_max()
        .shift(1)
        .over("day")
        .fill_null(0)
        > 0,
        depth_atr=depth,
        level=lvl,
    )
    if no_prior_acceptance:
        bars = bars.with_columns(_sweep=pl.col("_sweep") & ~pl.col("_accepted_before"))
    if sessions:
        bars = bars.with_columns(_sweep=pl.col("_sweep") & pl.col("session").is_in(sessions))
    if first_only:
        bars = bars.with_columns(_sweep=pl.col("_sweep") & (pl.col("_nth") == 1))
    return (
        bars.filter(pl.col("_sweep"))
        .select(
            pl.col("available_at").alias("decision_time"),
            "event_time",
            pl.lit(side, dtype=pl.Int8).alias("side"),
            "atr_pts",
            pl.col("level").round(3),
            pl.col("depth_atr").round(3),
            "day",
            "session",
        )
        .sort("decision_time")
    )


def describe(level: Level) -> dict[str, Any]:
    word, side, op = ("high", "short", "above") if level == "pdh" else ("low", "long", "below")
    back = "below" if level == "pdh" else "above"
    return {
        "name": f"Previous-day {word} sweep",
        "side": side,
        "rule": (
            f"M5 bar's {'high' if level == 'pdh' else 'low'} goes {op} the previous trading day's {word} "
            f"(17:00→17:00 New York) by min_depth_atr…max_depth_atr × ATR(14), and the bar closes back "
            f"{back} it. Decided at the bar close; entry at the next M1 open."
        ),
        "rule_version": RULE_VERSION,
    }


def sanity(ev: pl.DataFrame) -> dict[str, Any]:
    """Quick counts for a detector run (per session and per year)."""
    if ev.is_empty():
        return {"events": 0}
    return {
        "events": ev.height,
        "days": ev["day"].n_unique(),
        "median_depth_atr": float(np.round(ev["depth_atr"].median(), 3)),
        "by_session": dict(ev.group_by("session").len().sort("session").iter_rows()),
        "by_year": {str(k): v for k, v in ev.group_by(pl.col("day").dt.year()).len().sort("day").iter_rows()},
    }
