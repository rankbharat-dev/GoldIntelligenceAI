"""Research API — serves validated datasets to the web app.

Reads derived Parquet datasets only (storage/derived/xauusd). It cannot reach MT5
or the MCP server; tests/leakage/test_mt5_boundary.py enforces that.

    ci-api                      → http://127.0.0.1:8000  (docs at /docs)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

import polars as pl
from fastapi import FastAPI, HTTPException, Query

from candle_intel.config import get_settings
from candle_intel.costs import profiles

from . import assistant, ceo, explore, patterns, pipeline, research

Timeframe = Literal["M1", "M5", "M15", "H1"]
MAX_BARS = 5000

app = FastAPI(title="Candle Intelligence API", version="0.2.0", docs_url="/docs")
app.include_router(research.router)
app.include_router(explore.router)
app.include_router(pipeline.router)
app.include_router(assistant.router)
app.include_router(ceo.router)
app.include_router(patterns.router)


def _root() -> Path:
    return get_settings().storage_root / "derived" / "xauusd"


@lru_cache(maxsize=32)
def _manifest(dataset_id: str) -> dict[str, Any]:
    """Callers pass ids from _dataset_ids() / _resolve() only."""
    return json.loads((_root() / dataset_id / "manifest.json").read_text(encoding="utf-8"))


def _dataset_ids() -> list[str]:
    root = _root()
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "manifest.json").exists())


def _resolve(dataset: str) -> str:
    """Map a request's dataset to a known directory name. Only ids that exist on disk
    are accepted, so the parameter can never be used to build an arbitrary path."""
    ids = _dataset_ids()
    if dataset == "latest":
        if not ids:
            raise HTTPException(404, "No datasets yet. Run: ci-ingest raw, then ci-data build")
        return ids[-1]
    if dataset not in ids:
        raise HTTPException(404, f"Unknown dataset {dataset!r}")
    return dataset


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "datasets": len(_dataset_ids())}


@app.get("/api/datasets")
def datasets() -> list[dict[str, Any]]:
    out = []
    for ds in _dataset_ids():
        m = _manifest(ds)
        out.append(
            {
                "dataset_id": ds,
                "broker": m["broker"],
                "broker_server": m["broker_server"],
                "research_window_utc": m["research_window_utc"],
                "built_utc": m["built_utc"],
            }
        )
    return out


@app.get("/api/datasets/{dataset}/summary")
def summary(dataset: str) -> dict[str, Any]:
    ds = _resolve(dataset)
    m = _manifest(ds)
    q = json.loads((_root() / ds / "quality.json").read_text(encoding="utf-8"))
    return {
        "dataset_id": ds,
        "symbol": m["symbol"],
        "broker": m["broker"],
        "broker_server": m["broker_server"],
        "price_side": m["price_side"],
        "built_utc": m["built_utc"],
        "code_version": m["code_version"],
        "bars": {tf: f["rows"] for tf, f in m["files"].items()},
        "clock_model": m["clock_model"],
        "verification_vs_broker": m["verification_vs_broker"],
        "quality": q,
        "symbol_spec": m["symbol_spec"],
    }


@app.get("/api/candles")
def candles(
    tf: Timeframe = "M5",
    dataset: str = "latest",
    before: Annotated[int | None, Query(description="UTC epoch seconds; bars strictly before")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_BARS)] = 1500,
) -> dict[str, Any]:
    """Bars ending before `before` (default: the newest), oldest first — the shape
    TradingView Lightweight Charts expects, and what infinite scroll-back needs."""
    ds = _resolve(dataset)
    lf = pl.scan_parquet(_root() / ds / f"{tf}.parquet")
    if before is not None:
        cutoff = datetime.fromtimestamp(before, tz=UTC).replace(tzinfo=None)
        lf = lf.filter(pl.col("ts_utc") < cutoff)
    cols = ["ts_utc", "open", "high", "low", "close", "tick_volume"]
    if tf != "M1":
        cols.append("m1_bars")
    df = lf.select(cols).tail(limit).collect()
    expected_m1 = {"M1": 1, "M5": 5, "M15": 15, "H1": 60}[tf]
    return {
        "dataset_id": ds,
        "timeframe": tf,
        "count": df.height,
        "has_more": df.height == limit,
        "time": (df["ts_utc"].dt.epoch("s")).to_list(),
        "open": df["open"].to_list(),
        "high": df["high"].to_list(),
        "low": df["low"].to_list(),
        "close": df["close"].to_list(),
        "volume": df["tick_volume"].to_list(),
        # Bars built from fewer M1 bars than their length (gaps, session edges).
        "incomplete": (df["m1_bars"] < expected_m1).to_list() if tf != "M1" else None,
    }


# ---------------------------------------------------------------- costs (Phase 2)

CostStat = Literal["p25", "p50", "p90", "p99", "mean"]
VolBucket = Literal["all", "low", "mid", "high"]


def _cost_model_dir(ds: str, profile: str | None = None) -> Path:
    """Newest cost model of a dataset for a profile (default: the active one, falling
    back to the demo account's). Directory names come from disk."""
    want = profile or profiles.active()
    if want not in profiles.PROFILES:
        raise HTTPException(422, f"unknown cost profile {want!r}")
    m = profiles.newest(_root() / ds, want) or (None if profile else profiles.newest(_root() / ds))
    if m is None:
        raise HTTPException(404, f"No {want} cost model for {ds}. Run: ci-costs build")
    return m


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/costs/profiles")
def cost_profiles() -> dict[str, Any]:
    """Account cost profiles of the newest dataset, which one new runs use, and which one
    promotion requires (MASTER_PROMPT §5: the account that will trade)."""
    ids = _dataset_ids()
    if not ids:
        raise HTTPException(404, "No datasets yet")
    raw_archives = []
    raw_root = get_settings().storage_root / "raw" / "xauusd"
    for p in sorted(raw_root.iterdir()) if raw_root.exists() else []:
        mf = p / "manifest.json"
        if mf.exists():
            m = json.loads(mf.read_text(encoding="utf-8"))
            raw_archives.append(
                {
                    "raw_version": m["raw_version"],
                    "server": m["session"]["broker_server"],
                    "account_label": m["session"].get("account_label", "standard"),
                    "tick_days": len(m.get("tick_chunks", [])),
                }
            )
    return {
        "dataset_id": ids[-1],
        "active": profiles.active(),
        "promotion_profile": profiles.PROMOTION_PROFILE,
        "profiles": profiles.listing(_root() / ids[-1]),
        "raw_archives": raw_archives,
    }


@app.post("/api/costs/profiles/active")
def cost_profile_set(profile: str) -> dict[str, Any]:
    ids = _dataset_ids()
    try:
        return profiles.set_active(profile, _root() / ids[-1])
    except (ValueError, FileNotFoundError, IndexError) as e:
        raise HTTPException(422, str(e)) from e


@app.get("/api/costs/{dataset}")
def costs(dataset: str, profile: str | None = None) -> dict[str, Any]:
    cm = _cost_model_dir(_resolve(dataset), profile)
    doc = _read_json(cm / "cost_model.json")
    keep = (
        "cost_model_id",
        "model_version",
        "dataset_id",
        "broker",
        "broker_server",
        "built_utc",
        "code_version",
        "config_hash",
        "tick_window",
        "vol_tercile_edges",
        "summary",
        "execution",
    )
    return {k: doc[k] for k in keep} | {
        "profile": profiles.profile_of(doc)[0],
        "profile_status": profiles.profile_of(doc)[1],
        "spread_basis": doc.get("spread_basis", "measured on this account's ticks"),
        "validation": _read_json(cm / "validation.json"),
        "point": doc["symbol_spec"]["point"],
        "contract_size": doc["symbol_spec"]["trade_contract_size"],
    }


@app.get("/api/costs/{dataset}/heatmap")
def cost_heatmap(
    dataset: str,
    stat: CostStat = "p50",
    vol: VolBucket = "all",
    window: Literal["full", "current"] = "full",
    basis: Literal["abs", "ratio"] = "abs",
) -> dict[str, Any]:
    """Spread by UTC hour × weekday. ``abs`` = points; ``ratio`` = multiple of the
    minute's minimum spread (the time-of-day shape with the broker's tier removed)."""
    if window == "current" and basis == "ratio":
        raise HTTPException(422, "The current window is stored in points only (basis=abs)")
    cm = _cost_model_dir(_resolve(dataset))
    level = 1 if vol == "all" else 0
    cells = (
        pl.scan_parquet(cm / "spread_cells.parquet")
        .filter(
            (pl.col("basis") == basis)
            & (pl.col("window") == window)
            & (pl.col("level") == level)
            & (pl.col("vol_bucket") == vol)
        )
        .select("hour_utc", "dow", "minutes", stat)
        .collect()
    )
    lookup = {(r["dow"], r["hour_utc"]): r for r in cells.iter_rows(named=True)}
    days = list(range(1, 8))  # ISO weekday, 1 = Monday
    hours = list(range(24))

    def grid(col: str) -> list[list[float | None]]:
        return [[round(lookup[(d, h)][col], 4) if (d, h) in lookup else None for h in hours] for d in days]

    return {
        "stat": stat,
        "vol": vol,
        "window": window,
        "basis": basis,
        "unit": "points" if basis == "abs" else "x minute minimum",
        "days": days,
        "hours": hours,
        "values": grid(stat),
        "minutes": grid("minutes"),
    }


@app.get("/api/costs/{dataset}/levels")
def cost_levels(dataset: str) -> dict[str, Any]:
    """Daily spread level over the whole history (median of each M1 bar's minimum
    spread) and, inside the tick window, the time-weighted measured mean."""
    cm = _cost_model_dir(_resolve(dataset))
    df = pl.read_parquet(cm / "level_daily.parquet").sort("day")
    # Full trading days only: Sunday-evening and holiday stub sessions (~1 h of bars,
    # spreads up to 10x) are real but would hide the tier history behind a few spikes.
    df = df.filter(pl.col("bars") >= 0.5 * pl.col("bars").median())
    return {
        "stub_days_excluded": True,
        "time": df["day"].cast(pl.Datetime("us")).dt.epoch("s").to_list(),
        "level_median": df["level_median"].to_list(),
        "measured_mean": [None if v is None else round(v, 2) for v in df["measured_mean"].to_list()],
    }


# ---------------------------------------------------------------- features (Phase 3)

TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60}
FEATURE_META = ("event_time", "available_at", "ts_server", "trading_day", "m15_close_utc", "h1_close_utc")


