"""Feature catalogue — every column of the feature dataset, what it means, and when it
becomes known (blueprint §7.1, §12).

``timing`` says which clock a value depends on. All of them are <= the row's
``available_at`` (the close of the M5 bar), which the leakage suite checks:

    bar_close  uses the bar's own OHLC / volume / spread → known when the bar closes
    bar_open   uses only bars before this one (e.g. ATR of the previous 14 bars)
    calendar   a function of the bar's timestamp (session, weekday) → known in advance
    htf_close  from the last *closed* M15 / H1 bar (its close <= available_at)

Structure features (group ``structure``, Phase 7) use only swings confirmed by the
row's close: a swing needs K bars after it, so it is known K bars late (see
``candle_intel.structure.geometry``).

Units: ``atr`` = multiples of ATR(14) of the previous M5 bars (scale-free across the
2021 → 2026 price range), ``pts`` = broker points (0.001 USD), ``frac`` = 0..1 share.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

Timing = Literal["bar_close", "bar_open", "calendar", "htf_close"]


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    group: str
    unit: str
    timing: Timing
    description: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


# Row identity / lineage columns — not features, but part of every row.
META_COLUMNS = (
    "event_time",  # bar open, UTC
    "available_at",  # bar close, UTC — the earliest moment the row is known
    "ts_server",
    "trading_day",  # New York 17:00 roll
    "m15_close_utc",  # close time of the M15 bar the m15_* features come from
    "h1_close_utc",
    "in_research_window",
)

GROUPS = {
    "anatomy": "Candle anatomy",
    "sequence": "Sequence (last N candles)",
    "volatility": "Volatility",
    "session": "Session & time (IANA tz, DST-aware)",
    "daily": "Daily context (NY 17:00 trading day)",
    "m15": "M15 context (last closed M15 bar)",
    "h1": "H1 context (last closed H1 bar)",
    "structure": "Market structure (swings, S/R, trendlines, sweeps)",
    "spread": "Spread",
    "hygiene": "Hygiene flags (blueprint §5.3)",
}


def _f(name: str, group: str, unit: str, timing: Timing, description: str) -> FeatureSpec:
    return FeatureSpec(name, group, unit, timing, description)


def _htf(p: str, label: str) -> list[FeatureSpec]:
    g = p.rstrip("_")
    return [
        _f(
            f"{p}dir",
            g,
            "sign",
            "htf_close",
            f"Direction of the last closed {label} bar (+1 up, −1 down, 0 flat)",
        ),
        _f(f"{p}body_atr", g, "atr", "htf_close", f"Signed body of that {label} bar in {label} ATR(14)"),
        _f(
            f"{p}close_loc",
            g,
            "frac",
            "htf_close",
            f"Where that {label} bar closed inside its range (0 low … 1 high)",
        ),
        _f(f"{p}range_atr", g, "atr", "htf_close", f"Range of that {label} bar in {label} ATR(14)"),
        _f(
            f"{p}ret4_atr",
            g,
            "atr",
            "htf_close",
            f"Close change over the last 4 closed {label} bars, in {label} ATR",
        ),
        _f(
            f"{p}trend_atr",
            g,
            "atr",
            "htf_close",
            f"{label} close minus its SMA(20), in {label} ATR (trend side)",
        ),
        _f(
            f"{p}slope_atr",
            g,
            "atr",
            "htf_close",
            f"Change of the {label} SMA(20) over 5 bars, in {label} ATR",
        ),
        _f(f"{p}streak", g, "bars", "htf_close", f"Consecutive {label} bars in the same direction (signed)"),
        _f(f"{p}atr_pts", g, "pts", "htf_close", f"{label} ATR(14) in points"),
        _f(
            f"pos_in_{g}_prev",
            g,
            "frac",
            "htf_close",
            f"M5 close inside the last closed {label} bar's range (<0 below, >1 above)",
        ),
    ]


FEATURES: tuple[FeatureSpec, ...] = (
    # ------------------------------------------------------------ anatomy
    _f("dir", "anatomy", "sign", "bar_close", "Candle direction: +1 close > open, −1 close < open, 0 equal"),
    _f("range_pts", "anatomy", "pts", "bar_close", "High − low in points"),
    _f("body_frac", "anatomy", "frac", "bar_close", "|close − open| ÷ range (null for a zero-range bar)"),
    _f("upper_wick_frac", "anatomy", "frac", "bar_close", "Upper wick ÷ range"),
    _f("lower_wick_frac", "anatomy", "frac", "bar_close", "Lower wick ÷ range"),
    _f(
        "close_loc",
        "anatomy",
        "frac",
        "bar_close",
        "Close position inside the range: 0 = at the low, 1 = at the high",
    ),
    _f(
        "range_atr",
        "anatomy",
        "atr",
        "bar_close",
        "Range ÷ ATR(14) of the previous bars (>1 = bigger than usual)",
    ),
    _f("body_atr", "anatomy", "atr", "bar_close", "Signed body (close − open) ÷ ATR"),
    _f("upper_wick_atr", "anatomy", "atr", "bar_close", "Upper wick ÷ ATR"),
    _f("lower_wick_atr", "anatomy", "atr", "bar_close", "Lower wick ÷ ATR"),
    _f(
        "gap_atr",
        "anatomy",
        "atr",
        "bar_close",
        "Open − previous close, ÷ ATR (weekend gaps included; see hygiene)",
    ),
    _f("ret_atr", "anatomy", "atr", "bar_close", "Close − previous close, ÷ ATR"),
    _f("tick_volume", "anatomy", "ticks", "bar_close", "Broker tick volume of the bar"),
    _f("volume_rel", "anatomy", "x", "bar_close", "Tick volume ÷ median of the last 288 bars (~1 day)"),
    # ------------------------------------------------------------ sequence
    _f("dir_lag1", "sequence", "sign", "bar_close", "Direction of the previous bar"),
    _f("dir_lag2", "sequence", "sign", "bar_close", "Direction of the bar two back"),
    _f(
        "dirs_3",
        "sequence",
        "code",
        "bar_close",
        "Last 3 directions, oldest first: U up, D down, - flat (e.g. DDU)",
    ),
    _f("body_atr_lag1", "sequence", "atr", "bar_close", "Previous bar's signed body ÷ ATR"),
    _f("close_loc_lag1", "sequence", "frac", "bar_close", "Previous bar's close position in its range"),
    _f("range_atr_lag1", "sequence", "atr", "bar_close", "Previous bar's range ÷ ATR"),
    _f(
        "streak",
        "sequence",
        "bars",
        "bar_close",
        "Consecutive bars in the same direction, signed (+3 = three up bars)",
    ),
    _f("up_count_5", "sequence", "bars", "bar_close", "Up bars among the last 5"),
    _f("up_count_10", "sequence", "bars", "bar_close", "Up bars among the last 10"),
    _f("ret3_atr", "sequence", "atr", "bar_close", "Close change over 3 bars ÷ ATR"),
    _f("ret5_atr", "sequence", "atr", "bar_close", "Close change over 5 bars ÷ ATR"),
    _f("ret10_atr", "sequence", "atr", "bar_close", "Close change over 10 bars ÷ ATR"),
    _f("ret20_atr", "sequence", "atr", "bar_close", "Close change over 20 bars ÷ ATR"),
    _f("inside_bar", "sequence", "bool", "bar_close", "High and low inside the previous bar's range"),
    _f("outside_bar", "sequence", "bool", "bar_close", "High above and low below the previous bar"),
    _f("inside_streak", "sequence", "bars", "bar_close", "Consecutive inside bars ending here"),
    _f("higher_high", "sequence", "bool", "bar_close", "High above the previous high"),
    _f("lower_low", "sequence", "bool", "bar_close", "Low below the previous low"),
    _f("higher_low", "sequence", "bool", "bar_close", "Low above the previous low"),
    _f("lower_high", "sequence", "bool", "bar_close", "High below the previous high"),
    _f("compression", "sequence", "x", "bar_close", "Mean range of last 5 bars ÷ last 20 (<1 = contracting)"),
    _f(
        "dist_high20_atr",
        "sequence",
        "atr",
        "bar_close",
        "Highest high of the last 20 bars minus close, ÷ ATR",
    ),
    _f("dist_low20_atr", "sequence", "atr", "bar_close", "Close minus lowest low of the last 20 bars, ÷ ATR"),
    _f("pos_in_range20", "sequence", "frac", "bar_close", "Close inside the 20-bar high/low range"),
    _f(
        "bars_since_week_open",
        "sequence",
        "bars",
        "bar_close",
        "M5 bars since the first bar after the weekend",
    ),
    # ------------------------------------------------------------ volatility
    _f("atr_pts", "volatility", "pts", "bar_open", "ATR(14) of the previous M5 bars, points"),
    _f("vol_ratio", "volatility", "x", "bar_open", "ATR ÷ its trailing 20-day median (1 = normal)"),
    _f(
        "vol_regime",
        "volatility",
        "label",
        "bar_open",
        "low / mid / high: vol_ratio vs terciles of the 365 days before this month (causal)",
    ),
    _f("rv20_bps", "volatility", "bps", "bar_close", "Std-dev of the last 20 M5 log returns, basis points"),
    # ------------------------------------------------------------ session / time
    _f("session", "session", "label", "calendar", "asian / london / new_york / london_ny_overlap / off"),
    _f("in_tokyo", "session", "bool", "calendar", "Inside Tokyo 09:00–18:00 Asia/Tokyo"),
    _f("in_london", "session", "bool", "calendar", "Inside London 08:00–17:00 Europe/London"),
    _f("in_new_york", "session", "bool", "calendar", "Inside New York 08:00–17:00 America/New_York"),
    _f("min_since_tokyo_open", "session", "min", "calendar", "Minutes since the latest 09:00 Tokyo"),
    _f("min_since_london_open", "session", "min", "calendar", "Minutes since the latest 08:00 London"),
    _f("min_since_ny_open", "session", "min", "calendar", "Minutes since the latest 08:00 New York"),
    _f(
        "min_to_rollover", "session", "min", "calendar", "Minutes until the next 17:00 New York (daily break)"
    ),
    _f("hour_utc", "session", "h", "calendar", "UTC hour of the bar open"),
    _f("dow", "session", "day", "calendar", "ISO weekday of the bar open, UTC (1 = Monday)"),
    # ------------------------------------------------------------ daily
    _f("dist_day_open_atr", "daily", "atr", "bar_close", "Close minus the trading day's open, ÷ ATR"),
    _f("day_range_atr", "daily", "atr", "bar_close", "Trading-day high − low so far, ÷ ATR"),
    _f("pos_in_day_range", "daily", "frac", "bar_close", "Close inside today's range so far"),
    _f(
        "dist_prev_high_atr",
        "daily",
        "atr",
        "bar_close",
        "Close minus the previous trading day's high, ÷ ATR",
    ),
    _f("dist_prev_low_atr", "daily", "atr", "bar_close", "Close minus the previous trading day's low, ÷ ATR"),
    _f(
        "dist_prev_close_atr",
        "daily",
        "atr",
        "bar_close",
        "Close minus the previous trading day's close, ÷ ATR",
    ),
    # previous-day high / low liquidity sweeps (features/3, CEO Work Lab Phase 5)
    _f("pdh_sweep", "daily", "bool", "bar_close", "High above the previous day's high, close back below it"),
    _f("pdl_sweep", "daily", "bool", "bar_close", "Low below the previous day's low, close back above it"),
    _f("pdh_sweep_depth_atr", "daily", "atr", "bar_close", "How far a PDH sweep went above the level, ÷ ATR"),
    _f("pdl_sweep_depth_atr", "daily", "atr", "bar_close", "How far a PDL sweep went below the level, ÷ ATR"),
    _f(
        "pdh_sweeps_today",
        "daily",
        "count",
        "bar_close",
        "PDH sweeps so far this trading day, this bar included (1 = the first one)",
    ),
    _f(
        "pdl_sweeps_today",
        "daily",
        "count",
        "bar_close",
        "PDL sweeps so far this trading day, this bar included (1 = the first one)",
    ),
    _f(
        "pdh_accepted_before",
        "daily",
        "bool",
        "bar_close",
        "An earlier bar of this trading day already closed above the previous day's high",
    ),
    _f(
        "pdl_accepted_before",
        "daily",
        "bool",
        "bar_close",
        "An earlier bar of this trading day already closed below the previous day's low",
    ),
    # ------------------------------------------------------------ higher timeframes
    *_htf("m15_", "M15"),
    *_htf("h1_", "H1"),
    # ------------------------------------------------------------ market structure (Phase 7)
    _f("sw_hi_dist_atr", "structure", "atr", "bar_close", "Close minus the last confirmed swing high, ÷ ATR"),
    _f("sw_lo_dist_atr", "structure", "atr", "bar_close", "Close minus the last confirmed swing low, ÷ ATR"),
    _f("sw_hi_age", "structure", "bars", "bar_close", "Bars since that swing high's bar"),
    _f("sw_lo_age", "structure", "bars", "bar_close", "Bars since that swing low's bar"),
    _f(
        "sw_trend",
        "structure",
        "sign",
        "bar_close",
        "Swing structure: +1 higher high & higher low, −1 lower high & lower low, 0 mixed",
    ),
    _f("rng_width_atr", "structure", "atr", "bar_close", "Last swing high − last swing low, ÷ ATR"),
    _f("rng_pos", "structure", "frac", "bar_close", "Close between the last swing low (0) and high (1)"),
    _f("sw_break_up", "structure", "bool", "bar_close", "First close above the last swing high (breakout)"),
    _f("sw_break_down", "structure", "bool", "bar_close", "First close below the last swing low (breakdown)"),
    _f(
        "bars_since_break_up",
        "structure",
        "bars",
        "bar_close",
        "Bars since the last breakout (≤ 48, else empty)",
    ),
    _f(
        "bars_since_break_down",
        "structure",
        "bars",
        "bar_close",
        "Bars since the last breakdown (≤ 48, else empty)",
    ),
    _f(
        "retest_up",
        "structure",
        "bool",
        "bar_close",
        "Within 24 bars of a breakout: low back to the broken level (±0.25 ATR), close above it",
    ),
    _f(
        "retest_down",
        "structure",
        "bool",
        "bar_close",
        "Within 24 bars of a breakdown: high back to the broken level, close below it",
    ),
    _f(
        "failed_break_up",
        "structure",
        "bool",
        "bar_close",
        "First close back below the broken level within 12 bars of a breakout",
    ),
    _f(
        "failed_break_down",
        "structure",
        "bool",
        "bar_close",
        "First close back above the broken level within 12 bars of a breakdown",
    ),
    _f(
        "sweep_high",
        "structure",
        "bool",
        "bar_close",
        "Liquidity sweep: high above the last swing high, close back below it",
    ),
    _f(
        "sweep_low",
        "structure",
        "bool",
        "bar_close",
        "Liquidity sweep: low below the last swing low, close back above it",
    ),
    _f("sweep_depth_atr", "structure", "atr", "bar_close", "How far the sweep went beyond the swing, ÷ ATR"),
    _f(
        "sr_above_dist_atr",
        "structure",
        "atr",
        "bar_close",
        "Nearest S/R level above the close (≥ 2 swing touches, last ~4 days), distance ÷ ATR",
    ),
    _f("sr_above_touches", "structure", "count", "bar_close", "Swing touches of that level above"),
    _f(
        "sr_below_dist_atr",
        "structure",
        "atr",
        "bar_close",
        "Nearest S/R level below the close, distance ÷ ATR",
    ),
    _f("sr_below_touches", "structure", "count", "bar_close", "Swing touches of that level below"),
    _f(
        "sr_above_high_dist_atr",
        "structure",
        "atr",
        "bar_close",
        "Level above minus the bar's high, ÷ ATR (< 0: the wick pierced resistance)",
    ),
    _f(
        "sr_below_low_dist_atr",
        "structure",
        "atr",
        "bar_close",
        "The bar's low minus the level below, ÷ ATR (< 0: the wick pierced support)",
    ),
    _f(
        "tl_up_dist_atr",
        "structure",
        "atr",
        "bar_close",
        "Close minus the rising trendline through the last two higher swing lows, ÷ ATR",
    ),
    _f("tl_up_slope_atr", "structure", "atr", "bar_close", "Slope of that line in ATR per hour"),
    _f("tl_up_touches", "structure", "count", "bar_close", "Swing lows on that line (anchors included)"),
    _f(
        "tl_up_break",
        "structure",
        "bool",
        "bar_close",
        "Close below the rising trendline (the line ends here)",
    ),
    _f(
        "tl_dn_dist_atr",
        "structure",
        "atr",
        "bar_close",
        "Close minus the falling trendline through the last two lower swing highs, ÷ ATR",
    ),
    _f("tl_dn_slope_atr", "structure", "atr", "bar_close", "Slope of that line in ATR per hour"),
    _f("tl_dn_touches", "structure", "count", "bar_close", "Swing highs on that line (anchors included)"),
    _f(
        "tl_dn_break",
        "structure",
        "bool",
        "bar_close",
        "Close above the falling trendline (the line ends here)",
    ),
    _f(
        "ch_up_pos",
        "structure",
        "frac",
        "bar_close",
        "Close in the rising channel (line + parallel through the top swing high): 0 floor, 1 roof",
    ),
    _f("ch_dn_pos", "structure", "frac", "bar_close", "Close inside the falling channel: 0 floor, 1 roof"),
    _f(
        "ch_width_atr",
        "structure",
        "atr",
        "bar_close",
        "Channel width ÷ ATR (rising channel if any, else falling)",
    ),
    _f(
        "h1_sw_trend",
        "structure",
        "sign",
        "htf_close",
        "H1 swing structure (+1 HH & HL, −1 LH & LL, 0 mixed) from closed H1 bars",
    ),
    _f(
        "h1_sw_hi_dist_atr",
        "structure",
        "atr",
        "htf_close",
        "M5 close minus the last confirmed H1 swing high, ÷ M5 ATR",
    ),
    _f(
        "h1_sw_lo_dist_atr",
        "structure",
        "atr",
        "htf_close",
        "M5 close minus the last confirmed H1 swing low, ÷ M5 ATR",
    ),
    # ------------------------------------------------------------ spread
    _f(
        "spread_pts",
        "spread",
        "pts",
        "bar_close",
        "Spread level at the bar's last minute (minute minimum; ≤0 carried forward)",
    ),
    _f(
        "spread_rel",
        "spread",
        "x",
        "bar_close",
        "That spread ÷ its trailing ~5-day median (the broker's current tier)",
    ),
    # ------------------------------------------------------------ hygiene
    _f(
        "hyg_rollover",
        "hygiene",
        "bool",
        "calendar",
        "Bar inside the rollover window 16:45–18:30 New York → no entry",
    ),
    _f(
        "hyg_abnormal_spread",
        "hygiene",
        "bool",
        "bar_close",
        "A minute of the bar had spread above the trailing p99 of its UTC hour (past data only) → no entry",
    ),
    _f(
        "hyg_week_first3",
        "hygiene",
        "bool",
        "bar_close",
        "One of the first 3 M5 bars of the trading week → no entry",
    ),
    _f(
        "hyg_week_last3",
        "hygiene",
        "bool",
        "calendar",
        "One of the last 3 M5 bars before the Friday 17:00 NY close → no entry",
    ),
    _f("hyg_weekend_gap", "hygiene", "bool", "bar_close", "First bar after a weekend (gap > 24 h)"),
    _f(
        "hyg_spans_weekend_gap",
        "hygiene",
        "bool",
        "bar_close",
        "The 20-bar lookback crosses a weekend gap (report separately)",
    ),
    _f("hyg_incomplete", "hygiene", "bool", "bar_close", "Bar built from fewer than 5 M1 bars"),
    _f(
        "gap_before_min",
        "hygiene",
        "min",
        "bar_close",
        "Minutes missing between the previous bar and this one",
    ),
    _f(
        "hyg_no_entry",
        "hygiene",
        "bool",
        "bar_close",
        "Any §5.3 exclusion: rollover, abnormal spread, first/last 3 bars of week",
    ),
)

BY_NAME = {f.name: f for f in FEATURES}
assert len(BY_NAME) == len(FEATURES), "duplicate feature name"


def feature_names() -> list[str]:
    return [f.name for f in FEATURES]
