"""Bulk XAUUSD ingestion into an immutable, versioned raw dataset.

Layout (one directory per ingestion run = one raw dataset version):

    storage/raw/xauusd/<raw_version>/
        manifest.json                 broker, spec, chunks (rows + sha256), windows
        m1/2026-06.parquet ...        closed M1 bars, broker-server clock, bid
        ticks/2026-03-02.parquet ...  bid/ask ticks (optional)
        reference/M5.parquet ...      broker-native M5/M15/H1 over the M1 window,
                                      used to verify our own aggregation

Everything is on the broker-server clock (``ts_server``). Clock conversion,
validation and aggregation happen downstream in ``candle_intel.data``, which
reads these files and never talks to MT5.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from candle_intel.config import CANONICAL_SYMBOL, get_settings
from candle_intel.ingest import mt5_session

log = logging.getLogger(__name__)

REFERENCE_TIMEFRAMES = ("M5", "M15", "H1")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_readonly(df: pl.DataFrame, path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path, compression="zstd", statistics=True)
    path.chmod(0o444)
    return {"file": path.name, "rows": df.height, "sha256": _sha256(path)}


def _month_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    windows, cursor = [], datetime(start.year, start.month, 1)
    while cursor < end:
        nxt = datetime(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
        windows.append((max(cursor, start), min(nxt, end)))
        cursor = nxt
    return windows


def _fetch_window(tf: str, lo: datetime, hi: datetime, retries: int = 3) -> pl.DataFrame:
    """Fetch [lo, hi) and keep only bars truly inside it.

    MT5 may answer a window it has no data for with one stale bar from elsewhere,
    and may still be downloading history on the first request, so an empty result
    is retried before it is accepted.
    """
    df = pl.DataFrame()
    for attempt in range(retries):
        df = mt5_session.fetch_rates_chunked(tf, lo, hi - timedelta(seconds=1))
        df = df.filter((pl.col("ts_server") >= lo) & (pl.col("ts_server") < hi))
        if df.height:
            return df
        time.sleep(2 * (attempt + 1))
    return df


def earliest_m1(search_from: datetime) -> datetime | None:
    """Earliest M1 bar the terminal will serve, found by walking months forward."""
    cursor = datetime(search_from.year, search_from.month, 1)
    now = mt5_session.server_now()
    while cursor < now:
        nxt = cursor + timedelta(days=32)
        nxt = datetime(nxt.year, nxt.month, 1)
        df = mt5_session.fetch_rates_range("M1", cursor, nxt - timedelta(seconds=1))
        df = df.filter((pl.col("ts_server") >= cursor) & (pl.col("ts_server") < nxt))
        if df.height > 1000:
            return df["ts_server"].min()
        cursor = nxt
    return None


def ingest(
    since: datetime | None = None,
    with_ticks: bool = False,
    tick_days: int | None = None,
) -> Path:
    """Create a new raw dataset version. Returns its directory."""
    s = get_settings()
    started = datetime.now(UTC)
    with mt5_session.session() as info:
        server_now = mt5_session.server_now()
        start = since or earliest_m1(datetime(2000, 1, 1))
        if start is None:
            raise mt5_session.MT5Error("Terminal serves no M1 history for this symbol.")
        # Stop at the last fully closed minute; the forming bar never enters raw storage.
        end = server_now.replace(second=0, microsecond=0)

        version = f"xauusd_{info.broker_server.lower().replace(' ', '_')}_{started:%Y%m%dT%H%M%SZ}"
        root = s.storage_root / "raw" / "xauusd" / version
        log.info("raw dataset %s: M1 %s -> %s", version, start, end)

        m1_chunks, empty_months = [], []
        for lo, hi in _month_windows(start, end):
            df = _fetch_window("M1", lo, hi)
            if df.is_empty():
                empty_months.append(f"{lo:%Y-%m}")
                continue
            m1_chunks.append(
                {"month": f"{lo:%Y-%m}", **_write_readonly(df, root / "m1" / f"{lo:%Y-%m}.parquet")}
            )
            log.info("M1 %s: %d bars", f"{lo:%Y-%m}", df.height)

        first_m1 = min(
            (pl.read_parquet(root / "m1" / c["file"])["ts_server"].min() for c in m1_chunks),
            default=start,
        )
        reference = {}
        for tf in REFERENCE_TIMEFRAMES:
            df = mt5_session.fetch_rates_chunked(tf, first_m1, end)
            df = mt5_session.mark_complete(df, tf).filter(pl.col("complete")).drop("complete")
            reference[tf] = _write_readonly(df, root / "reference" / f"{tf}.parquet")

        tick_chunks: list[dict[str, Any]] = []
        if with_ticks:
            tick_start = (end - timedelta(days=tick_days)) if tick_days else first_m1
            day = datetime(tick_start.year, tick_start.month, tick_start.day)
            while day < end:
                nxt = day + timedelta(days=1)
                if day.weekday() != 5:  # Saturday has no gold ticks
                    t = mt5_session.fetch_ticks_range(day, min(nxt, end))
                    t = t.filter((pl.col("ts_server") >= day) & (pl.col("ts_server") < nxt))
                    if t.height:
                        tick_chunks.append(
                            {
                                "day": f"{day:%Y-%m-%d}",
                                **_write_readonly(t, root / "ticks" / f"{day:%Y-%m-%d}.parquet"),
                            }
                        )
                day = nxt
            log.info("ticks: %d days", len(tick_chunks))

        manifest = {
            "raw_version": version,
            "symbol": CANONICAL_SYMBOL,
            "session": asdict(info),
            "price_side": "bid",
            "clock": "broker_server",
            "m1_window_ts_server": [str(start), str(end)],
            "m1_chunks": m1_chunks,
            "m1_empty_months": empty_months,
            "reference": reference,
            "tick_chunks": tick_chunks,
            "symbol_spec": mt5_session.symbol_spec(),
            "terminal_max_bars": mt5_session.max_bars() + 1,
            "created_utc": started.isoformat(),
            "finished_utc": datetime.now(UTC).isoformat(),
        }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return root
