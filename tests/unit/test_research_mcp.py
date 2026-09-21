"""The assistant's research tool surface (no-API mode) is part of the guardrails: pin it."""

import asyncio

from ci_api import research_mcp
from ci_api.research_mcp import mcp

EXPECTED = {
    "research_status",
    "feature_catalogue",
    "behaviour_library",
    "propose_strategy",
    "run_backtest",
    "run_event_study",
    "propose_search",
    "job_status",
    "get_result",
    "search_status",
    "list_candidates",
}


def _tools():
    return asyncio.run(mcp.list_tools())


def test_tool_set_is_pinned() -> None:
    assert {t.name for t in _tools()} == EXPECTED


def test_no_guardrail_bypass_tools() -> None:
    for t in _tools():
        assert not any(
            w in t.name for w in ("unseal", "holdout", "approve", "resume", "delete", "order", "trade")
        )
        assert t.annotations is not None and t.annotations.destructive_hint is False


def test_backtests_cannot_target_tier_c() -> None:
    bt = next(t for t in _tools() if t.name == "run_backtest")
    assert bt.input_schema["properties"]["tier"]["enum"] == ["A", "B", "AB"]


def test_tier_c_results_are_withheld(monkeypatch) -> None:
    monkeypatch.setattr(research_mcp, "_call", lambda *a, **k: {"run_id": "x", "tier": "C", "results": {}})
    assert research_mcp.get_result("x") == {
        "sealed": True,
        "detail": "tier C (holdout) results are not available to the assistant",
    }


def test_searches_are_always_proposals(monkeypatch) -> None:
    sent = {}
    monkeypatch.setattr(research_mcp, "_call", lambda m, p, b=None: sent.update(path=p, body=b) or {})
    research_mcp.propose_search({"name": "x"})
    assert sent["path"] == "/api/searches" and sent["body"]["mode"] == "approve"
    research_mcp.propose_strategy({"meta": {"name": "a", "family": "b", "created_by": "owner"}})
    assert (
        sent["path"] == "/api/strategy/preview" and sent["body"]["spec"]["meta"]["created_by"] == "assistant"
    )
