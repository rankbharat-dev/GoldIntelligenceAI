"""Candle Intelligence — read-only, XAUUSD-only MT5 MCP server.

Design constraints (see docs/reviews/mt5-mcp-security-review.md):

* No tool accepts a symbol. The instrument is fixed by configuration and validated
  to be spot gold, so requesting another market is impossible, not merely refused.
* No code-execution tool. Every tool is a fixed, typed query.
* No trading, order, position, deal-history or account tool. The MT5 layer
  underneath (candle_intel.ingest.mt5_session) does not expose those functions.
* No credentials in any response. Status reports account *mode* only.
* Output is capped. Bulk history belongs in the Parquet ingestion pipeline,
  not in an LLM context window.
"""

from __future__ import annotations

import logging
import sys
import threading
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

import polars as pl
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from candle_intel.config import CANONICAL_SYMBOL, get_settings
from candle_intel.ingest import mt5_session

log = logging.getLogger("ci_mt5_mcp")

Timeframe = Literal["M1", "M5", "M15", "H1"]

READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)

INSTRUCTIONS = f"""\
Read-only market data for {CANONICAL_SYMBOL} (spot gold vs USD) from the local MetaTrader 5
terminal. This server cannot trade, cannot see positions or account details, and serves
no other instrument. All times - returned AND requested - are wall times on the BROKER
SERVER CLOCK (ts_server), not UTC; xauusd_status reports the server's current UTC offset
estimate and server time. Outputs are capped; for research-scale history use the Parquet
datasets instead."""

mcp = MCPServer(name="candle-intelligence-mt5", instructions=INSTRUCTIONS, version="0.1.0")

_lock = threading.Lock()  # the MetaTrader5 package is not thread-safe
_session: mt5_session.SessionInfo | None = None


def _ensure_session() -> mt5_session.SessionInfo:
    global _session
    if _session is None:
        _session = mt5_session.connect()
    return _session


def _parse_server_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is not None:
        raise ValueError("Pass broker-server wall time without a UTC offset, e.g. 2026-09-01T10:00")
    return dt


def _frame_payload(df: pl.DataFrame, cap: int) -> dict[str, Any]:
    truncated = df.height > cap
    if truncated:
        df = df.tail(cap)
    rows = df.with_columns(pl.col("ts_server").dt.to_string("%Y-%m-%dT%H:%M:%S%.3f")).to_dicts()
    return {"symbol": CANONICAL_SYMBOL, "count": len(rows), "truncated": truncated, "rows": rows}


@mcp.tool(annotations=READ_ONLY)
def xauusd_status() -> dict[str, Any]:
    """Connection health and safety posture of the MT5 link.

    Reports whether the terminal is connected, whether the account is demo or real,
    whether the session permits trading (False under an investor password) and whether
    the terminal's Algo Trading switch is on. Never returns account identifiers.
    """
    with _lock:
        info = _ensure_session()
        offset = mt5_session.estimate_server_offset_hours(info.broker_symbol)
    return {
        "symbol": CANONICAL_SYMBOL,
        "broker_symbol": info.broker_symbol,
        "terminal_build": info.terminal_build,
        "broker": info.broker_company,
        "broker_server": info.broker_server,
        "terminal_connected": info.terminal_connected,
        "account_mode": info.account_mode,
        "account_trading_permitted": info.account_trading_permitted,
        "terminal_algo_trading_enabled": info.terminal_algo_trading_enabled,
        "server_offset_hours_estimate": offset,
        "server_time": mt5_session.server_now().isoformat(),
        "server": "read-only; no trading tools exist",
    }


@mcp.tool(annotations=READ_ONLY)
def xauusd_symbol_info() -> dict[str, Any]:
    """Contract specification for XAUUSD: digits, point, tick size/value, contract size,
    volume limits, stop/freeze levels, swap settings and current spread."""
    with _lock:
        _ensure_session()
        return {"symbol": CANONICAL_SYMBOL, "spec": mt5_session.symbol_spec()}


@mcp.tool(annotations=READ_ONLY)
def xauusd_latest_price() -> dict[str, Any]:
    """Latest XAUUSD bid, ask and spread (in price units) with its server-clock timestamp."""
    with _lock:
        _ensure_session()
        return {"symbol": CANONICAL_SYMBOL, **mt5_session.latest_tick()}


