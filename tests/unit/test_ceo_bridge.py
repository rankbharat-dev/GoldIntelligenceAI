"""The optional headless bridge: tool permissions come from the agent files, runs are
claimed once, usage is parsed from Claude Code's JSON, and pause / cancel stops the run.
Claude Code itself is replaced by a small fake script — no real model is called."""

from __future__ import annotations

import json
import sys
from datetime import timedelta

import pytest
from ci_api import ceo_bridge

from candle_intel.ceo.store import CeoError, CeoStore, _now
from candle_intel.research.ledger import Ledger

FAKE_OK = """
import json, sys
prompt = sys.stdin.read()
assert "Research Director" in prompt and "MISSION_ID" not in prompt
print(json.dumps({"type": "result", "is_error": False, "num_turns": 7, "total_cost_usd": 0.42,
                  "duration_ms": 1500, "usage": {"input_tokens": 100, "cache_read_input_tokens": 900,
                  "output_tokens": 50}, "result": "done"}))
"""
FAKE_SLOW = "import sys, time\nsys.stdin.read()\ntime.sleep(60)\n"


def test_allowed_tools_are_mcp_only() -> None:
    tools = ceo_bridge.allowed_tools()
    assert "Agent" in tools
    assert all(t == "Agent" or t.startswith("mcp__candle-intelligence-") for t in tools)
    assert "mcp__candle-intelligence-research__run_backtest" in tools  # the validator's
    cmd = ceo_bridge.build_command("claude")
    assert cmd[:2] == ["claude", "-p"] and "--strict-mcp-config" in cmd
    assert "m_123" in ceo_bridge.director_prompt("m_123")


def test_parse_usage() -> None:
    out = 'noise\n{"total_cost_usd": 1.5, "num_turns": 3, "usage": {"input_tokens": 10, "output_tokens": 2}}'
    assert ceo_bridge.parse_usage(out) == {
        "input_tokens": 10,
        "output_tokens": 2,
        "cost_usd": 1.5,
        "turns": 3,
        "duration_s": 0.0,
    }
    assert ceo_bridge.parse_usage("not json") == {}


def _fake(tmp_path, monkeypatch, code: str):
    f = tmp_path / "fake_claude.py"
    f.write_text(code, encoding="utf-8")
    monkeypatch.setattr(ceo_bridge, "build_command", lambda cli: [sys.executable, str(f)])


def test_run_one_reports_usage(tmp_path, monkeypatch) -> None:
    _fake(tmp_path, monkeypatch, FAKE_OK)
    monkeypatch.setattr(ceo_bridge, "_mission_status", lambda mid: "running")
    res = ceo_bridge.run_one({"run_id": "cr_1", "mission_id": "m_1"}, "x", 1, lambda: None)
    assert res["status"] == "done" and res["exit_code"] == 0
    assert res["usage"]["input_tokens"] == 1000 and res["usage"]["cost_usd"] == 0.42


def test_cancel_stops_the_run(tmp_path, monkeypatch) -> None:
    _fake(tmp_path, monkeypatch, FAKE_SLOW)
    monkeypatch.setattr(ceo_bridge, "WATCH_S", 0.5)
    monkeypatch.setattr(ceo_bridge, "_mission_status", lambda mid: "cancelled")
    res = ceo_bridge.run_one({"run_id": "cr_2", "mission_id": "m_2"}, "x", 1, lambda: None)
    assert res["status"] == "cancelled"


def test_store_run_lifecycle() -> None:
    s = CeoStore(Ledger.from_url("sqlite://"))
    mid = s.create_mission("Bridge lifecycle test")["mission_id"]
    assert s.bridge_status()["alive"] is False
    s.heartbeat({"cli": "claude"})
    assert s.bridge_status()["alive"] is True
    assert s.bridge_status(_now() + timedelta(minutes=5))["alive"] is False
    run = s.request_run(mid)
    with pytest.raises(CeoError, match="already"):
        s.request_run(mid)
    got = s.claim_run()
    assert got["run_id"] == run["run_id"] and s.claim_run() is None
    s.finish_run(
        run["run_id"], "done", 0, {"input_tokens": 1000, "output_tokens": 50, "cost_usd": 0.4, "turns": 7}
    )
    with pytest.raises(CeoError):
        s.finish_run(run["run_id"], "failed", 1, None)
    u = s.mission(mid)["usage"]
    assert u["bridge_runs"] == 1 and u["input_tokens"] == 1000 and u["cost_usd"] == 0.4
    s.request_run(mid)
    s.cancel(mid)
    assert [r["status"] for r in s.runs(mid)] == ["cancelled", "done"]
    assert json.loads(json.dumps(s.mission(mid)["usage"]))  # serialisable
