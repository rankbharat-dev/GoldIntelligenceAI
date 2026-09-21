"""Chart-Based Creator: a marked bar → a measurable rule draft (MASTER_PROMPT §6).

The owner marks the bar where they would have entered. This module reads that bar's
feature row (as known at its close) and turns what is *distinctive* about it into
candidate conditions with explicit tolerances:

* structure events that fired (sweep, breakout, retest, trendline break …) → ``== true``
* direction / sequence codes / swing-trend states → ``== value``
* fractions (close location, wick shares) → a ±0.15 band, clipped to 0..1
* ATR distances → a band of ±max(0.25, 30 %) around the value
* touch counts → ``>= value``

Nothing is selected silently: every suggestion carries why it was proposed, and the
owner ticks what stays. The result is an ordinary spec — tested like any other.
"""

from __future__ import annotations

from typing import Any

from candle_intel.features.registry import BY_NAME
from candle_intel.strategy.spec import NOT_CONDITIONABLE

EVENT_FLAGS = (
    "sweep_low",
    "sweep_high",
    "sw_break_up",
    "sw_break_down",
    "retest_up",
    "retest_down",
    "failed_break_up",
    "failed_break_down",
    "tl_up_break",
    "tl_dn_break",
    "inside_bar",
    "outside_bar",
)
CODES = ("dir", "dirs_3", "sw_trend", "h1_sw_trend", "m15_dir", "h1_dir")
FRACTIONS = ("close_loc", "upper_wick_frac", "lower_wick_frac", "body_frac", "rng_pos", "pos_in_range20")
DISTANCES = (
    "range_atr",
    "body_atr",
    "ret5_atr",
    "sweep_depth_atr",
    "sr_below_low_dist_atr",
    "sr_above_high_dist_atr",
    "tl_up_dist_atr",
    "tl_dn_dist_atr",
    "h1_trend_atr",
    "dist_prev_high_atr",
    "dist_prev_low_atr",
)
COUNTS = ("sr_below_touches", "sr_above_touches", "tl_up_touches", "tl_dn_touches")
# Suggested by default (the owner can untick): the event itself and the candle's shape.
DEFAULT_ON = {*EVENT_FLAGS, "dir", "close_loc"}


def _band(
    v: float, lo_cap: float | None = None, hi_cap: float | None = None, frac: bool = False
) -> list[float]:
    w = 0.15 if frac else max(0.25, abs(v) * 0.3)
    lo, hi = v - w, v + w
    if lo_cap is not None:
        lo = max(lo, lo_cap)
    if hi_cap is not None:
        hi = min(hi, hi_cap)
    return [round(lo, 3), round(hi, 3)]


def suggest(row: dict[str, Any], side: str) -> dict[str, Any]:
    """Suggestions from one feature row (``values`` of /api/features/.../bar)."""
    out: list[dict[str, Any]] = []

    def add(feature: str, op: str, value: Any, why: str) -> None:
        if feature in BY_NAME and feature not in NOT_CONDITIONABLE:
            out.append(
                {
                    "condition": {"feature": feature, "op": op, "value": value},
                    "why": why,
                    "group": BY_NAME[feature].group,
                    "selected": feature in DEFAULT_ON,
                }
            )

    for f in EVENT_FLAGS:
        if row.get(f) is True:
            add(f, "==", True, BY_NAME[f].description)
    for f in CODES:
        v = row.get(f)
        if v is not None:
            add(f, "==", v, f"This bar: {f} = {v}")
    for f in FRACTIONS:
        v = row.get(f)
        if isinstance(v, int | float):
            add(f, "between", _band(float(v), 0.0, 1.0, frac=True), f"This bar: {f} = {v:.2f} (±0.15)")
    for f in DISTANCES:
        v = row.get(f)
        if isinstance(v, int | float):
            add(f, "between", _band(float(v)), f"This bar: {f} = {v:.2f} ATR (±max(0.25, 30 %))")
    for f in COUNTS:
        v = row.get(f)
        if isinstance(v, int | float) and v >= 2:
            add(f, ">=", int(v), f"Level / line touched {int(v)} times")
    session = row.get("session")
    return {
        "side": side,
        "suggestions": out,
        "filters": {"sessions": [session]} if session else {},
        "note": "Tick the conditions that describe the setup; everything else is ignored. "
        "Tight bands on many features describe one bar, not a pattern — keep 2–4.",
    }
