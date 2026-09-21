"""Strategy spec — the single language for strategies (MASTER_PROMPT §7).

The owner's form builder, the optimiser and the research engine all produce this
spec; the one backtester runs it. A spec is plain, versioned JSON, validated here
and identified by a content hash, so "the same strategy" always means the same
bytes.

Timing is fixed by the engine, not the spec: every condition is evaluated on the
features of an M5 bar at that bar's close (``available_at``), and an entry fills at
the open of the first M1 bar after it. A spec therefore cannot express look-ahead.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from candle_intel.features.registry import BY_NAME

SPEC_VERSION = "strategy-spec/1"

Op = Literal[">", ">=", "<", "<=", "==", "!=", "between", "in", "not_in"]
Side = Literal["long", "short"]
Scalar = float | int | str | bool

SESSIONS = ("asian", "london", "new_york", "london_ny_overlap", "off")
VOL_REGIMES = ("low", "mid", "high")

# Features a strategy may not condition on: identity / lineage, and the hygiene
# verdict itself (it is always enforced by the engine, never optional).
NOT_CONDITIONABLE = {"hyg_no_entry"}

_NUMERIC_UNITS = {"atr", "pts", "frac", "x", "bps", "bars", "ticks", "min", "h", "day", "sign"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Condition(_Strict):
    """``feature op value`` on the decision bar, e.g. ``close_loc > 0.7``."""

    feature: str
    op: Op
    value: Scalar | list[Scalar]

    @field_validator("feature")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in BY_NAME:
            raise ValueError(f"unknown feature {v!r}")
        if v in NOT_CONDITIONABLE:
            raise ValueError(f"{v} is enforced by the engine and cannot be used as a condition")
        return v

    @model_validator(mode="after")
    def _shape(self) -> Condition:
        spec = BY_NAME[self.feature]
        if self.op == "between":
            if not (isinstance(self.value, list) and len(self.value) == 2):
                raise ValueError("between needs [low, high]")
            lo, hi = self.value
            if not all(isinstance(x, int | float) and not isinstance(x, bool) for x in (lo, hi)) or lo > hi:
                raise ValueError("between needs two numbers, low <= high")
        elif self.op in ("in", "not_in"):
            if not (isinstance(self.value, list) and self.value):
                raise ValueError(f"{self.op} needs a non-empty list")
        elif isinstance(self.value, list):
            raise ValueError(f"{self.op} needs a single value")
        if self.op in (">", ">=", "<", "<=", "between") and spec.unit not in _NUMERIC_UNITS:
            raise ValueError(f"{self.feature} ({spec.unit}) is not numeric; use ==, !=, in or not_in")
        return self


class EntryRule(_Strict):
    """Enter ``side`` when **all** conditions hold on the decision bar."""

    side: Side
    conditions: Annotated[list[Condition], Field(min_length=1, max_length=12)]


class Filters(_Strict):
    """Extra gates on top of the always-on hygiene rule (blueprint §5.3)."""

    sessions: list[Literal["asian", "london", "new_york", "london_ny_overlap", "off"]] | None = None
    vol_regimes: list[Literal["low", "mid", "high"]] | None = None
    hours_utc: list[Annotated[int, Field(ge=0, le=23)]] | None = None
    weekdays: list[Annotated[int, Field(ge=1, le=7)]] | None = None  # ISO, 1 = Monday
    max_spread_rel: Annotated[float, Field(gt=0)] | None = None  # spread ÷ its ~5-day median


class Exit(_Strict):
    """Distances are multiples of the decision bar's ATR(14) (feature ``atr_pts``)."""

    stop_atr: Annotated[float, Field(gt=0, le=20)]
    target_atr: Annotated[float, Field(gt=0, le=50)] | None = None
    time_exit_bars: Annotated[int, Field(ge=1, le=2016)] | None = None  # M5 bars after entry
    trail_atr: Annotated[float, Field(gt=0, le=20)] | None = None  # trailing stop, updated at M5 closes
    flat_before_weekend: bool = True

    @model_validator(mode="after")
    def _has_an_exit(self) -> Exit:
        if self.target_atr is None and self.time_exit_bars is None and self.trail_atr is None:
            raise ValueError("a strategy needs a target, a time exit or a trailing stop besides the stop")
        return self


class Sizing(_Strict):
    """Fixed-fractional risk: each trade risks ``risk_pct`` of current equity at its stop.
    Results are always reported in R as well, which does not depend on sizing."""

    mode: Literal["fixed_fractional"] = "fixed_fractional"
    risk_pct: Annotated[float, Field(gt=0, le=5)] = 1.0
    initial_equity_usd: Annotated[float, Field(ge=100)] = 10_000.0


class Meta(_Strict):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    family: Annotated[str, Field(min_length=1, max_length=60)]
    hypothesis: str = ""
    preregistration_id: str | None = None
    notes: str = ""
    created_by: Literal["owner", "engine", "assistant"] = "owner"

    @field_validator("family")
    @classmethod
    def _slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_\-]*", v):
            raise ValueError("family: lowercase letters, digits, - and _ only")
        return v


class StrategySpec(_Strict):
    spec_version: Literal["strategy-spec/1"] = SPEC_VERSION
    meta: Meta
    entries: Annotated[list[EntryRule], Field(min_length=1, max_length=4)]
    filters: Filters = Filters()
    exit: Exit
    sizing: Sizing = Sizing()

    def rules(self) -> dict[str, Any]:
        """The part of the spec that decides trades — what the hash identifies.
        Name, notes and hypothesis text do not change the strategy."""
        d = self.model_dump(mode="json")
        return {k: d[k] for k in ("spec_version", "entries", "filters", "exit", "sizing")} | {
            "family": self.meta.family
        }

    @property
    def spec_hash(self) -> str:
        blob = json.dumps(self.rules(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def features_used(self) -> list[str]:
        names = {c.feature for e in self.entries for c in e.conditions}
        return sorted(names)


# ---------------------------------------------------------------- parameter paths


def get_path(d: Any, path: str) -> Any:
    """``exit.stop_atr`` / ``entries.0.conditions.1.value`` / ``...value.0`` (between)."""
    for part in path.split("."):
        d = d[int(part)] if isinstance(d, list) else d[part]
    return d


def with_params(spec: StrategySpec, params: dict[str, Any]) -> StrategySpec:
    """A copy of ``spec`` with parameter paths replaced, re-validated."""
    d = spec.model_dump(mode="json")
    for path, value in params.items():
        *head, last = path.split(".")
        parent = get_path(d, ".".join(head)) if head else d
        if isinstance(parent, list):
            parent[int(last)] = value
        else:
            if last not in parent:
                raise KeyError(f"unknown parameter path {path!r}")
            parent[last] = value
    return StrategySpec.model_validate(d)


def catalogue() -> dict[str, Any]:
    """What the builder UI needs: conditionable features, operators, filter choices."""
    from candle_intel.features.registry import FEATURES, GROUPS

    return {
        "spec_version": SPEC_VERSION,
        "groups": GROUPS,
        "features": [
            f.to_dict() | {"numeric": f.unit in _NUMERIC_UNITS}
            for f in FEATURES
            if f.name not in NOT_CONDITIONABLE
        ],
        "ops": list(Op.__args__),
        "sessions": list(SESSIONS),
        "vol_regimes": list(VOL_REGIMES),
        "always_on": "hyg_no_entry (rollover window, abnormal spread, first/last 3 bars of the week)",
    }
