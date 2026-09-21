"""Candle Intelligence — CEO Work Lab tools for the five Claude Code agents (MCP, stdio).

The Research Director and its four specialists (``.claude/agents/*.md``) coordinate
through these tools: read the owner's mission, submit a plan, claim / log / finish tasks,
and hand in the final report. Research itself goes through the existing
``candle-intelligence-research`` tools (and ``run_validation`` / pattern tools here), so
every number is the engine's and lands in the same ledger.

What the agents cannot do, by construction: approve their own plans or tasks, resume
or cancel a mission (the CEO does that on the dashboard), touch tier C, trade, delete
anything, or read files. The tool list is pinned by tests/unit/test_ceo_mcp.py.

    python -m ci_api.ceo_mcp        (CI_API_URL, default http://127.0.0.1:8000)
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from .research_mcp import _call, _cap, _q

log = logging.getLogger("ci_ceo_mcp")

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

Agent = Literal["data_scientist", "pattern_analyst", "strategy_architect", "validator"]

INSTRUCTIONS = """\
CEO Work Lab for Candle Intelligence (XAUUSD-only research, no trading). The owner is the
CEO; the Research Director plans and delegates to four specialists; every task is claimed
with task_start, logged with task_log, and closed with task_finish (or task_fail).
Never invent numbers: a finding with metrics must cite the run_id or job_id that produced
them (read-only statistics: dataset_id + the exact query), or the hand-in is rejected.
Tier C is sealed. Write summaries in simple Hinglish."""

mcp = MCPServer(name="candle-intelligence-ceo", instructions=INSTRUCTIONS, version="0.1.0")


# ---------------------------------------------------------------- Research Director


@mcp.tool(annotations=READ)
def next_mission() -> dict[str, Any]:
    """The mission to work on now: the oldest one in draft, awaiting approval or running (paused
    missions are skipped). Includes its tasks and recent events. {"mission": null} if none."""
    return _cap(_call("GET", "/api/ceo/missions/next"))


@mcp.tool(annotations=READ)
def get_mission(mission_id: str) -> dict[str, Any]:
    """A mission with its plan, every task (state, outputs, errors) and the audit trail."""
    return _cap(_call("GET", f"/api/ceo/missions/{_q(mission_id)}"))


@mcp.tool(annotations=WRITE)
def submit_plan(mission_id: str, tasks: list[dict[str, Any]], note: str | None = None) -> dict[str, Any]:
    """Submit the plan (or add tasks to it later). Each task: {"key": "short-slug", "agent":
    data_scientist | pattern_analyst | strategy_architect | validator, "title": "...",
    "instructions": "what to do, inputs, expected output", "depends_on": [keys or task ids],
    "needs_approval": false, "revision_of": null or task id}. `note` explains the plan to the CEO
    in Hinglish. Limits (tasks, revisions) are enforced by the server."""
    return _cap(_call("POST", f"/api/ceo/missions/{_q(mission_id)}/plan", {"tasks": tasks, "note": note}))


@mcp.tool(annotations=READ)
def ready_tasks(mission_id: str) -> dict[str, Any]:
    """Tasks whose dependencies are done and that may start now (state queued). Empty when the
    mission is paused, awaiting the CEO, or finished."""
    return {"ready": _cap(_call("GET", f"/api/ceo/missions/{_q(mission_id)}/ready"))}


@mcp.tool(annotations=WRITE)
def submit_report(mission_id: str, report: dict[str, Any]) -> dict[str, Any]:
    """Close the mission with the final report: {"headline", "summary" (simple Hinglish),
    "verdict": promising | inconclusive | rejected | blocked, "findings": [{"text", "metrics",
    "source": {"run_id"|"job_id"}}], "strategies": [spec_hash], "recommendations": [...],
    "limitations": [at least one]}. All tasks must be finished first."""
    return _cap(_call("POST", f"/api/ceo/missions/{_q(mission_id)}/report", report))


@mcp.tool(annotations=READ)
def read_messages(mission_id: str) -> dict[str, Any]:
    """Director Room: the CEO's and your messages for this mission, oldest first. Read them
    before planning and after each round — the CEO may add wishes or answer your questions."""
    return {"messages": _cap(_call("GET", f"/api/ceo/missions/{_q(mission_id)}/messages"))}


@mcp.tool(annotations=WRITE)
def post_message(mission_id: str, text: str) -> dict[str, Any]:
    """Director Room: write to the CEO (Hinglish) — explain the plan, answer a message, or ask a
    question that is essential to continue."""
    body = {"text": text[:4000], "actor": "director"}
    return _call("POST", f"/api/ceo/missions/{_q(mission_id)}/messages", body)


# ---------------------------------------------------------------- every agent


@mcp.tool(annotations=READ)
def get_task(task_id: str) -> dict[str, Any]:
    """One task: instructions, dependencies, state, attempt, output, error."""
    return _cap(_call("GET", f"/api/ceo/tasks/{_q(task_id)}"))


@mcp.tool(annotations=WRITE)
def task_start(task_id: str, agent: Agent) -> dict[str, Any]:
    """Claim a queued task before working on it. Only the task's own agent can claim it, once."""
    return _call("POST", f"/api/ceo/tasks/{_q(task_id)}/start", {"agent": agent})


