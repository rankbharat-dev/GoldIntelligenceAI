"""Metadata registration in PostgreSQL (schema: infra/postgres/init/001_schema.sql).

Parquet manifests are the source of truth for data; the database indexes them.
Registration is idempotent (re-running a build does not duplicate rows).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from candle_intel.config import get_settings

log = logging.getLogger(__name__)


def engine() -> Engine:
    return create_engine(get_settings().postgres_dsn.get_secret_value(), pool_pre_ping=True)


def register_dataset(conn, row: dict[str, Any]) -> None:
    conn.execute(
        text(
            """
            INSERT INTO ci.datasets (dataset_id, timeframe, broker, broker_server, broker_symbol,
                price_side, clock, first_ts_server, last_ts_server, row_count, parquet_path,
                sha256, parent_dataset_id, config_hash)
            VALUES (:dataset_id, :timeframe, :broker, :broker_server, :broker_symbol,
                :price_side, :clock, :first_ts_server, :last_ts_server, :row_count, :parquet_path,
                :sha256, :parent_dataset_id, :config_hash)
            ON CONFLICT (dataset_id) DO NOTHING
            """
        ),
        {
            "price_side": "bid",
            "clock": "broker_server",
            "parent_dataset_id": None,
            "config_hash": None,
            **row,
        },
    )


def register_quality_run(conn, dataset_id: str, report: dict[str, Any]) -> None:
    exists = conn.execute(
        text("SELECT 1 FROM ci.data_quality_runs WHERE dataset_id = :d"), {"d": dataset_id}
    ).first()
    if exists:
        return
    window = report["coverage"]["research_window_utc"]
    conn.execute(
        text(
            """
            INSERT INTO ci.data_quality_runs (dataset_id, passed, findings, research_window_start,
                research_window_end, rollover_minute_server)
            VALUES (:d, :passed, CAST(:findings AS JSONB), :ws, :we, :roll)
            """
        ),
        {
            "d": dataset_id,
            "passed": report["passed"],
            "findings": json.dumps(report, default=str),
            "ws": window[0],
            "we": window[1],
            "roll": report["daily_break_ny"]["typical_start"],
        },
    )


def register_symbol_spec(conn, broker: str, broker_symbol: str, spec: dict[str, Any]) -> None:
    conn.execute(
        text(
            "INSERT INTO ci.symbol_specs (broker, broker_symbol, spec) VALUES (:b, :s, CAST(:spec AS JSONB))"
        ),
        {"b": broker, "s": broker_symbol, "spec": json.dumps(spec, default=str)},
    )
