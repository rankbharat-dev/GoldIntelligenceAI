"""Code-defined chart patterns with explicit rules (CEO Work Lab, Phase 4).

Each detector turns a visual idea into events a computer finds the same way every time,
and :func:`run_pattern_study` measures what happened after them with the Behaviour
Explorer's triple-barrier study (same fills and costs as the backtester). Results are
ordinary study runs in the ledger (kind ``study``), so they show in the Explorer too.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import polars as pl
from pydantic import BaseModel, Field

from candle_intel.backtest.market import Market
from candle_intel.patterns import prev_day
from candle_intel.research import behaviours, events, runs, studies
from candle_intel.research.ledger import Ledger

Detector = Literal["pdh_sweep", "pdl_sweep"]
SESSIONS = ("asian", "london", "new_york", "london_ny_overlap", "off")


class SweepParams(BaseModel):
    min_depth_atr: Annotated[float, Field(ge=0, le=5)] = 0.0
    max_depth_atr: Annotated[float, Field(gt=0, le=10)] | None = 1.5
    first_only: bool = True
    no_prior_acceptance: bool = True
    sessions: list[Literal["asian", "london", "new_york", "london_ny_overlap", "off"]] | None = None
    min_prev_day_bars: Annotated[int, Field(ge=0, le=288)] = 120


class Barriers(BaseModel):
    target_atr: Annotated[float, Field(gt=0, le=20)] = 1.5
    stop_atr: Annotated[float, Field(gt=0, le=20)] = 1.0
    horizon_bars: Annotated[int, Field(ge=1, le=576)] = 24


def catalogue() -> dict[str, Any]:
    return {
        "detectors": {
            "pdh_sweep": prev_day.describe("pdh") | {"timeframe": "M5"},
            "pdl_sweep": prev_day.describe("pdl") | {"timeframe": "M5"},
        },
        "params": SweepParams.model_json_schema(),
        "defaults": SweepParams().model_dump(),
        "barriers_default": Barriers().model_dump(),
        "sessions": list(SESSIONS),
        "tiers": {
            "A": "explore freely (any parameters)",
            "B": "confirmation only with the default parameters — no tuning on tier B",
            "C": "sealed",
        },
    }


class PatternError(ValueError):
    pass


def events_for(mk: Market, detector: Detector, params: SweepParams, tier: str) -> pl.DataFrame:
    ev = prev_day.detect(mk, "pdh" if detector == "pdh_sweep" else "pdl", **params.model_dump())
    lo, hi = mk.split.bounds(tier)  # type: ignore[arg-type]
    return ev.filter((pl.col("decision_time") >= lo) & (pl.col("decision_time") < hi))


def run_pattern_study(
    mk: Market,
    ledger: Ledger,
    detector: Detector,
    params: SweepParams | None = None,
    barriers: Barriers | None = None,
    tier: str = "A",
    progress=None,
) -> dict[str, Any]:
    params = params or SweepParams()
    barriers = barriers or Barriers()
    if tier not in ("A", "B"):
        raise PatternError("pattern studies run on tier A or B; tier C stays sealed")
    if tier == "B" and params != SweepParams():
        raise PatternError("tier B confirms the default rule only — tune parameters on tier A")
    if progress:
        progress(0.02, f"detecting {detector}")
    ev = events_for(mk, detector, params, tier)
    side = "short" if detector == "pdh_sweep" else "long"
    defn = {
        "side": side,
        "conditions": [{"feature": "atr_pts", "op": ">", "value": 0}],  # placeholder: events come from code
        "barriers": barriers.model_dump(),
        "detector": detector,
        "params": params.model_dump(),
        "rule_version": prev_day.RULE_VERSION,
    }
    about = prev_day.describe("pdh" if detector == "pdh_sweep" else "pdl")
    name = f"{about['name']} · code v{prev_day.RULE_VERSION}"
    spec = events.as_spec(defn, name)
    feats = mk.features(events.columns_needed(spec))
    sigs = ev.select("decision_time", "event_time", "side", "atr_pts")
    res = events.summarise_signals(
        spec, defn, sigs, feats, mk, tier, registered=tier == "B", progress=progress
    )
    key = behaviours.definition_hash(defn)
    doc = {
        "run_id": runs.new_run_id("study", key, tier),
        "kind": "study",
        "name": name,
        "pattern_id": None,
        "detector": detector,
        "detector_rule": about["rule"],
        "detector_counts": prev_day.sanity(ev),
        "definition_hash": key,
        "lineage": {
            "dataset_id": mk.dataset_id,
            "cost_model_id": mk.cost_model_id,
            "feature_set_id": mk.feature_set_id,
        },
    } | res
    p = res["scenarios"]["pessimistic"]
    summary = {
        "name": name,
        "pattern_id": None,
        "detector": detector,
        "exploratory": tier == "A",
        "n": res["occurrences"],
        "target_rate": p.get("target_rate"),
        "mean_r_gross": p.get("mean_r_gross"),
        "mean_r_net": p.get("mean_r_net"),
        "lift_target_rate": (res["lift_vs_baseline"] or {}).get("target_rate"),
        "p_gross": res["gross"]["bootstrap"].get("p_mean_le_0"),
        "sufficient": res["sample"]["sufficient"],
    }
    return studies._record(doc, "study", key, f"study:detector:{detector}", tier, summary, ledger)
