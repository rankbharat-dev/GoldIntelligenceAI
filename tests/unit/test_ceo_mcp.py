"""The CEO Work Lab's agent surface is part of the guardrails: pin the tools, and check that
each agent definition only names tools that exist and that fit its role."""

from __future__ import annotations

import asyncio
import re

from ci_api import ceo_mcp, research_mcp
from ci_api.ceo_mcp import mcp

from candle_intel.config.settings import PROJECT_ROOT

EXPECTED = {
    "next_mission",
    "get_mission",
    "submit_plan",
    "ready_tasks",
    "submit_report",
    "read_messages",
    "post_message",
    "get_task",
    "task_start",
    "task_log",
    "task_finish",
    "task_fail",
    "data_health",
    "feature_distribution",
    "wait_job",
    "run_validation",
    "pattern_catalogue",
    "run_pattern_study",
}
AGENTS_DIR = PROJECT_ROOT / ".claude" / "agents"
COMMAND = PROJECT_ROOT / ".claude" / "commands" / "ceo-run.md"


def _names(server) -> set[str]:
    return {t.name for t in asyncio.run(server.list_tools())}


def _tools_of(path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^(tools|allowed-tools):\s*(.+)$", text, re.M)
    assert m, f"{path.name} has no tools list"
    return [t.strip() for t in m.group(2).split(",")]


def test_tool_set_is_pinned() -> None:
    assert _names(mcp) == EXPECTED


def test_no_ceo_only_or_dangerous_tools() -> None:
    for name in _names(mcp):
        assert not any(
            w in name
            for w in ("approve", "resume", "cancel", "unseal", "holdout", "delete", "order", "trade")
        )
    for t in asyncio.run(mcp.list_tools()):
        assert t.annotations is not None and t.annotations.destructive_hint is False


def test_agent_definitions_use_only_existing_tools_and_no_shell() -> None:
    known = {f"mcp__candle-intelligence-ceo__{n}" for n in _names(mcp)} | {
        f"mcp__candle-intelligence-research__{n}" for n in _names(research_mcp.mcp)
    }
    files = sorted(AGENTS_DIR.glob("*.md"))
    assert {f.stem for f in files} >= {
        "data-scientist",
        "pattern-analyst",
        "strategy-architect",
        "validation-analyst",
    }
    for f in [*files, COMMAND]:
        tools = _tools_of(f)
        for t in tools:
            assert t in known or t == "Agent", f"{f.name}: unknown or disallowed tool {t}"
        assert "Bash" not in tools and "Write" not in tools and "Edit" not in tools


def test_separation_of_duties() -> None:
    by = {f.stem: set(_tools_of(f)) for f in AGENTS_DIR.glob("*.md")}
    r = "mcp__candle-intelligence-research__"
    assert f"{r}run_backtest" not in by["strategy-architect"]
    assert f"{r}propose_strategy" not in by["validation-analyst"]
    assert f"{r}run_backtest" not in by["pattern-analyst"]
    director = set(_tools_of(COMMAND))
    assert f"{r}run_backtest" not in director and f"{r}propose_strategy" not in director


def test_hand_ins_carry_the_agent(monkeypatch) -> None:
    sent = {}
    monkeypatch.setattr(ceo_mcp, "_call", lambda m, p, b=None: sent.update(method=m, path=p, body=b) or {})
    ceo_mcp.task_finish("t1", "validator", {"summary": "x"})
    assert sent["path"] == "/api/ceo/tasks/t1/finish" and sent["body"]["agent"] == "validator"
    ceo_mcp.submit_plan("m1", [], "note")
    assert sent["path"] == "/api/ceo/missions/m1/plan"


def test_wait_job_returns_when_done(monkeypatch) -> None:
    calls = iter(
        [{"job_id": "j", "status": "running"}, {"job_id": "j", "status": "done", "result": {"run_id": "r"}}]
    )
    monkeypatch.setattr(ceo_mcp, "_call", lambda *a, **k: next(calls))
    monkeypatch.setattr(ceo_mcp.time, "sleep", lambda s: None)
    assert ceo_mcp.wait_job("j", 30)["result"] == {"run_id": "r"}
