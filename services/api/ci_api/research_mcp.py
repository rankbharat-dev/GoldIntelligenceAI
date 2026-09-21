"""Candle Intelligence — research tools for the AI assistant's no-API mode (MCP, stdio).

Claude Code / Claude Desktop drive the research engine through these tools; Python does
every number. The server is a thin client of the local research API (``ci-api``), so
every action goes through the same ledger, trial counter and job queue as the dashboard.

What the assistant can do: read the feature catalogue and behaviour library, *propose*
strategies (saved with ``created_by="assistant"``), start backtests on tiers A / B / A∪B,
run exploratory event studies on tier A, propose searches (always in approve mode — the
owner starts them from the Research Pipeline page), read results and the candidates board.

What it cannot do, by construction: unseal or read the holdout (tier C results are
withheld), approve or resume its own searches, delete anything, change thresholds,
see account data or trade. The tool list is pinned by tests/unit/test_research_mcp.py.

    python -m ci_api.research_mcp        (CI_API_URL, default http://127.0.0.1:8000)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

log = logging.getLogger("ci_research_mcp")

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
# Proposing / starting research writes to the ledger (a trial is counted) but never deletes.
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

INSTRUCTIONS = """\
Research tools for Candle Intelligence (XAUUSD-only strategy research, no trading).
All numbers come from the local Python engine; never invent or estimate results.
Every backtest counts as a trial on its strategy family and raises the bar for that
family (Deflated Sharpe). Tier C (the newest ~20 % of data) is sealed: its results are
never returned here, and only the owner can unseal it. Searches you create wait for the
owner's approval. Explain results in simple Hinglish when talking to the owner."""

mcp = MCPServer(name="candle-intelligence-research", instructions=INSTRUCTIONS, version="0.1.0")

MAX_CHARS = 60_000


def _base() -> str:
    return os.environ.get("CI_API_URL", "http://127.0.0.1:8000").rstrip("/")


def _call(method: str, path: str, body: Any = None) -> Any:
    if not path.startswith("/api/"):
        raise ValueError("internal paths only")
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(  # noqa: S310 - fixed local http base, not user-supplied
        _base() + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:2000]
        return {"error": e.code, "detail": detail}
    except urllib.error.URLError as e:
        return {"error": "api_unreachable", "detail": f"{e}. Start the research API with ci-api."}


def _cap(x: Any) -> Any:
    s = json.dumps(x, default=str)
    if len(s) <= MAX_CHARS:
        return x
    return {"truncated": True, "json_head": s[:MAX_CHARS]}


def _q(x: str) -> str:
    return urllib.parse.quote(str(x), safe="")


def _no_tier_c(run: dict[str, Any]) -> dict[str, Any]:
    if run.get("tier") == "C":
        return {"sealed": True, "detail": "tier C (holdout) results are not available to the assistant"}
    return run


@mcp.tool(annotations=READ)
def research_status() -> dict[str, Any]:
    """Engine status: dataset, split (tier dates), commission assumption, families and trial counts."""
    ov = _call("GET", "/api/research/overview")
    return _cap(ov)


@mcp.tool(annotations=READ)
def feature_catalogue(group: str | None = None) -> dict[str, Any]:
    """Features a strategy condition can use (name, group, unit, description). Optional group filter,
    e.g. 'structure', 'anatomy', 'sequence', 'session', 'h1'."""
    cat = _call("GET", "/api/strategy/catalogue")
    if isinstance(cat, dict) and group:
        cat["features"] = [f for f in cat.get("features", []) if f.get("group") == group]
    return _cap(cat)


@mcp.tool(annotations=READ)
def behaviour_library() -> dict[str, Any]:
    """Pre-registered behaviours (blueprint §17) with their rules and latest tier A / B study results."""
    return _cap(_call("GET", "/api/behaviours"))


