"""End-to-end MCP test over real stdio against a running, logged-in MT5 terminal.

Run explicitly:  pytest -m mt5 tests/integration
"""

import asyncio
import json
import sys

import pytest
from mcp import Client, StdioServerParameters

pytestmark = pytest.mark.mt5

SERVER = StdioServerParameters(command=sys.executable, args=["-m", "ci_mt5_mcp.server"])


def _payload(result) -> dict:
    if result.structured_content:
        return result.structured_content
    return json.loads(result.content[0].text)


async def _run() -> tuple[dict, dict]:
    async with Client(SERVER, read_timeout_seconds=120) as client:
        status = _payload(await client.call_tool("xauusd_status", {}))
        rates = _payload(await client.call_tool("xauusd_rates", {"timeframe": "M5", "count": 500}))
    return status, rates


def test_range_query_ending_now_reaches_latest_bar() -> None:
    """Regression: naive datetimes were read as local time, dropping the last N hours."""
    from datetime import timedelta

    from candle_intel.ingest import mt5_session

    with mt5_session.session():
        latest = mt5_session.fetch_rates_latest("M5", 1)["ts_server"].max()
        now = mt5_session.server_now()
        ranged = mt5_session.fetch_rates_range("M5", now - timedelta(hours=6), now)
        chunked = mt5_session.fetch_rates_chunked("M1", now - timedelta(days=120), now)
    assert ranged["ts_server"].max() == latest
    # 120 days of M1 exceeds one request's bar limit; chunking must still return it all.
    assert chunked["ts_server"].is_unique().all()
    assert chunked["ts_server"].is_sorted()


def test_status_and_m5_candles_over_stdio() -> None:
    status, rates = asyncio.run(_run())
    assert status["terminal_connected"] is True
    assert status["account_mode"] == "demo"
    assert rates["timeframe"] == "M5"
    assert rates["count"] > 0
    assert all(r["complete"] for r in rates["rows"][:-1])
    row = rates["rows"][-2]
    assert row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"]
