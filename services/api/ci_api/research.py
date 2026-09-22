"""Research endpoints: strategy specs, backtests, optimisation, validation, holdout, jobs.

Numbers only ever come from the Python engine (candle_intel.backtest / research);
this module validates requests, starts jobs and serves stored results. Tier C stays
sealed except through ``POST /api/holdout/unseal`` (one logged access per family).
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Any, Literal

import polars as pl
from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError

from candle_intel.backtest import market
from candle_intel.costs import build as cost_build
from candle_intel.costs import profiles
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
        return market.load(market.latest_dataset_dir(), profiles.active())
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


class ExplainBody(BaseModel):
    spec: dict[str, Any]
    time: int  # UTC epoch seconds: a trade's decision_time (the decision bar's close)


def _plain(v: Any) -> Any:
    if isinstance(v, float):
        return None if v != v else round(v, 5)
    return v


@router.post("/strategy/explain")
def strategy_explain(body: ExplainBody) -> dict[str, Any]:
    """Why a rule fired (or did not) on one decision bar: every entry condition and
    filter of the spec with the bar's actual value, evaluated by the engine's own
    expressions. Lets the owner check a trade on the chart against their rules.
    Bars inside the sealed tier C are refused."""
    s = parse_spec(body.spec)
    mk = get_market()
    t = datetime.fromtimestamp(body.time, UTC).replace(tzinfo=None)
    if t >= mk.split.c_start:
        raise HTTPException(403, "This bar is in tier C (final exam data) — sealed.")
    cols = sig.columns_needed(s)
    row = mk.features(cols).filter(pl.col("available_at") == t)
    if row.is_empty():
        raise HTTPException(404, f"No decision bar closes at {t.isoformat()} UTC")

    def check(expr: pl.Expr) -> bool:
        return bool(row.select(expr.alias("_x"))["_x"][0])

    entries = []
    for e in s.entries:
        conds = [
            {
                "feature": c.feature,
                "op": c.op,
                "value": c.value,
                "actual": _plain(row[c.feature][0]),
                "passed": check(sig.condition_expr(c)),
            }
            for c in e.conditions
        ]
        entries.append({"side": e.side, "conditions": conds, "passed": all(c["passed"] for c in conds)})

    f = s.filters
    filters = [
        {"key": "hygiene", "value": None, "actual": _plain(row["hyg_no_entry"][0]),
         "passed": check(~pl.col("hyg_no_entry").fill_null(True))},
    ]
    for key, col, want in (
        ("sessions", "session", f.sessions),
        ("vol_regimes", "vol_regime", f.vol_regimes),
        ("hours_utc", "hour_utc", f.hours_utc),
        ("weekdays", "dow", f.weekdays),
    ):
        if want is not None:
            filters.append({"key": key, "value": want, "actual": _plain(row[col][0]),
                            "passed": check(pl.col(col).is_in(want).fill_null(False))})
    if f.max_spread_rel is not None:
        filters.append({"key": "max_spread_rel", "value": f.max_spread_rel, "actual": _plain(row["spread_rel"][0]),
                        "passed": check((pl.col("spread_rel") <= f.max_spread_rel).fill_null(False))})
    gate = check(sig.filter_expr(f))
    return {
        "spec_hash": s.spec_hash,
        "decision_time": body.time,
        "event_time": _epoch(row["event_time"][0]),
        "atr_pts": _plain(row["atr_pts"][0]),
        "entries": entries,
        "filters": filters,
        "fires": gate and (sum(e["passed"] for e in entries) > 0),
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
        "cost_profile": {
            "profile": mk.cost_profile,
            "status": mk.cost_status,
            "promotion_profile": profiles.PROMOTION_PROFILE,
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


class CostJobBody(BaseModel):
    action: Literal["provisional-raw", "calibrate-raw"]
    commission_per_lot: Annotated[float, Field(ge=0, le=100)] = profiles.OWNER_RAW_COMMISSION_USD
    raw_ticks: str | None = None  # raw version of the Raw Spread demo's tick archive (calibrate-raw)


@router.post("/jobs/costs")
def job_costs(body: CostJobBody) -> dict[str, Any]:
    """Build a Raw cost profile from the dashboard. Reads Parquet only (the Raw demo's
    ticks must already be ingested with ``ci-ingest raw --ticks --account-label raw``)."""
    ds = market.latest_dataset_dir()
    if body.action == "calibrate-raw" and not body.raw_ticks:
        raise HTTPException(422, "choose the Raw account's tick archive")

    def work(p):
        p(0.05, body.action)
        if body.action == "provisional-raw":
            out = profiles.build_provisional_raw(ds, body.commission_per_lot)
        else:
            from candle_intel.costs.execution import Commission

            c = Commission(per_lot_round_turn_usd=body.commission_per_lot, confirmed=True)
            out = cost_build.build(ds, c, "raw", body.raw_ticks)
        market.load.cache_clear()
        return {"run_id": out.name}

    return _job_ref(get_runner().submit("costs", f"Cost profile · {body.action}", body.model_dump(), work))


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
