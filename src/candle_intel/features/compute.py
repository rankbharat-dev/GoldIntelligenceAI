"""Feature engine — M5 candle, sequence, context and hygiene features (blueprint §7, §12).

One row per M5 bar:

    event_time    = bar open (UTC)
    available_at  = bar close = event_time + 5 min

Every feature is computed from data that exists at ``available_at``:

* rolling windows look backwards only (never ``center``, never ``shift(-n)``);
* normalisers (ATR, medians, quantiles, regime terciles) come from *earlier* bars;
* higher-timeframe context is joined as-of the last M15 / H1 bar whose **close** is
  at or before ``available_at`` — a forming H1 bar is never visible;
* no statistic is fitted on the whole history (the cost model's full-history
  ``abnormal_spread`` threshold is recomputed here from a trailing window).

``tests/leakage/test_feature_leakage.py`` proves this by recomputing the features on
truncated and perturbed histories; the build repeats that check on the real data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import polars as pl

from candle_intel.costs import volatility
from candle_intel.costs.spread import NORM_BARS, ROLLOVER_WINDOW_NY
from candle_intel.data.aggregate import aggregate
from candle_intel.features.registry import META_COLUMNS, feature_names
from candle_intel.structure import geometry as structure

FEATURE_VERSION = "features/3"  # /2 (Phase 7): market structure · /3: previous-day sweeps

BAR = timedelta(minutes=5)
ATR_BARS = volatility.ATR_BARS
SEQ_BARS = 20
VOLUME_BARS = 288  # ~1 trading day of M5
REGIME_LOOKBACK = timedelta(days=365)
REGIME_MIN_BARS = 288 * 10
ABNORMAL_Q = 0.99
ABNORMAL_LOOKBACK = 3600  # M1 minutes of the same UTC hour ≈ 60 trading days
ABNORMAL_MIN = 600
WEEKEND_GAP_MIN = 24 * 60
WEEK_EDGE_BARS = 3
WEEK_CLOSE_NY = "17:00"  # Friday close (measured: last bar opens 16:55 NY in 257 of 274 weeks)
TRADING_DAY_ROLL_H = 7  # NY 17:00 + 7 h = next calendar day → trading day
HTF_ATR_BARS = 14
HTF_SMA_BARS = 20
HTF_MINUTES = {"m15_": 15, "h1_": 60}
SESSIONS = {  # name: (IANA zone, local open, local close)
    "tokyo": ("Asia/Tokyo", "09:00", "18:00"),
    "london": ("Europe/London", "08:00", "17:00"),
    "new_york": ("America/New_York", "08:00", "17:00"),
}
NY = "America/New_York"

CONFIG = {
    "feature_version": FEATURE_VERSION,
    "atr_bars": ATR_BARS,
    "seq_bars": SEQ_BARS,
    "volume_bars": VOLUME_BARS,
    "vol_baseline_bars": volatility.BASELINE_BARS,
    "regime_lookback_days": REGIME_LOOKBACK.days,
    "regime_min_bars": REGIME_MIN_BARS,
    "abnormal_q": ABNORMAL_Q,
    "abnormal_lookback_minutes": ABNORMAL_LOOKBACK,
    "abnormal_min_samples": ABNORMAL_MIN,
    "spread_norm_bars": NORM_BARS,
    "rollover_window_ny": ROLLOVER_WINDOW_NY,
    "weekend_gap_min": WEEKEND_GAP_MIN,
    "week_edge_bars": WEEK_EDGE_BARS,
    "week_close_ny": WEEK_CLOSE_NY,
    "htf_atr_bars": HTF_ATR_BARS,
    "htf_sma_bars": HTF_SMA_BARS,
    "sessions": SESSIONS,
    "structure": structure.CONFIG,
}


@dataclass(frozen=True)
class Bars:
    """The inputs of one feature build. ``m1`` needs ts_utc, ts_server, OHLC,
    tick_volume and spread_points; the others are its aggregates."""

    m1: pl.DataFrame
    m5: pl.DataFrame
    m15: pl.DataFrame
    h1: pl.DataFrame

    @classmethod
    def from_m1(cls, m1: pl.DataFrame) -> Bars:
        """Aggregate exactly as the data engine does. On a truncated history the last
        M15 / H1 bar is *forming* — as it would be in real time."""
        m1 = m1.sort("ts_utc")
        return cls(m1, aggregate(m1, "M5"), aggregate(m1, "M15"), aggregate(m1, "H1"))

    def truncated(self, cutoff: datetime) -> Bars:
        """What was known at ``cutoff``: M1 bars that had closed by then, re-aggregated."""
        return Bars.from_m1(self.m1.filter(pl.col("ts_utc") + timedelta(minutes=1) <= cutoff))


# ---------------------------------------------------------------- helpers


def _sign(e: pl.Expr) -> pl.Expr:
    return e.sign().cast(pl.Int8)


def _positive(e: pl.Expr) -> pl.Expr:
    """``e`` where > 0, else null — a safe denominator."""
    return pl.when(e > 0).then(e)


def _run_length(flag: pl.Expr) -> pl.Expr:
    """Length of the current run of equal values of ``flag`` ending at each row."""
    run_id = (flag != flag.shift()).fill_null(True).cum_sum()
    return (pl.int_range(pl.len()).over(run_id) + 1).cast(pl.Int32)


def _local_minutes(zone: str) -> pl.Expr:
    t = pl.col("event_time").dt.replace_time_zone("UTC").dt.convert_time_zone(zone)
    return (t.dt.hour().cast(pl.Int32) * 60 + t.dt.minute().cast(pl.Int32)).alias(f"_mod_{zone}")


def _hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


# ---------------------------------------------------------------- spread (M1 → M5)


def spread_minutes(m1: pl.DataFrame) -> pl.DataFrame:
    """Per M1 bar: causal spread level, its ratio to the prevailing tier, and the
    abnormal flag against a *trailing* per-hour p99 (the current minute excluded)."""
    raw = pl.col("spread_points")
    level = pl.when(raw > 0).then(raw).forward_fill()
    tier = pl.col("spread_level").rolling_median(NORM_BARS, min_samples=NORM_BARS // 10)
    norm = pl.col("spread_level") / tier
    threshold = (
        pl.col("spread_rel")
        .shift(1)
        .rolling_quantile(
            ABNORMAL_Q, window_size=ABNORMAL_LOOKBACK, min_samples=ABNORMAL_MIN, interpolation="lower"
        )
        .over(pl.col("ts_utc").dt.hour())
    )
    return (
        m1.select("ts_utc", "spread_points")
        .sort("ts_utc")
        .with_columns(spread_level=level.cast(pl.Float64))
        .with_columns(spread_rel=norm.fill_null(1.0))
        .with_columns(abnormal=(pl.col("spread_rel") > threshold).fill_null(False))
    )


def spread_m5(m1: pl.DataFrame) -> pl.DataFrame:
    return (
        spread_minutes(m1)
        .group_by_dynamic("ts_utc", every="5m", closed="left", label="left")
        .agg(
            spread_pts=pl.col("spread_level").last(),
            spread_rel=pl.col("spread_rel").last(),
            hyg_abnormal_spread=pl.col("abnormal").any(),
        )
        .rename({"ts_utc": "event_time"})
    )


# ---------------------------------------------------------------- volatility regime


def regime_edges(vol: pl.DataFrame) -> pl.DataFrame:
    """Tercile edges of vol_ratio per calendar month, fitted on the 365 days *before*
    the month starts. Refreshing monthly keeps it cheap and strictly causal."""
    v = vol.select("event_time", "vol_ratio").drop_nulls()
    months = vol.select(month=pl.col("event_time").dt.truncate("1mo")).unique().sort("month")["month"]
    rows = []
    for m in months:
        r = v.filter((pl.col("event_time") < m) & (pl.col("event_time") >= m - REGIME_LOOKBACK))["vol_ratio"]
        if r.len() >= REGIME_MIN_BARS:
            rows.append({"month": m, "_lo": float(r.quantile(1 / 3)), "_hi": float(r.quantile(2 / 3))})
    schema = {"month": vol.schema["event_time"], "_lo": pl.Float64, "_hi": pl.Float64}
    return pl.DataFrame(rows, schema=schema)


# ---------------------------------------------------------------- higher timeframe


def htf_features(bars: pl.DataFrame, prefix: str, minutes: int, point: float) -> pl.DataFrame:
    """Per closed M15 / H1 bar; joined later on its close time."""
    o, h, low, c = (pl.col(x) for x in ("open", "high", "low", "close"))
    prev_c = c.shift()
    tr = pl.max_horizontal(h - low, (h - prev_c).abs(), (low - prev_c).abs())
    atr = _positive(tr.rolling_mean(HTF_ATR_BARS))
    sma = c.rolling_mean(HTF_SMA_BARS)
    d = _sign(c - o)
    p = prefix
    return (
        bars.sort("ts_utc")
        .with_columns(_atr=atr, _sma=sma, _dir=d)
        .select(
            (pl.col("ts_utc") + timedelta(minutes=minutes)).alias(f"{p}close_utc"),
            pl.col("_dir").alias(f"{p}dir"),
            ((c - o) / pl.col("_atr")).alias(f"{p}body_atr"),
            ((c - low) / _positive(h - low)).alias(f"{p}close_loc"),
            ((h - low) / pl.col("_atr")).alias(f"{p}range_atr"),
            ((c - c.shift(4)) / pl.col("_atr")).alias(f"{p}ret4_atr"),
            ((c - pl.col("_sma")) / pl.col("_atr")).alias(f"{p}trend_atr"),
            ((pl.col("_sma") - pl.col("_sma").shift(5)) / pl.col("_atr")).alias(f"{p}slope_atr"),
            (_run_length(pl.col("_dir")) * pl.col("_dir")).cast(pl.Int32).alias(f"{p}streak"),
            (pl.col("_atr") / point).alias(f"{p}atr_pts"),
            h.alias(f"_{p}high"),
            low.alias(f"_{p}low"),
        )
    )


# ---------------------------------------------------------------- main


def compute_features(bars: Bars, point: float, research_start: datetime | None = None) -> pl.DataFrame:
    """All features for every M5 bar. Output columns: META_COLUMNS + registry order."""
    o, h, low, c = (pl.col(x) for x in ("open", "high", "low", "close"))
    atr = pl.col("_atr")
    rng = h - low
    body = c - o

    m5 = bars.m5.sort("ts_utc").rename({"ts_utc": "event_time"})
    vol = volatility.m5_volatility(bars.m5, point).rename({"ts_utc": "event_time", "atr_points": "atr_pts"})
    edges = regime_edges(vol)

    df = (
        m5.join(vol, on="event_time", how="left")
        .join(spread_m5(bars.m1), on="event_time", how="left")
        .with_columns(
            available_at=pl.col("event_time") + BAR,
            _atr=_positive(pl.col("atr_pts") * point),
            _month=pl.col("event_time").dt.truncate("1mo"),
            gap_before_min=((pl.col("event_time") - pl.col("event_time").shift()).dt.total_minutes() - 5)
            .fill_null(0)
            .cast(pl.Int32),
        )
        .join(edges, left_on="_month", right_on="month", how="left")
    )

    # ------------------------------------------------------------ anatomy
    df = df.with_columns(
        dir=_sign(body),
        range_pts=rng / point,
        body_frac=body.abs() / _positive(rng),
        upper_wick_frac=(h - pl.max_horizontal(o, c)) / _positive(rng),
        lower_wick_frac=(pl.min_horizontal(o, c) - low) / _positive(rng),
        close_loc=(c - low) / _positive(rng),
        range_atr=rng / atr,
        body_atr=body / atr,
        upper_wick_atr=(h - pl.max_horizontal(o, c)) / atr,
        lower_wick_atr=(pl.min_horizontal(o, c) - low) / atr,
        gap_atr=(o - c.shift()) / atr,
        ret_atr=(c - c.shift()) / atr,
        volume_rel=pl.col("tick_volume")
        / _positive(pl.col("tick_volume").rolling_median(VOLUME_BARS, min_samples=VOLUME_BARS // 6)),
    )

    # ------------------------------------------------------------ sequence
    symbol = pl.col("dir").replace_strict({1: "U", -1: "D", 0: "-"}, return_dtype=pl.String)
    inside = (h <= h.shift()) & (low >= low.shift())
    week_start = (pl.col("gap_before_min") > WEEKEND_GAP_MIN).cast(pl.Int32).cum_sum()
    df = df.with_columns(
        dir_lag1=pl.col("dir").shift(1),
        dir_lag2=pl.col("dir").shift(2),
        dirs_3=pl.concat_str(symbol.shift(2), symbol.shift(1), symbol),
        body_atr_lag1=pl.col("body_atr").shift(1),
        close_loc_lag1=pl.col("close_loc").shift(1),
        range_atr_lag1=pl.col("range_atr").shift(1),
        streak=(_run_length(pl.col("dir")) * pl.col("dir")).cast(pl.Int32),
        up_count_5=(pl.col("dir") == 1).cast(pl.Int32).rolling_sum(5),
        up_count_10=(pl.col("dir") == 1).cast(pl.Int32).rolling_sum(10),
        **{f"ret{n}_atr": (c - c.shift(n)) / atr for n in (3, 5, 10, 20)},
        inside_bar=inside,
        outside_bar=(h > h.shift()) & (low < low.shift()),
        inside_streak=pl.when(inside).then(_run_length(inside)).otherwise(0).cast(pl.Int32),
        higher_high=h > h.shift(),
        lower_low=low < low.shift(),
        higher_low=low > low.shift(),
        lower_high=h < h.shift(),
        compression=rng.rolling_mean(5) / _positive(rng.rolling_mean(SEQ_BARS)),
        dist_high20_atr=(h.rolling_max(SEQ_BARS) - c) / atr,
        dist_low20_atr=(c - low.rolling_min(SEQ_BARS)) / atr,
        pos_in_range20=(c - low.rolling_min(SEQ_BARS))
        / _positive(h.rolling_max(SEQ_BARS) - low.rolling_min(SEQ_BARS)),
        bars_since_week_open=pl.int_range(pl.len()).over(week_start).cast(pl.Int32),
    )

    # ------------------------------------------------------------ volatility
    r = pl.col("vol_ratio")
    df = df.with_columns(
        vol_regime=pl.when(r.is_null() | pl.col("_lo").is_null())
        .then(None)
        .when(r < pl.col("_lo"))
        .then(pl.lit("low"))
        .when(r < pl.col("_hi"))
        .then(pl.lit("mid"))
        .otherwise(pl.lit("high")),
        rv20_bps=(c / c.shift()).log().rolling_std(SEQ_BARS) * 1e4,
    )

    # ------------------------------------------------------------ session / time
    df = df.with_columns(*[_local_minutes(z) for z, _, _ in SESSIONS.values()])
    in_s = {}
    since = {}
    for name, (zone, start, end) in SESSIONS.items():
        mod = pl.col(f"_mod_{zone}")
        in_s[name] = (mod >= _hm(start)) & (mod < _hm(end))
        since[name] = ((mod - _hm(start)) % 1440).cast(pl.Int32)
    mod_ny = pl.col(f"_mod_{NY}")
    ny_dow = pl.col("event_time").dt.replace_time_zone("UTC").dt.convert_time_zone(NY).dt.weekday()
    ro_lo, ro_hi = (_hm(x) for x in ROLLOVER_WINDOW_NY)
    close_ny = _hm(WEEK_CLOSE_NY)
    df = df.with_columns(
        session=pl.when(in_s["london"] & in_s["new_york"])
        .then(pl.lit("london_ny_overlap"))
        .when(in_s["london"])
        .then(pl.lit("london"))
        .when(in_s["new_york"])
        .then(pl.lit("new_york"))
        .when(in_s["tokyo"])
        .then(pl.lit("asian"))
        .otherwise(pl.lit("off")),
        in_tokyo=in_s["tokyo"],
        in_london=in_s["london"],
        in_new_york=in_s["new_york"],
        min_since_tokyo_open=since["tokyo"],
        min_since_london_open=since["london"],
        min_since_ny_open=since["new_york"],
        min_to_rollover=((close_ny - mod_ny) % 1440).cast(pl.Int32),
        hour_utc=pl.col("event_time").dt.hour().cast(pl.Int8),
        dow=pl.col("event_time").dt.weekday().cast(pl.Int8),
        hyg_rollover=(mod_ny >= ro_lo) & (mod_ny < ro_hi),
        hyg_week_last3=(ny_dow == 5) & (mod_ny >= close_ny - 5 * WEEK_EDGE_BARS) & (mod_ny < close_ny),
        trading_day=(
            pl.col("event_time").dt.replace_time_zone("UTC").dt.convert_time_zone(NY)
            + timedelta(hours=TRADING_DAY_ROLL_H)
        ).dt.date(),
    )

    # ------------------------------------------------------------ daily context
    daily = (
        df.group_by("trading_day")
        .agg(_pd_high=h.max(), _pd_low=low.min(), _pd_close=c.sort_by("event_time").last())
        .sort("trading_day")
        .with_columns(pl.col("_pd_high", "_pd_low", "_pd_close").shift())
    )
    day_high = h.cum_max().over("trading_day")
    day_low = low.cum_min().over("trading_day")
    df = df.join(daily, on="trading_day", how="left").with_columns(
        dist_day_open_atr=(c - o.first().over("trading_day")) / atr,
        day_range_atr=(day_high - day_low) / atr,
        pos_in_day_range=(c - day_low) / _positive(day_high - day_low),
        dist_prev_high_atr=(c - pl.col("_pd_high")) / atr,
        dist_prev_low_atr=(c - pl.col("_pd_low")) / atr,
        dist_prev_close_atr=(c - pl.col("_pd_close")) / atr,
    )
    # Previous-day sweeps: the wick takes out yesterday's high / low, the close comes back.
    # Same rule as candle_intel.patterns.prev_day; per-day counters use this and earlier bars.
    pdh, pdl = pl.col("_pd_high"), pl.col("_pd_low")
    pdh_sw = ((h > pdh) & (c < pdh)).fill_null(False)
    pdl_sw = ((low < pdl) & (c > pdl)).fill_null(False)
    df = df.with_columns(
        pdh_sweep=pdh_sw,
        pdl_sweep=pdl_sw,
        pdh_sweep_depth_atr=pl.when(pdh_sw).then((h - pdh) / atr),
        pdl_sweep_depth_atr=pl.when(pdl_sw).then((pdl - low) / atr),
        pdh_sweeps_today=pdh_sw.cast(pl.Int32).cum_sum().over("trading_day", order_by="event_time"),
        pdl_sweeps_today=pdl_sw.cast(pl.Int32).cum_sum().over("trading_day", order_by="event_time"),
        pdh_accepted_before=(c > pdh)
        .fill_null(False)
        .cast(pl.Int32)
        .cum_max()
        .shift(1)
        .over("trading_day", order_by="event_time")
        .fill_null(0)
        > 0,
        pdl_accepted_before=(c < pdl)
        .fill_null(False)
        .cast(pl.Int32)
        .cum_max()
        .shift(1)
        .over("trading_day", order_by="event_time")
        .fill_null(0)
        > 0,
    )

    # ------------------------------------------------------------ higher timeframes (as-of close)
    for p, minutes in HTF_MINUTES.items():
        src = bars.m15 if p == "m15_" else bars.h1
        g = p.rstrip("_")
        df = (
            df.sort("available_at")
            .join_asof(
                htf_features(src, p, minutes, point),
                left_on="available_at",
                right_on=f"{p}close_utc",
                strategy="backward",
            )
            .with_columns(
                ((c - pl.col(f"_{p}low")) / _positive(pl.col(f"_{p}high") - pl.col(f"_{p}low"))).alias(
                    f"pos_in_{g}_prev"
                )
            )
        )

    # ------------------------------------------------------------ market structure (Phase 7)
    df = df.sort("event_time")
    df = df.join(structure.structure_features(df), on="event_time", how="left")
    df = (
        df.sort("available_at")
        .join_asof(
            structure.h1_structure(bars.h1),
            left_on="available_at",
            right_on="_h1s_close_utc",
            strategy="backward",
        )
        .with_columns(
            h1_sw_hi_dist_atr=(c - pl.col("_h1_sw_hi")) / atr,
            h1_sw_lo_dist_atr=(c - pl.col("_h1_sw_lo")) / atr,
        )
    )

    # ------------------------------------------------------------ hygiene
    df = df.with_columns(
        hyg_week_first3=pl.col("bars_since_week_open") < WEEK_EDGE_BARS,
        hyg_weekend_gap=pl.col("gap_before_min") > WEEKEND_GAP_MIN,
        hyg_spans_weekend_gap=pl.col("bars_since_week_open") < SEQ_BARS - 1,
        hyg_incomplete=pl.col("m1_bars") < 5,
        hyg_abnormal_spread=pl.col("hyg_abnormal_spread").fill_null(False),
        in_research_window=pl.lit(True) if research_start is None else pl.col("event_time") >= research_start,
    ).with_columns(
        hyg_no_entry=pl.col("hyg_rollover")
        | pl.col("hyg_abnormal_spread")
        | pl.col("hyg_week_first3")
        | pl.col("hyg_week_last3"),
    )

    return df.sort("event_time").select(*META_COLUMNS, *feature_names())