@mcp.tool(annotations=WRITE)
def propose_strategy(spec: dict[str, Any]) -> dict[str, Any]:
    """Validate and save a strategy spec (strategy-spec/1) as the assistant's proposal. Returns its
    hash and how often it fires on tiers A and B. Nothing is backtested until run_backtest."""
    spec = json.loads(json.dumps(spec))
    spec.setdefault("meta", {})["created_by"] = "assistant"
    saved = _call("POST", "/api/strategies", {"spec": spec})
    if "error" in saved:
        return saved
    prev = _call("POST", "/api/strategy/preview", {"spec": spec, "limit": 1})
    return {
        "spec_hash": saved.get("spec_hash"),
        "signals": prev.get("counts"),
        "bars": prev.get("bars_per_tier"),
    }


@mcp.tool(annotations=WRITE)
def run_backtest(spec_hash: str, tier: Literal["A", "B", "AB"] = "A") -> dict[str, Any]:
    """Backtest a saved strategy on tier A, B or A∪B (three cost scenarios). Counts as a trial.
    Returns a job id — poll job_status, then get_result with its run_id."""
    rec = _call("GET", f"/api/strategies/{_q(spec_hash)}")
    if "error" in rec:
        return rec
    return _call("POST", "/api/jobs/backtest", {"spec": rec["spec"], "tier": tier})


@mcp.tool(annotations=WRITE)
def run_event_study(
    side: Literal["long", "short"],
    conditions: list[dict[str, Any]],
    target_atr: Annotated[float, Field(gt=0, le=20)] = 1.5,
    stop_atr: Annotated[float, Field(gt=0, le=20)] = 1.0,
    horizon_bars: Annotated[int, Field(ge=1, le=576)] = 24,
) -> dict[str, Any]:
    """Exploratory 'what happened next' study of a behaviour on tier A (triple barrier, real costs,
    compared with all bars). Returns a job id."""
    body = {
        "name": "assistant study",
        "side": side,
        "conditions": conditions,
        "barriers": {"target_atr": target_atr, "stop_atr": stop_atr, "horizon_bars": horizon_bars},
        "tier": "A",
    }
    return _call("POST", "/api/jobs/study", body)


@mcp.tool(annotations=WRITE)
def propose_search(space: dict[str, Any]) -> dict[str, Any]:
    """Register a research-engine search (blocks × filters × exits, see /api/search/space). It is
    created in approve mode: the owner reviews and starts it on the Research Pipeline page."""
    return _call("POST", "/api/searches", {"space": space, "mode": "approve", "created_by": "assistant"})


@mcp.tool(annotations=READ)
def job_status(job_id: str) -> dict[str, Any]:
    """Status, progress and result run id of a job."""
    j = _call("GET", f"/api/jobs/{_q(job_id)}")
    return {
        k: j.get(k) for k in ("job_id", "kind", "title", "status", "progress", "message", "result", "error")
    }


@mcp.tool(annotations=READ)
def get_result(run_id: str) -> dict[str, Any]:
    """A finished run (backtest, validate, study, screen): headline numbers, breakdowns, checklist.
    Tier C runs are withheld."""
    run = _call("GET", f"/api/runs/{_q(run_id)}")
    if "error" in run:
        return run
    run = _no_tier_c(run)
    for k in ("equity", "markers"):
        run.pop(k, None)
    for s in (run.get("results") or {}).values():
        if isinstance(s, dict):
            s.pop("equity", None)
            s.pop("by_month", None)
    return _cap(run)


@mcp.tool(annotations=READ)
def search_status(search_id: str) -> dict[str, Any]:
    """A research-engine search: status, hypotheses with accepted / rejected reasons, trial count."""
    return _cap(_call("GET", f"/api/searches/{_q(search_id)}"))


@mcp.tool(annotations=READ)
def list_candidates() -> dict[str, Any]:
    """The §15 leaderboard: latest Validate verdict per strategy."""
    return {"candidates": _cap(_call("GET", "/api/candidates"))}


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
