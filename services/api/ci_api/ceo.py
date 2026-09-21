"""CEO Work Lab endpoints: the owner's missions and the agents' task hand-ins.

Two audiences use this router:

* the dashboard (``/ceo-lab``) — create a mission, approve a plan or a task, pause,
  resume, cancel, and read everything;
* the agents, through the ``candle-intelligence-ceo`` MCP server — submit a plan,
  claim / log / finish / fail tasks, write the final report.

The CEO-only actions (approve, resume, cancel) are simply not exposed by the MCP
server; tests/unit/test_ceo_mcp.py pins that. No research runs here: agents start
engine work through the existing research endpoints and cite its run / job ids.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from functools import lru_cache
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from candle_intel.ceo.store import AGENTS, CeoError, CeoStore

from . import research

router = APIRouter(prefix="/api/ceo")


_lock = threading.Lock()


@lru_cache(maxsize=1)
def _store_for(ledger_id: int) -> CeoStore:
    return CeoStore(research.get_ledger())


def get_store() -> CeoStore:
    led = research.get_ledger()
    with _lock:  # first requests arrive together; create the tables once
        return _store_for(id(led))


def _do(fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0]) if e.args else "not found") from e
    except ValidationError as e:
        raise HTTPException(
            422,
            {
                "message": "invalid input",
                "errors": [{"loc": ".".join(map(str, err["loc"])), "msg": err["msg"]} for err in e.errors()],
            },
        ) from e
    except CeoError as e:
        raise HTTPException(409, str(e)) from e


# ---------------------------------------------------------------- dashboard


class MissionBody(BaseModel):
    objective: Annotated[str, Field(min_length=10, max_length=4000)]
    constraints: dict[str, Any] = {}
    limits: dict[str, Any] = {}
    require_plan_approval: bool = False


@router.get("/overview")
def overview() -> dict[str, Any]:
    return _do(get_store().overview)


@router.get("/agents")
def agents() -> dict[str, Any]:
    return AGENTS


@router.post("/missions")
def mission_create(body: MissionBody) -> dict[str, Any]:
    return _do(
        get_store().create_mission, body.objective, body.constraints, body.limits, body.require_plan_approval
    )


@router.get("/missions")
def mission_list(limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[dict[str, Any]]:
    return get_store().missions(limit)


@router.get("/missions/next")
def mission_next() -> dict[str, Any]:
    m = get_store().next_mission()
    return {"mission": m}


@router.get("/missions/{mission_id}")
def mission_get(mission_id: str) -> dict[str, Any]:
    return _do(get_store().mission, mission_id)


STREAM_POLL_S = 1.5
STREAM_MAX_S = 600  # the browser's EventSource reconnects by itself


@router.get("/missions/{mission_id}/stream")
async def mission_stream(mission_id: str, request: Request) -> StreamingResponse:
    """Server-Sent Events: ``event: change`` with the mission's fingerprint whenever it
    moves (the page then refetches); a comment every 15 s keeps proxies from closing it.
    The page falls back to polling if the stream is unavailable."""
    store = get_store()
    _do(store.version, mission_id)  # 404 before streaming starts

    async def gen():
        last, quiet, t0 = None, 0.0, time.monotonic()
        yield "retry: 3000\n\n"
        while time.monotonic() - t0 < STREAM_MAX_S:
            if await request.is_disconnected():
                return
            try:
                v = await run_in_threadpool(store.version, mission_id)
            except KeyError:
                return
            if v != last:
                last, quiet = v, 0.0
                yield f"event: change\ndata: {json.dumps({'version': v})}\n\n"
            elif quiet >= 15:
                quiet = 0.0
                yield ": keep-alive\n\n"
            await asyncio.sleep(STREAM_POLL_S)
            quiet += STREAM_POLL_S

    headers = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


@router.get("/missions/{mission_id}/events")
def mission_events(mission_id: str, after: Annotated[int, Query(ge=0)] = 0) -> list[dict[str, Any]]:
    return get_store().events(mission_id, after)


@router.post("/missions/{mission_id}/approve")
def mission_approve(mission_id: str) -> dict[str, Any]:
    return _do(get_store().approve_plan, mission_id)


@router.post("/missions/{mission_id}/pause")
def mission_pause(mission_id: str) -> dict[str, Any]:
    return _do(get_store().pause, mission_id)


@router.post("/missions/{mission_id}/resume")
def mission_resume(mission_id: str) -> dict[str, Any]:
    return _do(get_store().resume, mission_id)


@router.post("/missions/{mission_id}/cancel")
def mission_cancel(mission_id: str) -> dict[str, Any]:
    return _do(get_store().cancel, mission_id)


@router.post("/tasks/{task_id}/approve")
def task_approve(task_id: str) -> dict[str, Any]:
    return _do(get_store().approve_task, task_id)


class FeedbackBody(BaseModel):
    feedback: Annotated[str, Field(min_length=5, max_length=4000)]


class EditBody(BaseModel):
    title: str | None = None
    instructions: str | None = None


class MessageBody(BaseModel):
    text: Annotated[str, Field(min_length=1, max_length=4000)]
    actor: Literal["ceo", "director"] = "ceo"


@router.post("/missions/{mission_id}/send-back")
def mission_send_back(mission_id: str, body: FeedbackBody) -> dict[str, Any]:
    return _do(get_store().send_back_plan, mission_id, body.feedback)


@router.post("/tasks/{task_id}/edit")
def task_edit(task_id: str, body: EditBody) -> dict[str, Any]:
    return _do(get_store().edit_task, task_id, body.title, body.instructions)


@router.post("/tasks/{task_id}/drop")
def task_drop(task_id: str) -> dict[str, Any]:
    return _do(get_store().drop_task, task_id)


@router.get("/missions/{mission_id}/messages")
def mission_messages(mission_id: str) -> list[dict[str, Any]]:
    return _do(get_store().messages, mission_id)


# ---------------------------------------------------------------- bridge (Phase 7)


class FinishRunBody(BaseModel):
    status: Literal["done", "failed", "cancelled"]
    exit_code: int | None = None
    usage: dict[str, Any] | None = None
    tail: Annotated[str, Field(max_length=20000)] = ""


@router.post("/missions/{mission_id}/run")
def mission_run(mission_id: str) -> dict[str, Any]:
    """CEO: start the agents now through the local bridge (if it is running)."""
    run = _do(get_store().request_run, mission_id)
    return {"run": run, "bridge": get_store().bridge_status()}


@router.get("/bridge")
def bridge() -> dict[str, Any]:
    s = get_store()
    return s.bridge_status() | {"runs": s.runs(limit=10)}


@router.post("/bridge/heartbeat")
def bridge_heartbeat(info: dict[str, Any]) -> dict[str, Any]:
    get_store().heartbeat(info)
    return {"ok": True}


@router.post("/bridge/claim")
def bridge_claim() -> dict[str, Any]:
    return {"run": get_store().claim_run()}


@router.post("/runs/{run_id}/finish")
def run_finish(run_id: str, body: FinishRunBody) -> dict[str, Any]:
    return _do(get_store().finish_run, run_id, body.status, body.exit_code, body.usage, body.tail)


@router.post("/missions/{mission_id}/messages")
def mission_message(mission_id: str, body: MessageBody) -> dict[str, Any]:
    return _do(get_store().post_message, mission_id, body.actor, body.text)


# ---------------------------------------------------------------- agents


class PlanBody(BaseModel):
    tasks: list[dict[str, Any]]
    note: Annotated[str, Field(max_length=6000)] | None = None


class AgentBody(BaseModel):
    agent: str


class LogBody(AgentBody):
    message: Annotated[str, Field(min_length=1, max_length=4000)]
    data: Any = None


class FinishBody(AgentBody):
    output: dict[str, Any]


class FailBody(AgentBody):
    error: Annotated[str, Field(min_length=3, max_length=4000)]


@router.post("/missions/{mission_id}/plan")
def mission_plan(mission_id: str, body: PlanBody) -> dict[str, Any]:
    return _do(get_store().add_tasks, mission_id, body.tasks, body.note)


@router.get("/missions/{mission_id}/ready")
def mission_ready(mission_id: str) -> list[dict[str, Any]]:
    return _do(get_store().ready_tasks, mission_id)


@router.post("/missions/{mission_id}/report")
def mission_report(mission_id: str, report: dict[str, Any]) -> dict[str, Any]:
    return _do(get_store().submit_report, mission_id, report)


@router.get("/tasks/{task_id}")
def task_get(task_id: str) -> dict[str, Any]:
    return _do(get_store().task, task_id)


@router.post("/tasks/{task_id}/start")
def task_start(task_id: str, body: AgentBody) -> dict[str, Any]:
    return _do(get_store().start_task, task_id, body.agent)


@router.post("/tasks/{task_id}/log")
def task_log(task_id: str, body: LogBody) -> dict[str, Any]:
    _do(get_store().log, task_id, body.agent, body.message, body.data)
    return {"ok": True}


@router.post("/tasks/{task_id}/finish")
def task_finish(task_id: str, body: FinishBody) -> dict[str, Any]:
    return _do(get_store().finish_task, task_id, body.agent, body.output)


@router.post("/tasks/{task_id}/fail")
def task_fail(task_id: str, body: FailBody) -> dict[str, Any]:
    return _do(get_store().fail_task, task_id, body.agent, body.error)
