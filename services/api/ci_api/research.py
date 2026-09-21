"""Research endpoints: strategy specs, backtests, optimisation, validation, holdout, jobs.

Numbers only ever come from the Python engine (candle_intel.backtest / research);
this module validates requests, starts jobs and serves stored results. Tier C stays
sealed except through ``POST /api/holdout/unseal`` (one logged access per family).
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError

from candle_intel.backtest import market
from candle_intel.research import checklist, optimize, runs, validate
from candle_intel.research.jobs import JobRunner
from candle_intel.research.ledger import HoldoutError, Ledger, default_ledger
from candle_intel.strategy import signals as sig
from candle_intel.strategy.spec import StrategySpec, catalogue

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------- dependencies (monkeypatched in tests)


def get_ledger() -> Ledger:
    try:
        return default_ledger()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            503, f"Research ledger unavailable (is PostgreSQL running? docker compose up -d): {e}"
        ) from e


def get_market() -> market.Market:
    try:
        return market.load(market.latest_dataset_dir())
    except FileNotFoundError as e:
        raise HTTPException(404, f"Data not built: {e}. Run ci-data, ci-costs and ci-features build.") from e


@lru_cache(maxsize=1)
def _runner_for(ledger_id: int) -> JobRunner:
    return JobRunner(get_ledger())


def get_runner() -> JobRunner:
    return _runner_for(id(get_ledger()))


def parse_spec(raw: dict[str, Any]) -> StrategySpec:
    try:
        return StrategySpec.model_validate(raw)
    except ValidationError as e:
        raise HTTPException(
            422,
            {
                "message": "invalid strategy spec",
                "errors": [{"loc": ".".join(map(str, err["loc"])), "msg": err["msg"]} for err in e.errors()],
            },
        ) from e


def _epoch(t: datetime) -> int:
    return int(t.replace(tzinfo=UTC).timestamp())


# ---------------------------------------------------------------- specs


@router.get("/strategy/catalogue")
def strategy_catalogue() -> dict[str, Any]:
    return catalogue()


@router.post("/strategy/validate")
def strategy_validate(spec: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
    s = parse_spec(spec)
    return {"ok": True, "spec_hash": s.spec_hash, "features_used": s.features_used()}


class SaveBody(BaseModel):
    spec: dict[str, Any]
    parent_hash: str | None = None


@router.post("/strategies")
def strategy_save(body: SaveBody) -> dict[str, Any]:
    s = parse_spec(body.spec)
    runs.save_spec(s, get_ledger(), body.parent_hash)
    return {"spec_hash": s.spec_hash}


@router.get("/strategies")
def strategy_list() -> list[dict[str, Any]]:
    return get_ledger().specs()


@router.get("/strategies/{spec_hash}")
def strategy_get(spec_hash: str) -> dict[str, Any]:
    led = get_ledger()
    rec = led.spec(spec_hash)
    if rec is None:
        raise HTTPException(404, f"unknown strategy {spec_hash}")
    n, _ = led.trials(rec["family"])
    return rec | {
        "runs": led.runs(spec_hash),
        "family_trials": n,
        "holdout": led.holdout_status(rec["family"]),
    }


@router.post("/strategies/{spec_hash}/favourite")
def strategy_favourite(spec_hash: str, on: bool = True) -> dict[str, Any]:
    get_ledger().set_favourite(spec_hash, on)
    return {"ok": True}


class PreviewBody(BaseModel):
    spec: dict[str, Any]
    start: int | None = None  # UTC epoch seconds; default: the last 30 days of tier B
    end: int | None = None
    limit: Annotated[int, Field(ge=1, le=5000)] = 2000


@router.post("/strategy/preview")
def strategy_preview(body: PreviewBody) -> dict[str, Any]:
    """Where the entry rules fire (decisions, not trades) — for chart markers and a quick
    'how often' check. Counts cover tiers A and B only; C stays sealed."""
    s = parse_spec(body.spec)
    mk = get_market()
    feats = mk.features(sig.columns_needed(s))
    signals = sig.signals(s, feats)
    counts = {}
    for tier in ("A", "B"):
        lo, hi = mk.split.bounds(tier)
        counts[tier] = signals.filter(
            (signals["decision_time"] >= lo) & (signals["decision_time"] < hi)
        ).height
    visible = signals.filter(signals["decision_time"] < mk.split.c_start)
    if body.start is not None:
        visible = visible.filter(
            visible["decision_time"] >= datetime.fromtimestamp(body.start, UTC).replace(tzinfo=None)
        )
    if body.end is not None:
        visible = visible.filter(
            visible["decision_time"] < datetime.fromtimestamp(body.end, UTC).replace(tzinfo=None)
        )
    visible = visible.tail(body.limit)
    return {
        "spec_hash": s.spec_hash,
        "counts": counts,
        "bars_per_tier": {
            t: feats.filter(
                (feats["available_at"] >= mk.split.bounds(t)[0])
                & (feats["available_at"] < mk.split.bounds(t)[1])
            ).height
            for t in ("A", "B")
        },
        "event_time": [_epoch(t) for t in visible["event_time"].to_list()],
        "side": visible["side"].to_list(),
    }


# ---------------------------------------------------------------- split / families


@router.get("/research/overview")
def research_overview() -> dict[str, Any]:
    mk = get_market()
    led = get_ledger()
    sp = mk.split
    return {
        "split": sp.to_dict(),
        "tiers": {
            t: {
                "start": sp.bounds(t)[0].isoformat(),
                "end": sp.bounds(t)[1].isoformat() if sp.bounds(t)[1] else None,
            }
            for t in ("A", "B", "C")
        },
        "lineage": {
            "dataset_id": mk.dataset_id,
            "cost_model_id": mk.cost_model_id,
            "feature_set_id": mk.feature_set_id,
        },
        "commission": {
            "per_lot_round_turn_usd": mk.commission.per_lot_round_turn_usd,
            "confirmed": mk.commission.confirmed,
            "pessimistic_unconfirmed_usd": mk.commission.unconfirmed_pessimistic_usd,
        },
        "families": led.families(),
        "thresholds": checklist.T,
    }


# ---------------------------------------------------------------- runs


@router.get("/runs")
def run_list(
    spec_hash: str | None = None, limit: Annotated[int, Query(ge=1, le=500)] = 200
) -> list[dict[str, Any]]:
    return get_ledger().runs(spec_hash, limit)


@router.get("/runs/{run_id}")
def run_get(run_id: str) -> dict[str, Any]:
    try:
        return runs.load_run(run_id)
    except FileNotFoundError as e:
        raise HTTPException(404, f"unknown run {run_id}") from e


@router.get("/runs/{run_id}/trades")
def run_trades(
    run_id: str,
    scenario: Literal["optimistic", "base", "pessimistic"] = "pessimistic",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> dict[str, Any]:
    try:
        t = runs.load_trades(run_id, scenario)
    except FileNotFoundError as e:
        raise HTTPException(404, f"no trades for run {run_id}") from e
    t = t.sort("entry_time")
    return {"total": t.height, "offset": offset, "trades": runs.jsonable_trades(t.slice(offset, limit))}


# ---------------------------------------------------------------- jobs


class BacktestBody(BaseModel):
    spec: dict[str, Any]
    tier: Literal["A", "B", "AB"] = "A"


class ParamRange(BaseModel):
    path: str
    values: Annotated[list[float | int | str], Field(min_length=1, max_length=40)]


class OptimizeBody(BaseModel):
    spec: dict[str, Any]
    params: Annotated[list[ParamRange], Field(min_length=1, max_length=3)]


class ValidateBody(BaseModel):
    spec: dict[str, Any]
    params: list[ParamRange] | None = None  # walk-forward re-optimisation grid (optional)


class UnsealBody(BaseModel):
    spec_hash: str
    reason: Annotated[str, Field(min_length=10, max_length=1000)]
    confirm_family: str  # must equal the family name: a deliberate, typed confirmation


def _job_ref(job_id: str) -> dict[str, Any]:
    return {"job_id": job_id}


@router.post("/jobs/backtest")
def job_backtest(body: BacktestBody) -> dict[str, Any]:
    s = parse_spec(body.spec)
    led, mk, runner = get_ledger(), get_market(), get_runner()
    runs.save_spec(s, led)
    job = runner.submit(
        "backtest",
        f"Backtest {s.meta.name} · tier {body.tier}",
        {"spec_hash": s.spec_hash, "tier": body.tier},
        lambda p: {"run_id": runs.run_backtest(s, body.tier, mk, led, progress=p)["run_id"]},
    )
    return _job_ref(job)


@router.post("/jobs/optimize")
def job_optimize(body: OptimizeBody) -> dict[str, Any]:
    s = parse_spec(body.spec)
    params = [p.model_dump() for p in body.params]
    try:
        n = len(optimize.grid(params))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    led, mk, runner = get_ledger(), get_market(), get_runner()
    runs.save_spec(s, led)
    job = runner.submit(
        "optimize",
        f"Optimize {s.meta.name} · {n} variants on tier A",
        {"spec_hash": s.spec_hash, "params": params},
        lambda p: {"run_id": optimize.run_optimize(s, params, mk, led, p)["run_id"]},
    )
    return _job_ref(job)


@router.post("/jobs/validate")
def job_validate(body: ValidateBody) -> dict[str, Any]:
    s = parse_spec(body.spec)
    params = [p.model_dump() for p in body.params] if body.params else None
    if params:
        try:
            optimize.grid(params)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
    led, mk, runner = get_ledger(), get_market(), get_runner()
    runs.save_spec(s, led)
    job = runner.submit(
        "validate",
        f"Validate {s.meta.name}",
        {"spec_hash": s.spec_hash, "params": params},
        lambda p: {"run_id": validate.validate(s, mk, led, params, p)["run_id"]},
    )
    return _job_ref(job)


@router.post("/holdout/unseal")
def holdout_unseal(body: UnsealBody) -> dict[str, Any]:
    led = get_ledger()
    rec = led.spec(body.spec_hash)
    if rec is None:
        raise HTTPException(404, f"unknown strategy {body.spec_hash}")
    s = StrategySpec.model_validate(rec["spec"])
    if body.confirm_family.strip().lower() != s.meta.family:
        raise HTTPException(422, f"type the family name ({s.meta.family}) to confirm")
    if led.holdout_status(s.meta.family):
        raise HTTPException(409, f"family {s.meta.family!r} has already used its holdout")
    mk, runner = get_market(), get_runner()

    def work(p):
        try:
            doc = validate.unseal_and_test(s, mk, led, body.reason, p)
        except HoldoutError as e:
            raise RuntimeError(str(e)) from e
        return {"run_id": doc["run_id"]}

    job = runner.submit("holdout", f"Holdout (tier C) · {s.meta.name}", {"spec_hash": s.spec_hash}, work)
    return _job_ref(job)


@router.get("/jobs")
def job_list(limit: Annotated[int, Query(ge=1, le=200)] = 30) -> list[dict[str, Any]]:
    return get_ledger().jobs(limit)


@router.get("/jobs/{job_id}")
def job_get(job_id: str) -> dict[str, Any]:
    j = get_ledger().job(job_id)
    if j is None:
        raise HTTPException(404, f"unknown job {job_id}")
    return j


@router.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: str) -> dict[str, Any]:
    return {"cancelled": get_runner().cancel(job_id)}