def _feature_set_dir(ds: str) -> Path:
    """Newest feature set of a dataset (ci-features build). Directory names come from disk."""
    root = _root() / ds / "features"
    sets = sorted(p for p in root.iterdir() if (p / "feature_set.json").exists()) if root.exists() else []
    if not sets:
        raise HTTPException(404, f"No feature set for {ds}. Run: ci-features build")
    return sets[-1]


def _json_value(v: Any) -> Any:
    if isinstance(v, float) and v != v:  # NaN is not JSON
        return None
    if isinstance(v, datetime):
        return int(v.replace(tzinfo=UTC).timestamp())
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


@app.get("/api/features/{dataset}")
def feature_set(dataset: str) -> dict[str, Any]:
    """The newest feature set: schema (name, group, unit, timing, description), lineage,
    leakage self-check and summary."""
    doc = _read_json(_feature_set_dir(_resolve(dataset)) / "feature_set.json")
    keep = (
        "feature_set_id",
        "feature_version",
        "dataset_id",
        "companion_cost_model_id",
        "row_semantics",
        "built_utc",
        "code_version",
        "config_hash",
        "groups",
        "schema",
        "leakage_selfcheck",
        "summary",
        "files",
    )
    return {k: doc[k] for k in keep}


@app.get("/api/features/{dataset}/bar")
def feature_bar(
    dataset: str,
    time: Annotated[int, Query(description="UTC epoch seconds of the clicked bar's open")],
    tf: Timeframe = "M5",
) -> dict[str, Any]:
    """Features of one M5 bar. A click on M1 maps to the M5 bar containing that minute;
    on M15 / H1 to the last M5 bar inside it (the one that closes with it)."""
    ds = _resolve(dataset)
    fs = _feature_set_dir(ds)
    t = datetime.fromtimestamp(time, tz=UTC).replace(tzinfo=None)
    start = t.replace(minute=t.minute - t.minute % 5, second=0, microsecond=0)
    end = t + timedelta(minutes=TF_MINUTES[tf])
    df = (
        pl.scan_parquet(fs / "features_M5.parquet")
        .filter((pl.col("event_time") >= start) & (pl.col("event_time") < end))
        .sort("event_time")
        .tail(1)
        .collect()
    )
    if df.is_empty():
        raise HTTPException(404, f"No M5 bar inside the {tf} bar at {t.isoformat()} UTC")
    row = {k: _json_value(v) for k, v in df.row(0, named=True).items()}
    event_time = df["event_time"][0]

    costs = None
    try:
        cm = _cost_model_dir(ds)
        c = (
            pl.scan_parquet(cm / "M5_costs.parquet")
            .filter(pl.col("ts_utc") == event_time)
            .select("spread_source", "spread_optimistic", "spread_base", "spread_pessimistic")
            .collect()
        )
        if c.height:
            costs = {"cost_model_id": cm.name} | {k: _json_value(v) for k, v in c.row(0, named=True).items()}
    except HTTPException:
        pass

    return {
        "dataset_id": ds,
        "feature_set_id": fs.name,
        "tf": tf,
        "requested_time": time,
        "mapped": tf != "M5" or row["event_time"] != time,
        "meta": {k: row[k] for k in FEATURE_META},
        "values": {k: v for k, v in row.items() if k not in FEATURE_META and k != "in_research_window"},
        "in_research_window": row["in_research_window"],
        "costs": costs,
    }


