"""Out-of-sample validation of the spread model (blueprint §6, roadmap Phase 2 exit).

The tick days are split chronologically: the model is fitted on the first 80 %
and asked to predict the time-weighted spread of every minute in the last 20 %
it has never seen. Two models are scored on the same minutes:

    level_x_ratio  — the chosen model (bar level × conditional ratio)
    abs_cells      — the literal blueprint cell table (absolute spread per cell)

A second check needs no ticks: over the pre-tick history, how often does the
abs-cell model predict a *typical* spread below the minimum the broker actually
quoted in that minute? Any such prediction is impossible by construction.

Acceptance criteria are fixed here, before the numbers are seen.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from candle_intel.costs import spread

HOLDOUT_SHARE = 0.20
ACCEPTANCE = {
    "max_abs_relative_bias_p50": 0.15,  # mean predicted p50 vs mean measured spread
    "min_coverage_p90": 0.85,  # share of held-out minutes at or below predicted p90
}


def metrics(pred: pl.DataFrame, obs: str = "spread_twmean") -> dict[str, Any]:
    o = pl.col(obs)
    r = pred.select(
        n=pl.len(),
        mean_measured=o.mean(),
        mean_p50=pl.col("p50").mean(),
        mae_p50=(pl.col("p50") - o).abs().mean(),
        median_ae_p50=(pl.col("p50") - o).abs().median(),
        coverage_p90=(o <= pl.col("p90") + 1e-9).mean(),
        coverage_p99=(o <= pl.col("p99") + 1e-9).mean(),
    ).row(0, named=True)
    r["relative_bias_p50"] = (r["mean_p50"] - r["mean_measured"]) / r["mean_measured"]
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}


def split_day(measured: pl.DataFrame, share: float = HOLDOUT_SHARE):
    days = measured["ts_utc"].dt.date().unique().sort()
    return days[int(len(days) * (1 - share))]


def validate(khist: pl.DataFrame, measured: pl.DataFrame, keys: pl.DataFrame) -> dict[str, Any]:
    cut = split_day(measured)
    in_calib = pl.col("ts_utc").dt.date() < cut
    calib = khist.filter(in_calib)
    held = measured.filter(~in_calib).join(keys, on="ts_utc", how="inner")

    ratio = spread.cells(calib, "ratio", "calibration")
    absolute = spread.cells(calib, "abs", "calibration")

    pred_a = spread.lookup(held, ratio).with_columns(
        [(pl.col("spread_level") * pl.col(q)).alias(q) for q in spread.QCOLS]
    )
    pred_b = spread.lookup(held, absolute)
    a, b = metrics(pred_a), metrics(pred_b)

    # Weekly error: shows *where* a model breaks (tier changes), not just how much.
    weekly = (
        pred_a.select("ts_utc", "spread_twmean", a_p50="p50")
        .join(pred_b.select("ts_utc", b_p50="p50"), on="ts_utc")
        .group_by(week=pl.col("ts_utc").dt.truncate("1w"))
        .agg(
            measured=pl.col("spread_twmean").mean(),
            level_x_ratio=pl.col("a_p50").mean(),
            abs_cells=pl.col("b_p50").mean(),
        )
        .sort("week")
    )

    # Pre-tick history: can the abs-cell model even be right?
    first_tick = measured["ts_utc"].min()
    history = spread.lookup(keys.filter(pl.col("ts_utc") < first_tick), absolute)
    impossible = history.select(
        n=pl.len(),
        share_p50_below_quoted_minimum=(pl.col("p50") < pl.col("spread_level")).mean(),
        median_p50_over_level=(pl.col("p50") / pl.col("spread_level")).median(),
    ).row(0, named=True)

    passed = (
        abs(a["relative_bias_p50"]) <= ACCEPTANCE["max_abs_relative_bias_p50"]
        and a["coverage_p90"] >= ACCEPTANCE["min_coverage_p90"]
    )
    return {
        "method": "chronological holdout of tick days; fit on earlier days, predict later minutes",
        "calibration_days_before": str(cut),
        "holdout_share": HOLDOUT_SHARE,
        "holdout_minutes": held.height,
        "acceptance": ACCEPTANCE,
        "chosen_model": "level_x_ratio",
        "passed": passed,
        "models": {"level_x_ratio": a, "abs_cells": b},
        "abs_cells_on_pre_tick_history": {
            k: (round(v, 4) if isinstance(v, float) else v) for k, v in impossible.items()
        },
        "weekly_holdout": [
            {
                "week": str(r["week"].date()),
                **{k: round(r[k], 2) for k in ("measured", "level_x_ratio", "abs_cells")},
            }
            for r in weekly.iter_rows(named=True)
        ],
    }
