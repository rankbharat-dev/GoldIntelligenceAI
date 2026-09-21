"""Read-only gateway to the local MetaTrader 5 terminal.

This is the single module in the repository allowed to ``import MetaTrader5``
(enforced by tests/leakage/test_mt5_boundary.py). It exposes only an allowlist of
market-data functions. Trading, order, position, deal-history and account
functions are unreachable through it by construction.

Timestamps: MT5 returns bar and tick times as epoch seconds on the *broker
server clock*, not UTC. This module never relabels them as UTC. Columns are
named ``ts_server``; conversion to UTC is a separate, audited step in
``candle_intel.data`` once the broker's offset history is established.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType, SimpleNamespace
from typing import Any

import MetaTrader5 as _mt5
import numpy as np
import polars as pl

from candle_intel.config import RESEARCH_TIMEFRAMES, Settings, get_settings

log = logging.getLogger(__name__)

_ALLOWED_FUNCTIONS = (
    "initialize",
    "shutdown",
    "last_error",
    "version",
    "terminal_info",
    "symbol_select",
    "symbol_info",
    "symbol_info_tick",
    "copy_rates_range",
    "copy_rates_from_pos",
    "copy_ticks_range",
)

# Read-only proxy. Code outside this module gets `api`, never the raw module.
api = SimpleNamespace(**{name: getattr(_mt5, name) for name in _ALLOWED_FUNCTIONS})

TIMEFRAMES = MappingProxyType(
    {tf: getattr(_mt5, f"TIMEFRAME_{tf}") for tf in RESEARCH_TIMEFRAMES}
)
COPY_TICKS_ALL = _mt5.COPY_TICKS_ALL

_ACCOUNT_MODES = {0: "demo", 1: "contest", 2: "real"}


class MT5Error(RuntimeError):
    pass


@dataclass(frozen=True)
class SessionInfo:
    """Connection facts that are safe to log and report. No account identifiers."""

    terminal_build: int
    terminal_company: str
    terminal_connected: bool
    terminal_algo_trading_enabled: bool
    account_mode: str  # demo / contest / real
    account_trading_permitted: bool  # False when logged in with the investor password
    broker_symbol: str
    server_offset_hours: float | None  # estimate; None when the market is closed


def _last_error() -> str:
    code, msg = api.last_error()
    return f"[{code}] {msg}"


def _account_facts() -> tuple[str, bool]:
    """Only the two fields needed for safety checks ever leave this function."""
    info = _mt5.account_info()
    if info is None:
        raise MT5Error(f"No account session in terminal: {_last_error()}")
    return _ACCOUNT_MODES.get(info.trade_mode, "unknown"), bool(info.trade_allowed)


def estimate_server_offset_hours(broker_symbol: str) -> float | None:
    """Estimate broker-server UTC offset from the latest tick.

    Valid only while the market is trading; returns None when the latest tick is
    stale (weekend, holiday) rather than guessing.
    """
    tick = api.symbol_info_tick(broker_symbol)
    if tick is None:
        return None
    diff = tick.time - time.time()
    offset = round(diff / 1800) / 2  # nearest half hour
    residual = abs(diff - offset * 3600)
    if not -12 <= offset <= 14 or residual > 300:
        return None
    return offset


def connect(settings: Settings | None = None) -> SessionInfo:
    s = settings or get_settings()
    kwargs: dict[str, Any] = {"timeout": s.mt5_timeout_ms}
    if s.mt5_terminal_path:
        kwargs["path"] = str(s.mt5_terminal_path)
    if s.mt5_login is not None:
        kwargs["login"] = s.mt5_login
        if s.mt5_password is not None:
            kwargs["password"] = s.mt5_password.get_secret_value()
        if s.mt5_server:
            kwargs["server"] = s.mt5_server

    if not api.initialize(**kwargs):
        raise MT5Error(f"MT5 initialize failed: {_last_error()}")

    if not api.symbol_select(s.mt5_broker_symbol, True):
        err = _last_error()
        api.shutdown()
        raise MT5Error(
            f"Symbol {s.mt5_broker_symbol!r} not available in Market Watch: {err}. "
            "Set CI_MT5_BROKER_SYMBOL to your broker's gold symbol."
        )

    term = api.terminal_info()
    mode, trading_permitted = _account_facts()
    # A freshly launched terminal serves a cached tick until the feed catches up.
    offset = None
    for _ in range(5):
        offset = estimate_server_offset_hours(s.mt5_broker_symbol)
        if offset is not None:
            break
        time.sleep(1)
    info = SessionInfo(
        terminal_build=int(api.version()[1]),
        terminal_company=str(term.company),
        terminal_connected=bool(term.connected),
        terminal_algo_trading_enabled=bool(term.trade_allowed),
        account_mode=mode,
        account_trading_permitted=trading_permitted,
        broker_symbol=s.mt5_broker_symbol,
        server_offset_hours=offset,
    )
    log.info("MT5 connected: %s", info)
    return info


def disconnect() -> None:
    api.shutdown()


@contextmanager
def session(settings: Settings | None = None) -> Iterator[SessionInfo]:
    info = connect(settings)
    try:
        yield info
    finally:
        disconnect()


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------

_RATE_SCHEMA = {
    "ts_server": pl.Datetime("us"),
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "tick_volume": pl.Int64,
    "spread_points": pl.Int32,
    "real_volume": pl.Int64,
}

_TICK_SCHEMA = {
    "ts_server": pl.Datetime("ms"),
    "bid": pl.Float64,
    "ask": pl.Float64,
    "flags": pl.UInt32,
}


def _require_timeframe(timeframe: str) -> int:
    try:
        return TIMEFRAMES[timeframe]
    except KeyError:
        raise ValueError(
            f"timeframe must be one of {RESEARCH_TIMEFRAMES}, got {timeframe!r}"
        ) from None


TIMEFRAME_MINUTES = MappingProxyType({"M1": 1, "M5": 5, "M15": 15, "H1": 60})


def mark_complete(df: pl.DataFrame, timeframe: str, settings: Settings | None = None) -> pl.DataFrame:
    """Add ``complete``: False for a bar still forming at the broker's latest tick.

    Compared on the broker's own clock, so no UTC-offset assumption is involved.
    """
    now = server_now(settings)
    bar_end = pl.col("ts_server") + pl.duration(minutes=TIMEFRAME_MINUTES[timeframe])
    return df.with_columns((bar_end <= now).alias("complete"))


def to_epoch_seconds(dt: datetime) -> int:
    """Encode a broker-server-clock wall time as the epoch value MT5 compares against.

    MT5 range bounds are compared directly with bar/tick ``time``, which is the
    server wall clock encoded as if it were UTC. So a bound must be the *server*
    wall time, encoded the same way.

    The MetaTrader5 package interprets a naive datetime in the machine's local
    timezone, which silently shifts every query by the local UTC offset (5.5 h on
    an IST machine). Encoding explicitly avoids that. Pass naive server-clock
    datetimes; aware datetimes are rejected because their meaning is ambiguous here.
    """
    if dt.tzinfo is not None:
        raise ValueError("MT5 range bounds are broker-server wall times; pass a naive datetime")
    return int(dt.replace(tzinfo=UTC).timestamp())


def server_now(settings: Settings | None = None) -> datetime:
    """Current time on the broker server clock (naive), from the latest tick."""
    s = settings or get_settings()
    tick = api.symbol_info_tick(s.mt5_broker_symbol)
    if tick is None:
        raise MT5Error(f"symbol_info_tick failed: {_last_error()}")
    return datetime.fromtimestamp(tick.time, tz=UTC).replace(tzinfo=None)


def max_bars() -> int:
    """Largest bar count one request may return (terminal 'Max bars in chart' - 1)."""
    return int(api.terminal_info().maxbars) - 1


def rates_to_frame(raw: np.ndarray | None) -> pl.DataFrame:
    if raw is None or len(raw) == 0:
        return pl.DataFrame(schema=_RATE_SCHEMA)
    return pl.DataFrame(
        {
            "ts_server": raw["time"].astype("int64") * 1_000_000,
            "open": raw["open"],
            "high": raw["high"],
            "low": raw["low"],
            "close": raw["close"],
            "tick_volume": raw["tick_volume"].astype("int64"),
            "spread_points": raw["spread"].astype("int32"),
            "real_volume": raw["real_volume"].astype("int64"),
        }
    ).cast(_RATE_SCHEMA)


def ticks_to_frame(raw: np.ndarray | None) -> pl.DataFrame:
    if raw is None or len(raw) == 0:
        return pl.DataFrame(schema=_TICK_SCHEMA)
    return pl.DataFrame(
        {
            "ts_server": raw["time_msc"].astype("int64"),
            "bid": raw["bid"],
            "ask": raw["ask"],
            "flags": raw["flags"].astype("uint32"),
        }
    ).cast(_TICK_SCHEMA)


def fetch_rates_range(
    timeframe: str, start: datetime, end: datetime, settings: Settings | None = None
) -> pl.DataFrame:
    s = settings or get_settings()
    raw = api.copy_rates_range(
        s.mt5_broker_symbol, _require_timeframe(timeframe), to_epoch_seconds(start), to_epoch_seconds(end)
    )
    if raw is None:
        raise MT5Error(f"copy_rates_range failed: {_last_error()}")
    return rates_to_frame(raw)


def fetch_rates_chunked(
    timeframe: str, start: datetime, end: datetime, settings: Settings | None = None
) -> pl.DataFrame:
    """Range fetch split into windows small enough to stay under the terminal's
    bar limit (a single over-limit request fails with 'Invalid params')."""
    minutes_per_chunk = max_bars() * TIMEFRAME_MINUTES[_tf_name(timeframe)] // 2
    step = timedelta(minutes=minutes_per_chunk)
    parts, cursor = [], start
    while cursor < end:
        upper = min(cursor + step, end)
        parts.append(fetch_rates_range(timeframe, cursor, upper, settings))
        cursor = upper
    if not parts:
        return rates_to_frame(None)
    return pl.concat(parts).unique("ts_server", keep="first").sort("ts_server")


def _tf_name(timeframe: str) -> str:
    _require_timeframe(timeframe)
    return timeframe


def fetch_rates_latest(timeframe: str, count: int, settings: Settings | None = None) -> pl.DataFrame:
    s = settings or get_settings()
    count = min(count, max_bars())
    raw = api.copy_rates_from_pos(s.mt5_broker_symbol, _require_timeframe(timeframe), 0, count)
    if raw is None:
        raise MT5Error(f"copy_rates_from_pos failed: {_last_error()}")
    return rates_to_frame(raw)


def fetch_ticks_range(
    start: datetime, end: datetime, settings: Settings | None = None
) -> pl.DataFrame:
    s = settings or get_settings()
    raw = api.copy_ticks_range(
        s.mt5_broker_symbol, to_epoch_seconds(start), to_epoch_seconds(end), COPY_TICKS_ALL
    )
    if raw is None:
        raise MT5Error(f"copy_ticks_range failed: {_last_error()}")
    return ticks_to_frame(raw)


_SPEC_FIELDS = (
    "name", "description", "currency_base", "currency_profit", "digits", "point",
    "trade_tick_size", "trade_tick_value", "trade_contract_size", "volume_min",
    "volume_max", "volume_step", "trade_stops_level", "trade_freeze_level",
    "swap_mode", "swap_long", "swap_short", "swap_rollover3days", "spread",
    "spread_float", "trade_calc_mode", "trade_mode",
)


def symbol_spec(settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    info = api.symbol_info(s.mt5_broker_symbol)
    if info is None:
        raise MT5Error(f"symbol_info failed: {_last_error()}")
    d = info._asdict()
    return {k: d[k] for k in _SPEC_FIELDS if k in d}


def latest_tick(settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    t = api.symbol_info_tick(s.mt5_broker_symbol)
    if t is None:
        raise MT5Error(f"symbol_info_tick failed: {_last_error()}")
    ts = datetime.fromtimestamp(t.time_msc / 1000, tz=UTC).replace(tzinfo=None)
    return {
        "ts_server": ts.isoformat(timespec="milliseconds"),
        "bid": t.bid,
        "ask": t.ask,
        "spread": round(t.ask - t.bid, 5),
    }
