"""Code-defined pattern detectors (CEO Work Lab, Phase 4): catalogue and study jobs.

A pattern study is an ordinary study run (kind ``study``) — the result opens in the
Behaviour Explorer like any other. Tier B only confirms the default rule; C is sealed.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from candle_intel import patterns

from . import research

router = APIRouter(prefix="/api")


class PatternStudyBody(BaseModel):
    detector: patterns.Detector
    params: patterns.SweepParams = patterns.SweepParams()
    barriers: patterns.Barriers = patterns.Barriers()
    tier: Literal["A", "B"] = "A"


@router.get("/patterns/catalogue")
def pattern_catalogue() -> dict[str, Any]:
    return patterns.catalogue()


@router.post("/jobs/pattern-study")
def job_pattern_study(body: PatternStudyBody) -> dict[str, Any]:
    if body.tier == "B" and body.params != patterns.SweepParams():
        raise HTTPException(422, "tier B confirms the default rule only — tune parameters on tier A")
    led, mk, runner = research.get_ledger(), research.get_market(), research.get_runner()

    def work(p):
        try:
            doc = patterns.run_pattern_study(mk, led, body.detector, body.params, body.barriers, body.tier, p)
        except patterns.PatternError as e:
            raise RuntimeError(str(e)) from e
        return {"run_id": doc["run_id"]}

    title = f"Pattern {body.detector} · tier {body.tier}"
    return {"job_id": runner.submit("study", title, body.model_dump(), work)}
