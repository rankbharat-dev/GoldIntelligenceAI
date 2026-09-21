"""Turn a spec's conditions into per-bar entry signals.

Each feature row describes one M5 bar and is known at its ``available_at`` (the bar
close). A signal on that row is therefore a decision *at* ``available_at``; the engine
fills it no earlier than the next M1 open. Evaluating the whole frame at once is
equivalent to asking :class:`~candle_intel.features.store.FeatureStore` row by row,
because a condition only ever reads its own row.
"""

from __future__ import annotations

from functools import reduce

import polars as pl

from candle_intel.strategy.spec import Condition, Filters, StrategySpec

FILTER_COLUMNS = ("session", "vol_regime", "hour_utc", "dow", "spread_rel", "hyg_no_entry", "atr_pts")


def condition_expr(c: Condition) -> pl.Expr:
    col = pl.col(c.feature)
    v = c.value
    match c.op:
        case ">":
            e = col > v
        case ">=":
            e = col >= v
        case "<":
            e = col < v
        case "<=":
            e = col <= v
        case "==":
            e = col == v
        case "!=":
            e = col != v
        case "between":
            e = col.is_between(v[0], v[1])
        case "in":
            e = col.is_in(v)
        case "not_in":
            e = ~col.is_in(v)
    # A null feature (warm-up, zero-range bar) never satisfies a condition.
    return e.fill_null(False)


def filter_expr(f: Filters) -> pl.Expr:
    parts = [
        ~pl.col("hyg_no_entry").fill_null(True),
        pl.col("atr_pts").is_not_null() & (pl.col("atr_pts") > 0),
    ]
    if f.sessions is not None:
        parts.append(pl.col("session").is_in(f.sessions))
    if f.vol_regimes is not None:
        parts.append(pl.col("vol_regime").is_in(f.vol_regimes).fill_null(False))
    if f.hours_utc is not None:
        parts.append(pl.col("hour_utc").is_in(f.hours_utc))
    if f.weekdays is not None:
        parts.append(pl.col("dow").is_in(f.weekdays))
    if f.max_spread_rel is not None:
        parts.append((pl.col("spread_rel") <= f.max_spread_rel).fill_null(False))
    return reduce(lambda a, b: a & b, parts)


def columns_needed(spec: StrategySpec) -> list[str]:
    return sorted(set(spec.features_used()) | set(FILTER_COLUMNS))


def signals(spec: StrategySpec, features: pl.DataFrame) -> pl.DataFrame:
    """Rows where some entry rule fires: ``decision_time`` (= available_at),
    ``event_time``, ``side`` (+1 long / −1 short), ``atr_pts``. If a long and a short
    rule fire on the same bar the bar is skipped — the spec is contradictory there."""
    gate = filter_expr(spec.filters)
    longs = [
        reduce(lambda a, b: a & b, map(condition_expr, e.conditions))
        for e in spec.entries
        if e.side == "long"
    ]
    shorts = [
        reduce(lambda a, b: a & b, map(condition_expr, e.conditions))
        for e in spec.entries
        if e.side == "short"
    ]
    any_ = lambda xs: reduce(lambda a, b: a | b, xs) if xs else pl.lit(False)  # noqa: E731
    return (
        features.lazy()
        .with_columns(_l=any_(longs) & gate, _s=any_(shorts) & gate)
        .filter(pl.col("_l") ^ pl.col("_s"))
        .select(
            pl.col("available_at").alias("decision_time"),
            "event_time",
            pl.when(pl.col("_l")).then(1).otherwise(-1).cast(pl.Int8).alias("side"),
            "atr_pts",
        )
        .sort("decision_time")
        .collect()
    )
