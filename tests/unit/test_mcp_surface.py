"""The MCP tool surface is part of the security boundary; pin it exactly."""

import asyncio

from ci_mt5_mcp.server import mcp

EXPECTED_TOOLS = {
    "xauusd_status",
    "xauusd_symbol_info",
    "xauusd_latest_price",
    "xauusd_rates",
    "xauusd_ticks",
    "xauusd_spread_stats",
}


def _tools():
    return asyncio.run(mcp.list_tools())


def test_tool_set_is_exactly_the_allowlist() -> None:
    assert {t.name for t in _tools()} == EXPECTED_TOOLS


def test_no_tool_accepts_a_symbol() -> None:
    for t in _tools():
        props = (t.input_schema or {}).get("properties", {})
        assert not any("symbol" in p.lower() for p in props), f"{t.name} takes a symbol: {props}"


def test_every_tool_is_annotated_read_only() -> None:
    for t in _tools():
        assert t.annotations is not None, t.name
        assert t.annotations.read_only_hint is True, t.name
        assert t.annotations.destructive_hint is False, t.name


def test_rates_timeframes_are_research_timeframes_only() -> None:
    rates = next(t for t in _tools() if t.name == "xauusd_rates")
    schema = rates.input_schema["properties"]["timeframe"]
    assert set(schema["enum"]) == {"M1", "M5", "M15", "H1"}
