"""Feature access wrapper — the ``available_at`` rule enforced in code (blueprint §7.1).

Anything that makes a decision at time ``T`` (a strategy, the backtester, the
research engine) reads features through :class:`FeatureStore`, which only ever
returns rows with ``available_at <= T``. Asking for a bar that is not yet known
raises :class:`LookAheadError` instead of silently returning it.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

FEATURES_FILE = "features_M5.parquet"
MANIFEST_FILE = "feature_set.json"


class LookAheadError(LookupError):
    """A row was requested before it was available."""


class FeatureStore:
    def __init__(self, frame: pl.DataFrame) -> None:
        self._f = frame.sort("available_at")

    @classmethod
    def open(cls, feature_set_dir: Path, columns: list[str] | None = None) -> FeatureStore:
        cols = None if columns is None else ["event_time", "available_at", *columns]
        return cls(pl.read_parquet(feature_set_dir / FEATURES_FILE, columns=cols))

    @property
    def columns(self) -> list[str]:
        return self._f.columns

    def as_of(self, decision_time: datetime, start: datetime | None = None) -> pl.DataFrame:
        """Every row known at ``decision_time`` (optionally from ``start`` on)."""
        f = self._f.filter(pl.col("available_at") <= decision_time)
        return f if start is None else f.filter(pl.col("event_time") >= start)

    def latest(self, decision_time: datetime) -> dict[str, Any] | None:
        """The most recent row known at ``decision_time``."""
        f = self.as_of(decision_time)
        return f.row(-1, named=True) if f.height else None

    def bar(self, event_time: datetime, decision_time: datetime) -> dict[str, Any]:
        """The row of one bar, only if it is known at ``decision_time``."""
        f = self._f.filter(pl.col("event_time") == event_time)
        if f.is_empty():
            raise KeyError(f"no M5 bar at {event_time}")
        row = f.row(0, named=True)
        if row["available_at"] > decision_time:
            raise LookAheadError(
                f"bar {event_time} is available at {row['available_at']}, after decision time {decision_time}"
            )
        return row
