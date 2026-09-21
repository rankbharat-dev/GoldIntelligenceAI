"""Spread model: measured → modeled → stressed (blueprint §6).

Two facts measured on this broker's data (Exness-MT5Trial7) shape the model:

1. **The spread is set in administrative tiers that change from week to week**
   (37 pts in Jan-2026, 137–155 in Mar, 80–90 in Jul–Sep), while its time-of-day
   profile is comparatively flat. A table of absolute spreads by (hour, weekday,
   volatility) fitted on 2026 ticks cannot describe 2021–2025.
2. **The M1 bar's ``spread_points`` is the minimum spread quoted during that
   minute** (identical to the tick minimum in 100 % of 252,833 overlapping
   minutes). Barring the few bars that report ≤ 0, it is a trustworthy per-bar
   *level* for the whole 5-year history.

So the modeled spread for a bar is

    spread_q(bar) = level(bar) × ratio_q(hour_utc, weekday, vol_bucket)

where ``ratio`` = quoted spread ÷ that minute's minimum, a time-weighted
distribution fitted on the tick archive. The literal blueprint model (absolute
spread per cell) is still built and scored in validation as the baseline.

Scenarios per bar (points):

    optimistic  = modeled p25             | measured: min(observed, p25)
    base        = modeled p50             | measured: observed
    pessimistic = max(p90, current p90)   | measured: max(observed, p90, current p90)

"current p90" is the absolute p90 of the same (hour, weekday, vol) cell over
the last CURRENT_DAYS of ticks: the promotion gate charges at least what the
broker has been charging recently, even for a 2022 bar that was cheaper at the time.
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from candle_intel.costs.volatility import bucket

QUANTILES = {"p25": 0.25, "p50": 0.50, "p90": 0.90, "p99": 0.99}
QCOLS = list(QUANTILES)
KEYS = ("hour_utc", "dow", "vol_bucket")
# Finest → coarsest. A bar uses the finest cell holding enough quoted time.
LEVELS: tuple[tuple[str, ...], ...] = (KEYS, ("hour_utc", "dow"), ("hour_utc",), ())
MIN_CELL_MINUTES = 60.0
ALL = {"hour_utc": -1, "dow": -1, "vol_bucket": "all"}
CURRENT_DAYS = 60
ROLLOVER_WINDOW_NY = ("16:45", "18:30")  # daily break 17:00–18:00 NY plus the widened edges
NORM_BARS = 7200  # ~5 trading days of M1: the prevailing spread tier
NY = "America/New_York"


# ---------------------------------------------------------------- bar keys


def calendar_keys() -> list[pl.Expr]:
    ny = pl.col("ts_utc").dt.replace_time_zone("UTC").dt.convert_time_zone(NY).dt.strftime("%H:%M")
    lo, hi = ROLLOVER_WINDOW_NY
    return [
        pl.col("ts_utc").dt.hour().cast(pl.Int8).alias("hour_utc"),
        pl.col("ts_utc").dt.weekday().cast(pl.Int8).alias("dow"),  # 1 = Monday … 7 = Sunday
        (ny >= lo).and_(ny < hi).alias("in_rollover_window"),
    ]


def bar_keys(m1: pl.DataFrame, vol: pl.DataFrame, edges: tuple[float, float]) -> pl.DataFrame:
    """M1 bars → cell keys, M5 ATR and the per-bar spread level.

    ``spread_level`` is the bar's own minimum spread; bars reporting ≤ 0 carry the
    last valid level forward (``level_imputed``)."""
    snap = pl.col("spread_points")
    return (
        m1.select("ts_utc", "ts_server", "spread_points")
        .sort("ts_utc")
        .with_columns(m5=pl.col("ts_utc").dt.truncate("5m"))
        .join(vol.rename({"ts_utc": "m5"}), on="m5", how="left")
        .with_columns(bucket(edges), *calendar_keys())
        .with_columns(
            level_imputed=snap <= 0,
            spread_level=pl.when(snap > 0).then(snap).otherwise(None).forward_fill().backward_fill(),
        )
        .drop("m5", "spread_points")
    )


# ---------------------------------------------------------------- cells


def keyed_histogram(hist: pl.DataFrame, keys: pl.DataFrame, ratio_basis: str = "own_min") -> pl.DataFrame:
    """Attach cell keys to the tick histogram and express each quote as a ratio.

    ``own_min``: to its minute's minimum spread (the account the bars come from).
    ``bar_level``: to the *bar dataset's* spread level of that minute — used when the
    ticks come from another account (Exness Raw Spread) than the bars (the demo), so
    that ``level × ratio`` prices the other account over the whole bar history."""
    if ratio_basis == "bar_level":
        return (
            hist.join(keys.select("ts_utc", *KEYS, "spread_level"), on="ts_utc", how="inner")
            .with_columns(ratio=(pl.col("spread_points") / pl.col("spread_level")).round(4))
            .drop("spread_level")
        )
    return (
        hist.join(keys.select("ts_utc", *KEYS), on="ts_utc", how="left")
        .with_columns(
            hour_utc=pl.coalesce("hour_utc", pl.col("ts_utc").dt.hour().cast(pl.Int8)),
            dow=pl.coalesce("dow", pl.col("ts_utc").dt.weekday().cast(pl.Int8)),
            vol_bucket=pl.col("vol_bucket").fill_null("mid"),
        )
        .with_columns(ratio=(pl.col("spread_points") / pl.col("spread_points").min().over("ts_utc")).round(3))
    )


def weighted_quantiles(
    df: pl.DataFrame, by: Sequence[str], value: str, weight: str = "seconds"
) -> pl.DataFrame:
    """Exact weighted quantiles of ``value`` per group (value = first point where the
    cumulative weight share reaches q). Adds ``minutes`` (weight / 60) and ``mean``."""
    by = list(by) or ["_g"]
    d = df.with_columns(_g=pl.lit(0)) if by == ["_g"] else df
    d = (
        d.group_by(*by, value)
        .agg(w=pl.col(weight).sum())
        .sort(*by, value)
        .with_columns(cf=pl.col("w").cum_sum().over(by) / pl.col("w").sum().over(by))
    )
    out = d.group_by(by).agg(
        minutes=pl.col("w").sum() / 60,
        mean=(pl.col(value) * pl.col("w")).sum() / pl.col("w").sum(),
        **{
            k: pl.col(value).filter(pl.col("cf") >= q - 1e-12).first().cast(pl.Float64)
            for k, q in QUANTILES.items()
        },
    )
    return out.drop("_g") if by == ["_g"] else out


def cells(khist: pl.DataFrame, basis: str, window: str) -> pl.DataFrame:
    """Quantile table at every fallback level. basis: "abs" (points) or "ratio"."""
    value = "spread_points" if basis == "abs" else "ratio"
    parts = []
    for i, level in enumerate(LEVELS):
        c = weighted_quantiles(khist, level, value)
        for k in KEYS:
            if k not in level:
                c = c.with_columns(pl.lit(ALL[k]).alias(k))
        parts.append(
            c.with_columns(
                pl.col("hour_utc").cast(pl.Int8),
                pl.col("dow").cast(pl.Int8),
                pl.col("vol_bucket").cast(pl.String),
                level=pl.lit(i, pl.Int8),
                basis=pl.lit(basis),
                window=pl.lit(window),
            ).select("basis", "window", "level", *KEYS, "minutes", "mean", *QCOLS)
        )
    return pl.concat(parts).sort("basis", "window", "level", *KEYS)


def lookup(keys: pl.DataFrame, table: pl.DataFrame, prefix: str = "") -> pl.DataFrame:
    """Per row of ``keys``, the quantiles of the finest cell with ≥ MIN_CELL_MINUTES
    of quoted time. ``table`` is one basis/window of ``cells``. Adds ``<prefix>cell_level``."""
    out = keys
    for i, level in enumerate(LEVELS):
        c = table.filter((pl.col("level") == i) & (pl.col("minutes") >= MIN_CELL_MINUTES)).select(
            *level, *[pl.col(q).alias(f"_{q}_{i}") for q in QCOLS]
        )
        if level:
            out = out.join(c, on=list(level), how="left")
        elif c.height:
            out = out.join(c, how="cross")
        else:
            out = out.with_columns(*[pl.lit(None, pl.Float64).alias(n) for n in c.columns])
    found = [pl.col(f"_p50_{i}").is_not_null() for i in range(len(LEVELS))]

    def pick(name: str) -> pl.Expr:
        e = pl.lit(None, pl.Float64)
        for i in reversed(range(len(LEVELS))):
            e = pl.when(found[i]).then(pl.col(f"_{name}_{i}")).otherwise(e)
        return e

    lvl = pl.lit(None, pl.Int8)
    for i in reversed(range(len(LEVELS))):
        lvl = pl.when(found[i]).then(pl.lit(i, pl.Int8)).otherwise(lvl)
    return out.with_columns(
        *[pick(q).alias(f"{prefix}{q}") for q in QCOLS], lvl.alias(f"{prefix}cell_level")
    ).drop([f"_{q}_{i}" for q in QCOLS for i in range(len(LEVELS))])


def current_window(khist: pl.DataFrame, days: int | None = None) -> pl.DataFrame:
    days = CURRENT_DAYS if days is None else days
    return khist.filter(pl.col("ts_utc") >= khist["ts_utc"].max() - pl.duration(days=days))


# ---------------------------------------------------------------- pricing bars


def price_bars(
    keys: pl.DataFrame, measured: pl.DataFrame, ratio_cells: pl.DataFrame, current_abs_cells: pl.DataFrame
) -> pl.DataFrame:
    """Every M1 bar gets its spread quantiles, source and three scenario spreads (points)."""
    b = lookup(keys, ratio_cells, prefix="r_")
    b = lookup(b, current_abs_cells, prefix="cur_")
    b = b.join(
        measured.select("ts_utc", spread_obs="spread_twmean", spread_obs_max="spread_max"),
        on="ts_utc",
        how="left",
    )
    obs, lvl = pl.col("spread_obs"), pl.col("spread_level")
    b = b.with_columns(
        *[(lvl * pl.col(f"r_{q}")).alias(f"spread_{q}") for q in QCOLS],
        spread_current_p90=pl.col("cur_p90"),
        spread_source=pl.when(obs.is_not_null()).then(pl.lit("measured")).otherwise(pl.lit("modeled")),
    )
    p25, p50, p90, cur = (pl.col(c) for c in ("spread_p25", "spread_p50", "spread_p90", "spread_current_p90"))
    measured_row = obs.is_not_null()
    return b.with_columns(
        spread_optimistic=pl.when(measured_row).then(pl.min_horizontal(obs, p25)).otherwise(p25),
        spread_base=pl.when(measured_row).then(obs).otherwise(p50),
        spread_pessimistic=pl.max_horizontal(obs, p90, cur),  # max ignores the null obs of modeled bars
        cell_level=pl.col("r_cell_level"),
    ).drop([f"r_{q}" for q in QCOLS], [f"cur_{q}" for q in QCOLS], "r_cell_level", "cur_cell_level")


def flag_abnormal(bars: pl.DataFrame) -> pl.DataFrame:
    """Blueprint §5.3: a bar whose spread exceeds the p99 of its hour-of-day
    distribution is ``abnormal_spread`` (excluded from entries later).

    Because the tiers move over the years, the spread is first normalised by the
    prevailing tier (trailing median level over ~5 trading days); the p99 is then
    taken per UTC hour over the whole history."""
    norm = (
        pl.col("spread_level")
        / pl.col("spread_level")
        .rolling_median(NORM_BARS, min_samples=NORM_BARS // 10)
        .fill_null(pl.col("spread_level"))
    ).alias("spread_norm")
    b = bars.with_columns(norm)
    return b.with_columns(
        abnormal_spread=pl.col("spread_norm") > pl.col("spread_norm").quantile(0.99).over("hour_utc")
    )


def to_m5(m1_costs: pl.DataFrame) -> pl.DataFrame:
    """An M5 bar's costs are those of its first M1 bar: the spread paid when entering
    at the M5 open. Abnormal/rollover flags hold if any minute of the bar has them."""
    flags = ("abnormal_spread", "in_rollover_window", "level_imputed")
    return (
        m1_costs.sort("ts_utc")
        .group_by_dynamic("ts_utc", every="5m", closed="left", label="left")
        .agg(
            pl.exclude("ts_utc", *flags).first(),
            *[pl.col(f).any() for f in flags],
        )
        .with_columns(pl.col("ts_server").dt.truncate("5m"))
    )
