"""Chronological A / B / C split (blueprint §9.1) — frozen once, never moved.

The boundaries are computed the first time from the research window
(A ≈ 60 %, B ≈ 20 %, C ≈ 20 %, cut at UTC midnight) and written to
``storage/research/split.json``. Later dataset builds reuse them unchanged: data
that arrives after the freeze is new, never-seen data and extends tier C. Moving a
boundary would let past holdout data leak into development, so there is no API
for it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

Tier = Literal["A", "B", "C", "AB"]  # AB = development + validation, continuous
SPLIT_VERSION = "split/1"
SHARES = (0.6, 0.2, 0.2)


@dataclass(frozen=True)
class Split:
    a_start: datetime
    b_start: datetime
    c_start: datetime
    frozen_utc: str = ""
    version: str = SPLIT_VERSION

    def bounds(self, tier: Tier) -> tuple[datetime, datetime | None]:
        """[start, end) of a tier on decision time; C is open-ended."""
        return {
            "A": (self.a_start, self.b_start),
            "B": (self.b_start, self.c_start),
            "C": (self.c_start, None),
            "AB": (self.a_start, self.c_start),
        }[tier]

    def tier_of(self, t: datetime) -> Tier | None:
        if t < self.a_start:
            return None
        return "A" if t < self.b_start else "B" if t < self.c_start else "C"

    def to_dict(self) -> dict[str, str]:
        return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, d: dict[str, str]) -> Split:
        return cls(
            datetime.fromisoformat(d["a_start"]),
            datetime.fromisoformat(d["b_start"]),
            datetime.fromisoformat(d["c_start"]),
            d.get("frozen_utc", ""),
            d.get("version", SPLIT_VERSION),
        )


def compute(research_start: datetime, research_end: datetime) -> Split:
    span = research_end - research_start

    def cut(share: float) -> datetime:
        t = research_start + span * share
        return t.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)  # next UTC midnight

    return Split(
        research_start,
        cut(SHARES[0]),
        cut(SHARES[0] + SHARES[1]),
        frozen_utc=datetime.now(UTC).isoformat(),
    )


def load_or_freeze(path: Path, research_start: datetime, research_end: datetime) -> Split:
    if path.exists():
        return Split.from_dict(json.loads(path.read_text(encoding="utf-8")))
    split = compute(research_start, research_end)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(split.to_dict(), indent=2), encoding="utf-8")
    path.chmod(0o444)
    return split
