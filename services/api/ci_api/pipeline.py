"""Phase 8 endpoints: the research engine's searches (Research Pipeline, Strategy Lab ·
AI Discovery) and the candidates leaderboard (My Strategies).

A search is created (and its hypotheses registered) before anything runs. In
``approve`` mode it waits for the owner; in ``auto`` mode it is queued at once.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from candle_intel.research import behaviours, discovery
from candle_intel.strategy.spec import SESSIONS, VOL_REGIMES

from . import research

router = APIRouter(prefix="/api")


class CreateBody(BaseModel):
    space: dict[str, Any]
    mode: Literal["auto", "approve"] = "approve"
    created_by: Literal["owner", "assistant"] = "owner"


def _submit(search_id: str) -> str:
    led, mk, runner = research.get_ledger(), research.get_market(), research.get_runner()
    rec = led.search(search_id)
    job = runner.submit(
        "search",
        f"Research search · {rec['name'] if rec else search_id}",
        {"search_id": search_id},
        lambda p: discovery.run(search_id, mk, led, p),
    )
    led.search_update(search_id, job_id=job, status="queued")
    return job


def _view(rec: dict[str, Any]) -> dict[str, Any]:
    led = research.get_ledger()
    job = led.job(rec["job_id"]) if rec.get("job_id") else None
    active = bool(job and job["status"] in ("queued", "running"))
    stale = rec["status"] in ("queued", "running") and not active
    return rec | {
        "job": {k: job[k] for k in ("job_id", "status", "progress", "message")} if job else None,
        "resumable": rec["status"] in ("paused", "failed") or stale,
    }


@router.get("/search/space")
def search_space() -> dict[str, Any]:
    """What a search can be built from: the registered behaviours as blocks, filter
    choices and sensible exit grids."""
    pats = behaviours.ensure_registered(research.get_ledger())
    return {
        "blocks": [
            {
                "label": p["name"][:80],
                "side": p["definition"]["side"],
                "conditions": p["definition"]["conditions"],
                "pattern_id": p["pattern_id"],
                "behaviour": p["behaviour"],
            }
            for p in pats
        ],
        "sessions": list(SESSIONS),
        "vol_regimes": list(VOL_REGIMES),
        "limits": {"max_trials": 600, "max_minutes": 720, "top_k": 10},
    }


@router.get("/searches")
def search_list() -> list[dict[str, Any]]:
    return [_view(r) for r in research.get_ledger().searches()]


@router.post("/searches")
def search_create(body: CreateBody) -> dict[str, Any]:
    try:
        space = discovery.SearchSpace.model_validate(body.space)
    except ValidationError as e:
        raise HTTPException(
            422,
            {
                "message": "invalid search",
                "errors": [{"loc": ".".join(map(str, err["loc"])), "msg": err["msg"]} for err in e.errors()],
            },
        ) from e
    led = research.get_ledger()
    rec = discovery.create(space, led, body.mode, body.created_by)
    if body.mode == "auto":
        _submit(rec["search_id"])
    return _view(led.search(rec["search_id"]) or rec)


@router.get("/searches/{search_id}")
def search_get(search_id: str) -> dict[str, Any]:
    led = research.get_ledger()
    rec = led.search(search_id)
    if rec is None:
        raise HTTPException(404, f"unknown search {search_id}")
    return _view(rec) | {
        "hypotheses": led.hypotheses(search_id),
        "live": discovery.summarise(search_id, led),
    }


@router.post("/searches/{search_id}/approve")
def search_approve(search_id: str) -> dict[str, Any]:
    led = research.get_ledger()
    rec = led.search(search_id)
    if rec is None:
        raise HTTPException(404, f"unknown search {search_id}")
    if rec["status"] != "proposed":
        raise HTTPException(409, f"search is {rec['status']}, not waiting for approval")
    return {"job_id": _submit(search_id)}


@router.post("/searches/{search_id}/pause")
def search_pause(search_id: str) -> dict[str, Any]:
    led = research.get_ledger()
    rec = led.search(search_id)
    if rec is None:
        raise HTTPException(404, f"unknown search {search_id}")
    if rec["status"] not in ("queued", "running"):
        raise HTTPException(409, f"search is {rec['status']}")
    led.search_update(search_id, control="pause")
    return {"ok": True, "note": "pauses after the hypothesis being tested now"}


@router.post("/searches/{search_id}/resume")
def search_resume(search_id: str) -> dict[str, Any]:
    led = research.get_ledger()
    rec = led.search(search_id)
    if rec is None:
        raise HTTPException(404, f"unknown search {search_id}")
    if not _view(rec)["resumable"]:
        raise HTTPException(409, f"search is {rec['status']}")
    led.search_update(search_id, control="")
    return {"job_id": _submit(search_id)}


@router.get("/candidates")
def candidates() -> list[dict[str, Any]]:
    """Latest Validate verdict per strategy, best first — the §15 leaderboard."""
    led = research.get_ledger()
    seen: dict[str, dict[str, Any]] = {}
    for r in led.runs(limit=500):
        if r["kind"] == "validate" and r["spec_hash"] not in seen:
            seen[r["spec_hash"]] = r
    specs = {s["spec_hash"]: s for s in led.specs()}
    rank = {"candidate": 0, "pending": 1, "rejected": 2}
    rows = []
    for h, r in seen.items():
        s = r["summary"] or {}
        sp = specs.get(h, {})
        rows.append(
            {
                "spec_hash": h,
                "run_id": r["run_id"],
                "family": r["family"],
                "name": s.get("name") or sp.get("name"),
                "created_by": sp.get("created_by"),
                "verdict": s.get("verdict"),
                "failed": s.get("failed"),
                "pending": s.get("pending"),
                "expectancy_r": s.get("expectancy_r"),
                "oos_expectancy_r": s.get("oos_expectancy_r"),
                "n": s.get("n"),
                "family_trials": s.get("family_trials"),
                "validated_at": r["created_at"],
            }
        )
    rows.sort(key=lambda x: (rank.get(x["verdict"] or "", 3), -(x["expectancy_r"] or -9)))
    return rows
