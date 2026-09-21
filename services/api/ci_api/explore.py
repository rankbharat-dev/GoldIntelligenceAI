"""Phase 7 endpoints: structure overlays, Behaviour Explorer, pre-registered behaviours,
event studies and the Chart-Based Creator.

Numbers come from ``candle_intel.structure`` / ``candle_intel.research.events``; tier C
is never read here (distributions cover A∪B, studies A or B).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import polars as pl
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError

from candle_intel.features.registry import BY_NAME
from candle_intel.research import behaviours, events, studies
from candle_intel.strategy import drafts
from candle_intel.strategy.spec import _NUMERIC_UNITS, Condition
from candle_intel.structure import geometry

from . import research

router = APIRouter(prefix="/api")

WARMUP_BARS = geometry.LEVEL_LOOKBACK + 400  # enough history that the window equals the full-history result
MAX_WINDOW_BARS = 40_000


def _dt(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, UTC).replace(tzinfo=None)


# ---------------------------------------------------------------- structure overlays


@router.get("/structure")
def structure(
    start: Annotated[int, Query(description="UTC epoch s — first bar of the visible window")],
    end: Annotated[int, Query(description="UTC epoch s — end of the visible window")],
) -> dict[str, Any]:
    """Swings, current S/R levels, trendlines / channels and events (sweeps, breaks,
    retests, failures) for a window, computed on M5 with enough warm-up that every
    value equals the full-history computation (all structure rules are local)."""
    mk = research.get_market()
    if end <= start:
        raise HTTPException(422, "end must be after start")
    lo, hi = _dt(start), _dt(end)
    m5 = _m5_window(mk, lo, hi)
    if m5.is_empty():
        return {"swings": [], "levels": [], "lines": [], "events": [], "window_bars": 0}
    start_row = int(m5.select((pl.col("event_time") < lo).sum()).item())
    out = geometry.detect(m5, start_row=start_row)
    return out | {"window_bars": m5.height - start_row, "feature_set_id": mk.feature_set_id}


def _m5_window(mk, lo: datetime, hi: datetime) -> pl.DataFrame:
    path = mk.features_path.parent.parent.parent / "M5.parquet"
    atr = pl.scan_parquet(mk.features_path).select("event_time", "atr_pts")
    lf = (
        pl.scan_parquet(path)
        .select(pl.col("ts_utc").alias("event_time"), "open", "high", "low", "close")
        .filter(pl.col("event_time") < hi)
    )
    before = lf.filter(pl.col("event_time") < lo).tail(WARMUP_BARS)
    inside = lf.filter(pl.col("event_time") >= lo).head(MAX_WINDOW_BARS)
    df = pl.concat([before, inside]).join(atr, on="event_time", how="left").collect()
    return df.sort("event_time").with_columns(_atr=pl.col("atr_pts") * mk.point)


# ---------------------------------------------------------------- Behaviour Explorer


@router.get("/explore/features")
def explore_features() -> list[dict[str, Any]]:
    return [f.to_dict() | {"numeric": f.unit in _NUMERIC_UNITS} for f in BY_NAME.values()]


@router.get("/explore/distribution")
def explore_distribution(
    feature: str, by: Literal["none", "year", "session", "vol_regime", "tier"] = "none"
) -> dict[str, Any]:
    spec = BY_NAME.get(feature)
    if spec is None:
        raise HTTPException(404, f"unknown feature {feature!r}")
    mk = research.get_market()
    numeric = spec.unit in _NUMERIC_UNITS and spec.unit != "sign"
    out = events.distribution(mk, feature, None if by == "none" else by, numeric)
    return out | {"spec": spec.to_dict(), "tiers": "A∪B (C sealed)"}


class Barriers(BaseModel):
    target_atr: Annotated[float, Field(gt=0, le=20)] = 1.5
    stop_atr: Annotated[float, Field(gt=0, le=20)] = 1.0
    horizon_bars: Annotated[int, Field(ge=1, le=576)] = 24


class StudyBody(BaseModel):
    pattern_id: str | None = None
    name: str = "ad-hoc study"
    side: Literal["long", "short"] = "long"
    conditions: list[dict[str, Any]] = []
    barriers: Barriers = Barriers()
    tier: Literal["A", "B"] = "A"


class RegisterBody(BaseModel):
    slug: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_]{2,40}$")]
    name: Annotated[str, Field(min_length=3, max_length=120)]
    behaviour: str = "custom"
    side: Literal["long", "short"]
    conditions: Annotated[list[dict[str, Any]], Field(min_length=1, max_length=8)]
    hypothesis: Annotated[str, Field(min_length=10, max_length=600)]
    barriers: Barriers = Barriers()


def _check_conditions(conds: list[dict[str, Any]]) -> None:
    try:
        for c in conds:
            Condition.model_validate(c)
    except ValidationError as e:
        raise HTTPException(
            422,
            {
                "message": "invalid condition",
                "errors": [{"loc": ".".join(map(str, err["loc"])), "msg": err["msg"]} for err in e.errors()],
            },
        ) from e


@router.get("/behaviours")
def behaviour_list() -> dict[str, Any]:
    led = research.get_ledger()
    pats = behaviours.ensure_registered(led)
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for r in led.runs(limit=500):
        if r["kind"] != "study":
            continue
        pid = (r["summary"] or {}).get("pattern_id")
        if pid and (pid, r["tier"]) not in latest:
            latest[(pid, r["tier"])] = {"run_id": r["run_id"], "created_at": r["created_at"]} | r["summary"]
    screens = [r for r in led.runs(limit=500) if r["kind"] == "screen"]
    return {
        "groups": behaviours.GROUPS,
        "rule_version": behaviours.RULE_VERSION,
        "min_samples": behaviours.MIN_SAMPLES,
        "patterns": [p | {"latest": {t: latest.get((p["pattern_id"], t)) for t in ("A", "B")}} for p in pats],
        "screens": screens[:10],
    }


@router.post("/behaviours")
def behaviour_register(body: RegisterBody) -> dict[str, Any]:
    _check_conditions(body.conditions)
    return behaviours.register_custom(
        research.get_ledger(),
        body.slug,
        body.name,
        body.behaviour,
        body.side,
        body.conditions,
        body.hypothesis,
        body.barriers.model_dump(),
    )


@router.post("/jobs/study")
def job_study(body: StudyBody) -> dict[str, Any]:
    led, mk, runner = research.get_ledger(), research.get_market(), research.get_runner()
    if body.pattern_id is None:
        if not body.conditions:
            raise HTTPException(422, "give conditions or a registered pattern_id")
        _check_conditions(body.conditions)
        if body.tier != "A":
            raise HTTPException(
                422, "ad-hoc studies run on tier A; pre-register the behaviour to study tier B"
            )
    elif led.pattern(body.pattern_id) is None:
        raise HTTPException(404, f"unknown pattern {body.pattern_id}")
    defn = {"side": body.side, "conditions": body.conditions, "barriers": body.barriers.model_dump()}

    def work(p):
        try:
            doc = studies.run_study(defn, mk, led, body.tier, body.name, body.pattern_id, p)
        except events.StudyError as e:
            raise RuntimeError(str(e)) from e
        return {"run_id": doc["run_id"]}

    title = f"Study {body.pattern_id or body.name} · tier {body.tier}"
    return {"job_id": runner.submit("study", title, body.model_dump(), work)}


@router.post("/jobs/screen")
def job_screen(tier: Literal["A", "B"] = "A") -> dict[str, Any]:
    led, mk, runner = research.get_ledger(), research.get_market(), research.get_runner()
    job = runner.submit(
        "screen",
        f"Behaviour screen · tier {tier}",
        {"tier": tier},
        lambda p: {"run_id": studies.run_screen(mk, led, tier, p)["run_id"]},
    )
    return {"job_id": job}


# ---------------------------------------------------------------- Chart-Based Creator


class DraftBody(BaseModel):
    time: int  # UTC epoch s of the marked bar's open (any timeframe; mapped to its M5 bar)
    tf: Literal["M1", "M5", "M15", "H1"] = "M5"
    side: Literal["long", "short"] = "long"


@router.post("/strategy/draft-from-bar")
def draft_from_bar(body: DraftBody) -> dict[str, Any]:
    mk = research.get_market()
    t = _dt(body.time)
    minutes = {"M1": 1, "M5": 5, "M15": 15, "H1": 60}[body.tf]
    start = t.replace(minute=t.minute - t.minute % 5, second=0, microsecond=0)
    end = t + timedelta(minutes=minutes)
    src = pl.scan_parquet(mk.features_path) if mk.features_path.is_file() else mk._frame.lazy()
    df = (
        src.filter((pl.col("event_time") >= start) & (pl.col("event_time") < end))
        .sort("event_time")
        .tail(1)
        .collect()
    )
    if df.is_empty():
        raise HTTPException(404, "no M5 bar there")
    row = df.row(0, named=True)
    if row["available_at"] >= mk.split.c_start:
        raise HTTPException(403, "that bar is in the sealed holdout (tier C); mark a bar before it")
    out = drafts.suggest(row, body.side)
    return out | {
        "event_time": int(row["event_time"].replace(tzinfo=UTC).timestamp()),
        "available_at": int(row["available_at"].replace(tzinfo=UTC).timestamp()),
    }
