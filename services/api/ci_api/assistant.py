"""Phase 10 endpoints: the AI Assistant (API mode) and the ML Lab.

API mode sends only the question, recent turns, the feature catalogue and — if the owner
attaches them — a spec or a tier A / B result (never tier C, never keys). The reply may
contain a proposed spec, validated here; nothing is saved or run on the assistant's
behalf. The no-API mode is the research MCP server (``ci_api.research_mcp``).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from candle_intel.assistant import chat
from candle_intel.ml import filter as mlf
from candle_intel.research import runs

from . import research

router = APIRouter(prefix="/api")


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(max_length=20_000)]


class ChatBody(BaseModel):
    question: Annotated[str, Field(min_length=1, max_length=8000)]
    history: Annotated[list[Turn], Field(max_length=40)] = []
    run_id: str | None = None
    spec: dict[str, Any] | None = None
    fast: bool = False


@router.get("/assistant/status")
def assistant_status() -> dict[str, Any]:
    return chat.status()


@router.post("/assistant/chat")
def assistant_chat(body: ChatBody) -> dict[str, Any]:
    context: dict[str, Any] = {}
    try:
        if body.run_id:
            context["result"] = chat.summarise_run(runs.load_run(body.run_id))
        if body.spec:
            context["strategy_spec"] = body.spec
        return chat.ask(body.question, [t.model_dump() for t in body.history], context or None, body.fast)
    except FileNotFoundError as e:
        raise HTTPException(404, f"unknown run {body.run_id}") from e
    except chat.AssistantError as e:
        raise HTTPException(502, str(e)) from e


class MLBody(BaseModel):
    spec: dict[str, Any]


@router.post("/jobs/ml")
def job_ml(body: MLBody) -> dict[str, Any]:
    s = research.parse_spec(body.spec)
    led, mk, runner = research.get_ledger(), research.get_market(), research.get_runner()
    runs.save_spec(s, led)

    def work(p):
        try:
            return {"run_id": mlf.train_and_test(s, mk, led, p)["run_id"]}
        except mlf.MLError as e:
            raise RuntimeError(str(e)) from e

    return {"job_id": runner.submit("ml", f"ML filter · {s.meta.name}", {"spec_hash": s.spec_hash}, work)}


@router.get("/ml/runs")
def ml_runs() -> list[dict[str, Any]]:
    return [r for r in research.get_ledger().runs(limit=500) if r["kind"] == "ml"]