@mcp.tool(annotations=WRITE)
def task_log(task_id: str, agent: Agent, message: str) -> dict[str, Any]:
    """Write a progress line (visible live to the CEO). Also keeps the task's heartbeat alive —
    log at least every 20 minutes during long work."""
    return _call("POST", f"/api/ceo/tasks/{_q(task_id)}/log", {"agent": agent, "message": message[:4000]})


@mcp.tool(annotations=WRITE)
def task_finish(task_id: str, agent: Agent, output: dict[str, Any]) -> dict[str, Any]:
    """Hand in the task: {"summary": "Hinglish, what was found", "findings": [{"text", "metrics":
    {...}, "source": {"run_id" | "job_id"}}], "artifacts": [{"kind": run|job|spec|search|pattern|note,
    "ref", "title"}], "limitations": [...], "next_steps": [...]}. Metrics without an existing
    source are rejected."""
    return _cap(_call("POST", f"/api/ceo/tasks/{_q(task_id)}/finish", {"agent": agent, "output": output}))


@mcp.tool(annotations=WRITE)
def task_fail(task_id: str, agent: Agent, error: str) -> dict[str, Any]:
    """Report that the task could not be done (and why). It is retried if attempts remain."""
    return _call("POST", f"/api/ceo/tasks/{_q(task_id)}/fail", {"agent": agent, "error": error[:4000]})


# ---------------------------------------------------------------- research helpers


@mcp.tool(annotations=READ)
def data_health() -> dict[str, Any]:
    """The research dataset: broker, bar counts per timeframe, coverage window, gaps and quality
    checks, clock model. Read-only (from the built Parquet dataset's manifest)."""
    s = _call("GET", "/api/datasets/latest/summary")
    if isinstance(s, dict):
        s.pop("symbol_spec", None)
    return _cap(s)


@mcp.tool(annotations=READ)
def feature_distribution(
    feature: str, by: Literal["none", "year", "session", "vol_regime", "tier"] = "none"
) -> dict[str, Any]:
    """Distribution of one feature over tiers A∪B (C sealed), optionally split by year, session,
    volatility regime or tier — e.g. feature='range_atr' by='session'. Makes no run: cite it as
    {"dataset_id": <from data_health>, "query": "feature_distribution(<feature>, by=<by>)"}."""
    return _cap(_call("GET", f"/api/explore/distribution?feature={_q(feature)}&by={by}"))


@mcp.tool(annotations=READ)
def wait_job(job_id: str, max_wait_s: Annotated[int, Field(ge=5, le=240)] = 180) -> dict[str, Any]:
    """Wait (up to max_wait_s) for a research job to finish, then return its status. Call again if
    it is still running. Saves polling job_status many times."""
    t0 = time.monotonic()
    while True:
        j = _call("GET", f"/api/jobs/{_q(job_id)}")
        if not isinstance(j, dict) or ("error" in j and "status" not in j):
            return j
        if j.get("status") not in ("queued", "running") or time.monotonic() - t0 > max_wait_s:
            return {
                k: j.get(k)
                for k in ("job_id", "kind", "title", "status", "progress", "message", "result", "error")
            }
        time.sleep(3)


@mcp.tool(annotations=WRITE)
def run_validation(spec_hash: str) -> dict[str, Any]:
    """Full validation of a saved strategy (tier B out-of-sample, walk-forward on A, Deflated
    Sharpe at the family's true trial count, §15 checklist). Never touches tier C. Returns a
    job id — wait_job, then get_result with its run_id."""
    rec = _call("GET", f"/api/strategies/{_q(spec_hash)}")
    if "error" in rec:
        return rec
    return _call("POST", "/api/jobs/validate", {"spec": rec["spec"], "params": None})


@mcp.tool(annotations=READ)
def pattern_catalogue() -> dict[str, Any]:
    """Code-defined pattern detectors (e.g. previous-day high / low sweeps on M5) with their exact
    rules, parameters, defaults and tier rules."""
    return _cap(_call("GET", "/api/patterns/catalogue"))


@mcp.tool(annotations=WRITE)
def run_pattern_study(
    detector: Literal["pdh_sweep", "pdl_sweep"],
    params: dict[str, Any] | None = None,
    target_atr: Annotated[float, Field(gt=0, le=20)] = 1.5,
    stop_atr: Annotated[float, Field(gt=0, le=20)] = 1.0,
    horizon_bars: Annotated[int, Field(ge=1, le=576)] = 24,
    tier: Literal["A", "B"] = "A",
) -> dict[str, Any]:
    """What happened after each detected event (triple barrier with real costs, vs the all-bars
    baseline, by year / session / regime). params: min_depth_atr, max_depth_atr, first_only,
    no_prior_acceptance, sessions, min_prev_day_bars. Tier B only with default params. Returns a
    job id — wait_job, then get_result with its run_id."""
    body = {
        "detector": detector,
        "params": params or {},
        "barriers": {"target_atr": target_atr, "stop_atr": stop_atr, "horizon_bars": horizon_bars},
        "tier": tier,
    }
    return _call("POST", "/api/jobs/pattern-study", body)


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