@mcp.tool(annotations=READ_ONLY)
def xauusd_rates(
    timeframe: Timeframe = "M5",
    count: Annotated[int, Field(ge=1, description="Most recent N bars (ignored if start given)")] = 200,
    start: Annotated[str | None, Field(description="Server-clock ISO datetime. Range start.")] = None,
    end: Annotated[str | None, Field(description="Server-clock ISO datetime; default now.")] = None,
) -> dict[str, Any]:
    """Historical XAUUSD OHLCV candles for M1, M5, M15 or H1.

    Either the most recent `count` bars, or bars between `start` and `end`. Prices are
    bid. `spread_points` is the broker's per-bar spread snapshot in points. `complete` is
    False for the bar still forming. Results are capped (see `truncated`); when capped,
    the most recent bars are kept.
    """
    cap = get_settings().mcp_max_bars
    with _lock:
        _ensure_session()
        if start is None:
            df = mt5_session.fetch_rates_latest(timeframe, min(count, cap))
        else:
            start_dt = _parse_server_time(start)
            end_dt = _parse_server_time(end) if end else mt5_session.server_now()
            span_bars = (end_dt - start_dt).total_seconds() / 60 / mt5_session.TIMEFRAME_MINUTES[timeframe]
            if span_bars > cap * 2:
                raise ValueError(
                    f"Window spans ~{int(span_bars)} {timeframe} bars; the MCP limit is {cap}. "
                    "Narrow the window or use the Parquet datasets for bulk history."
                )
            df = mt5_session.fetch_rates_chunked(timeframe, start_dt, end_dt)
        df = mt5_session.mark_complete(df, timeframe)
    payload = _frame_payload(df, cap)
    payload["timeframe"] = timeframe
    return payload


@mcp.tool(annotations=READ_ONLY)
def xauusd_ticks(
    start: Annotated[str, Field(description="Server-clock ISO datetime")],
    end: Annotated[str | None, Field(description="Server-clock ISO datetime; default start + 5 min")] = None,
) -> dict[str, Any]:
    """Raw XAUUSD bid/ask ticks in a time window. Capped; keep windows short."""
    start_dt = _parse_server_time(start)
    end_dt = _parse_server_time(end) if end else start_dt + timedelta(minutes=5)
    if end_dt - start_dt > timedelta(hours=6):
        raise ValueError("Tick windows are limited to 6 hours over MCP.")
    with _lock:
        _ensure_session()
        df = mt5_session.fetch_ticks_range(start_dt, end_dt)
    return _frame_payload(df, get_settings().mcp_max_ticks)


@mcp.tool(annotations=READ_ONLY)
def xauusd_spread_stats(
    minutes: Annotated[int, Field(ge=1, le=1440, description="Look-back window in minutes")] = 60,
) -> dict[str, Any]:
    """Distribution of the real bid/ask spread over the last N minutes of ticks:
    tick count and p25 / p50 / p90 / p99 / max spread in price units."""
    with _lock:
        info = _ensure_session()
        end_dt = mt5_session.server_now() + timedelta(seconds=1)
        df = mt5_session.fetch_ticks_range(end_dt - timedelta(minutes=minutes), end_dt)
    if df.is_empty():
        return {"symbol": CANONICAL_SYMBOL, "ticks": 0, "note": "no ticks (market closed?)"}
    last = df["ts_server"].max()
    spread = (df["ask"] - df["bid"]).round(5)
    return {
        "symbol": CANONICAL_SYMBOL,
        "broker_symbol": info.broker_symbol,
        "window_minutes": minutes,
        "window_end_ts_server": str(last),
        "ticks": df.height,
        "spread_p25": spread.quantile(0.25),
        "spread_p50": spread.quantile(0.50),
        "spread_p90": spread.quantile(0.90),
        "spread_p99": spread.quantile(0.99),
        "spread_max": spread.max(),
    }


def main() -> None:
    # stdout is the MCP transport; logs must go to stderr.
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    try:
        mcp.run("stdio")
    finally:
        if _session is not None:
            mt5_session.disconnect()


if __name__ == "__main__":
    main()