INDICATOR_COLS = (
    "atr_pts",
    "ema9_dist_atr",
    "ema21_dist_atr",
    "ema50_dist_atr",
    "ema200_dist_atr",
    "bb_pctb",
    "bb_width_atr",
    "bb_mid_dist_atr",
    "vwap_dist_atr",
    "rsi14",
    "macd_hist_atr",
    "stoch_k14",
    "adx14",
)
MAX_INDICATOR_BARS = 6000


@app.get("/api/indicators")
def indicators(
    start: Annotated[int, Query(description="UTC epoch seconds (M5 bar open), inclusive")],
    end: Annotated[int, Query(description="UTC epoch seconds (M5 bar open), exclusive")],
    dataset: str = "latest",
) -> dict[str, Any]:
    """The engine's own M5 indicators over a window, as chart lines: EMA 9/21/50/200,
    Bollinger (50, 2.1) and session VWAP rebuilt to price from the stored feature
    distances (``level = close − dist × ATR``, ATR = atr_pts × point), plus RSI 14,
    MACD histogram (ATR units), Stochastic %K and ADX as stored. Nothing is recomputed,
    so the chart shows exactly what the strategy rules read."""
    if end <= start:
        raise HTTPException(422, "end must be after start")
    ds = _resolve(dataset)
    fs = _feature_set_dir(ds)
    lo = datetime.fromtimestamp(start, tz=UTC).replace(tzinfo=None)
    hi = datetime.fromtimestamp(end, tz=UTC).replace(tzinfo=None)
    point = float(_manifest(ds)["symbol_spec"]["point"])
    f = (
        pl.scan_parquet(fs / "features_M5.parquet")
        .filter((pl.col("event_time") >= lo) & (pl.col("event_time") < hi))
        .select("event_time", *INDICATOR_COLS)
    )
    bars = pl.scan_parquet(_root() / ds / "M5.parquet").select(pl.col("ts_utc").alias("event_time"), "close")
    df = f.join(bars, on="event_time", how="inner").sort("event_time").head(MAX_INDICATOR_BARS).collect()
    atr = pl.col("atr_pts") * point
    c = pl.col("close")
    bb_lo = c - pl.col("bb_pctb") * pl.col("bb_width_atr") * atr
    df = df.with_columns(
        *[(c - pl.col(f"ema{n}_dist_atr") * atr).alias(f"ema{n}") for n in (9, 21, 50, 200)],
        bb_lower=bb_lo,
        bb_upper=bb_lo + pl.col("bb_width_atr") * atr,
        bb_mid=c - pl.col("bb_mid_dist_atr") * atr,
        vwap=c - pl.col("vwap_dist_atr") * atr,
    )

    def col(name: str, digits: int) -> list[float | None]:
        return [None if v is None or v != v else round(v, digits) for v in df[name].to_list()]

    return {
        "dataset_id": ds,
        "feature_set_id": fs.name,
        "timeframe": "M5",
        "count": df.height,
        "truncated": df.height == MAX_INDICATOR_BARS,
        "time": df["event_time"].dt.epoch("s").to_list(),
        "price": {k: col(k, 3) for k in ("ema9", "ema21", "ema50", "ema200", "bb_upper", "bb_mid", "bb_lower", "vwap")},
        "osc": {k: col(k, 3) for k in ("rsi14", "macd_hist_atr", "stoch_k14", "adx14")},
    }


def main() -> None:
    import uvicorn

    uvicorn.run("ci_api.main:app", host="127.0.0.1", port=8000, reload=False)
