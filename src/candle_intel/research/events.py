"""Event studies — "what happened next?" (Behaviour Explorer, blueprint §8, §9, §11).

An occurrence is a bar where a behaviour's conditions hold (hygiene always enforced).
Each occurrence is labelled with the **triple barrier** of §8.1 — target ``u`` ATR,
stop ``d`` ATR, vertical barrier ``h`` M5 bars — through the backtester's own fill and
cost code (``engine.simulate(overlap=True)``): entry at the next M1 open, barriers on
the M1 path, spread / slippage / commission / swap per scenario. So a study and a
backtest of the same rule can never disagree about what a trade costs.

Output: label shares, R before and after costs, MFE / MAE, fixed-horizon forward
returns (diagnostic only, §8.2), breakdowns by year / session / volatility regime,
a stationary-bootstrap CI and p-value, the §11 sample-size verdict, and the same
numbers for a **baseline** of all eligible bars — the lift is what the behaviour adds.

Tier C is never studied here. Ad-hoc (unregistered) studies run on tier A only and
are marked exploratory; registered behaviours may be studied on B (logged as a run).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
import polars as pl

from candle_intel.backtest import engine
from candle_intel.backtest.market import Market
from candle_intel.backtest.metrics import _f
from candle_intel.research.behaviours import MIN_SAMPLES
from candle_intel.statistics import robust
from candle_intel.strategy.signals import columns_needed, signals
from candle_intel.strategy.spec import StrategySpec

FORWARD_BARS = (3, 6, 12, 24)
BASELINE_MAX = 30_000
MIN_BUCKET = 30
SCEN = ("optimistic", "base", "pessimistic")


class StudyError(ValueError):
    pass


def as_spec(defn: dict[str, Any], name: str = "study") -> StrategySpec:
    b = defn["barriers"]
    return StrategySpec.model_validate(
        {
            "meta": {"name": name[:80], "family": "study"},
            "entries": [{"side": defn["side"], "conditions": defn["conditions"]}],
            "filters": defn.get("filters") or {},
            "exit": {
                "stop_atr": b["stop_atr"],
                "target_atr": b["target_atr"],
                "time_exit_bars": b["horizon_bars"],
                "flat_before_weekend": True,
            },
        }
    )


def _label(reason: pl.Expr) -> pl.Expr:
    return (
        pl.when(reason == "target")
        .then(1)
        .when(reason.is_in(["stop", "stop_gap"]))
        .then(-1)
        .otherwise(0)
        .cast(pl.Int8)
    )


def label(spec: StrategySpec, mk: Market, sigs: pl.DataFrame, tier: str, scenarios=SCEN) -> pl.DataFrame:
    """Triple-barrier outcome of every signal, one row per (signal, scenario)."""
    parts = [engine.simulate(spec, mk, tier, s, sigs, overlap=True) for s in scenarios]
    t = pl.concat(parts)
    return t.with_columns(label=_label(pl.col("exit_reason")))


def forward_returns(mk: Market, sigs: pl.DataFrame) -> dict[str, dict[str, Any]]:
    """Side-adjusted bid move after n M5 bars, in ATR — diagnostic only (§8.2)."""
    if sigs.is_empty():
        return {}
    dts = sigs["decision_time"].dt.epoch("s").to_numpy()
    side = sigs["side"].to_numpy().astype(np.float64)
    atr = sigs["atr_pts"].to_numpy() * mk.point
    ei = np.searchsorted(mk.t, dts, "left")
    ok = ei < len(mk.t)
    out = {}
    for n in FORWARD_BARS:
        j = np.searchsorted(mk.t, dts + n * 300, "left")
        good = ok & (j < len(mk.t))
        r = side[good] * (mk.o[j[good]] - mk.o[ei[good]]) / atr[good]
        r = r[np.isfinite(r)]
        out[str(n)] = {
            "n": int(len(r)),
            "mean_atr": _f(r.mean()) if len(r) else None,
            "hit_rate": _f((r > 0).mean()) if len(r) else None,
        }
    return out


def _stats(t: pl.DataFrame) -> dict[str, Any]:
    if t.is_empty():
        return {"n": 0}
    r = t["r_net"].to_numpy()
    g = t["r_before_costs"].to_numpy()
    lab = t["label"].to_numpy()
    return {
        "n": len(r),
        "target_rate": _f((lab == 1).mean()),
        "stop_rate": _f((lab == -1).mean()),
        "time_rate": _f((lab == 0).mean()),
        "mean_r_net": _f(r.mean()),
        "median_r_net": _f(np.median(r)),
        "std_r_net": _f(r.std(ddof=1)) if len(r) > 1 else None,
        "mean_r_gross": _f(g.mean()),
        "win_rate_net": _f((r > 0).mean()),
        "mfe_r": _f(t["mfe_r"].mean()),
        "mae_r": _f(t["mae_r"].mean()),
        "avg_minutes": _f(t["bars_held_m1"].mean(), 1),
        "ambiguity_rate": _f(t["ambiguous"].mean()),
        "measured_spread_share": _f(t["spread_measured"].mean()),
    }


def _breakdown(t: pl.DataFrame, key: pl.Expr, name: str) -> list[dict[str, Any]]:
    if t.is_empty():
        return []
    g = (
        t.group_by(key.alias(name))
        .agg(
            n=pl.len(),
            mean_r_net=pl.col("r_net").mean(),
            mean_r_gross=pl.col("r_before_costs").mean(),
            target_rate=(pl.col("label") == 1).mean(),
        )
        .sort(name)
    )
    return [
        {name: r[name], "n": r["n"], "scored": r["n"] >= MIN_BUCKET}
        | {k: _f(r[k]) for k in ("mean_r_net", "mean_r_gross", "target_rate")}
        for r in g.iter_rows(named=True)
    ]


def _context(mk: Market) -> pl.DataFrame:
    f = mk.features(["session", "vol_regime"])
    return f.select(pl.col("available_at").alias("decision_time"), "session", "vol_regime")


def sample_verdict(n: int, tier: str) -> dict[str, Any]:
    need = MIN_SAMPLES.get(tier, 0)
    ok = n >= need
    what = {
        "A": "research observation only — cannot become a strategy",
        "B": "cannot be promoted to candidate",
        "C": "indicative, not confirmatory",
    }[tier]
    return {"min": need, "n": n, "sufficient": ok, "consequence": None if ok else what}


_BASELINES: dict[tuple, dict[str, Any]] = {}


def baseline(mk: Market, side: str, barriers: dict[str, Any], tier: str) -> dict[str, Any]:
    """The same labels on every eligible bar of the tier (evenly thinned to at most
    ``BASELINE_MAX``): what the barriers give with no behaviour at all."""
    b = barriers
    key = (id(mk), mk.feature_set_id, side, b["stop_atr"], b["target_atr"], b["horizon_bars"], tier)
    if key in _BASELINES:
        return _BASELINES[key]
    spec = as_spec(
        {"side": side, "conditions": [{"feature": "atr_pts", "op": ">", "value": 0}], "barriers": barriers},
        "baseline",
    )
    feats = mk.features(columns_needed(spec))
    lo, hi = mk.split.bounds(tier)  # type: ignore[arg-type]
    sigs = signals(spec, feats).filter(
        (pl.col("decision_time") >= lo) & ((pl.col("decision_time") < hi) if hi else pl.lit(True))
    )
    step = max(1, sigs.height // BASELINE_MAX)
    sigs = sigs.gather_every(step)
    t = label(spec, mk, sigs, tier, ("pessimistic",))
    out = _stats(t) | {"sampled_every": step}
    if len(_BASELINES) > 32:
        _BASELINES.clear()
    _BASELINES[key] = out
    return out


def study(
    defn: dict[str, Any],
    mk: Market,
    tier: str = "A",
    name: str = "study",
    registered: bool = False,
    progress=None,
) -> dict[str, Any]:
    """Event study of one behaviour on one tier. Pure: no ledger writes."""
    if tier not in ("A", "B"):
        raise StudyError("event studies run on tier A (and B for registered behaviours); C stays sealed")
    if tier == "B" and not registered:
        raise StudyError("tier B is for pre-registered behaviours; register this hypothesis first")
    spec = as_spec(defn, name)
    feats = mk.features(columns_needed(spec))
    lo, hi = mk.split.bounds(tier)  # type: ignore[arg-type]
    sigs = signals(spec, feats).filter((pl.col("decision_time") >= lo) & (pl.col("decision_time") < hi))
    if progress:
        progress(0.1, f"{sigs.height} occurrences — labelling")
    t = label(spec, mk, sigs, tier).join(_context(mk), on="decision_time", how="left")
    pess = t.filter(pl.col("scenario") == "pessimistic").sort("decision_time")
    if progress:
        progress(0.55, "statistics")
    r_net = pess["r_net"].to_numpy()
    r_gross = pess["r_before_costs"].to_numpy()
    per = {s: _stats(t.filter(pl.col("scenario") == s)) for s in SCEN}
    if progress:
        progress(0.7, "baseline (all eligible bars)")
    base = baseline(mk, defn["side"], defn["barriers"], tier)
    p = per["pessimistic"]
    lift = None
    if p.get("n") and base.get("n"):
        lift = {
            "target_rate": _f((p["target_rate"] or 0) - (base["target_rate"] or 0)),
            "mean_r_gross": _f((p["mean_r_gross"] or 0) - (base["mean_r_gross"] or 0)),
            "mean_r_net": _f((p["mean_r_net"] or 0) - (base["mean_r_net"] or 0)),
        }
    occ = pess.tail(5000)
    return {
        "tier": tier,
        "tier_bounds_utc": [lo.isoformat(), hi.isoformat() if hi else None],
        "definition": defn,
        "registered": registered,
        "exploratory": not registered,
        "occurrences": int(sigs.height),
        "bars_in_tier": int(
            feats.filter((pl.col("available_at") >= lo) & (pl.col("available_at") < hi)).height
        ),
        "scenarios": per,
        "gross": {
            "bootstrap": robust.stationary_bootstrap_ci(r_gross),
        },
        "net": {"bootstrap": robust.stationary_bootstrap_ci(r_net)},
        "baseline": base,
        "lift_vs_baseline": lift,
        "forward_returns_atr": forward_returns(mk, sigs),
        "by_year": _breakdown(pess, pl.col("decision_time").dt.year(), "year"),
        "by_session": _breakdown(pess, pl.col("session"), "session"),
        "by_vol_regime": _breakdown(pess, pl.col("vol_regime").fill_null("unknown"), "vol_regime"),
        "sample": sample_verdict(int(sigs.height), tier),
        "markers": {
            "event_time": [
                int(x.replace(tzinfo=UTC).timestamp()) - 300 for x in occ["decision_time"].to_list()
            ],
            "label": occ["label"].to_list(),
            "r_net": [round(x, 3) for x in occ["r_net"].to_list()],
        },
        "computed_utc": datetime.now(UTC).isoformat(),
    }


# ---------------------------------------------------------------- feature distributions


def distribution(mk: Market, feature: str, by: str | None, numeric: bool, bins: int = 30) -> dict[str, Any]:
    """Distribution of one feature over tiers A∪B (never C), optionally split by year,
    session, volatility regime or tier. Numeric: quantiles + a shared histogram;
    categorical: value shares."""
    cols = [feature] + ([by] if by in ("session", "vol_regime") else [])
    f = mk.features(cols)
    lo, hi = mk.split.bounds("AB")
    f = f.filter((pl.col("available_at") >= lo) & (pl.col("available_at") < hi))
    if by == "year":
        f = f.with_columns(_g=pl.col("event_time").dt.year().cast(pl.String))
    elif by == "tier":
        f = f.with_columns(
            _g=pl.when(pl.col("available_at") < mk.split.b_start).then(pl.lit("A")).otherwise(pl.lit("B"))
        )
    elif by in ("session", "vol_regime"):
        f = f.with_columns(_g=pl.col(by).cast(pl.String).fill_null("unknown"))
    else:
        f = f.with_columns(_g=pl.lit("all"))
    groups = sorted(f["_g"].unique().to_list())
    out: dict[str, Any] = {"feature": feature, "by": by or "none", "rows": f.height, "groups": []}
    if numeric:
        x = f[feature].cast(pl.Float64)
        q1, q99 = x.quantile(0.01), x.quantile(0.99)
        if q1 is None or q99 is None:
            return out | {"numeric": True, "edges": []}
        if q1 == q99:
            q1, q99 = q1 - 0.5, q99 + 0.5
        edges = np.linspace(q1, q99, bins + 1)
        out |= {"numeric": True, "edges": [round(float(e), 5) for e in edges]}
        for gname in groups:
            v = f.filter(pl.col("_g") == gname)[feature].cast(pl.Float64).drop_nulls().drop_nans().to_numpy()
            hist = np.histogram(np.clip(v, edges[0], edges[-1]), edges)[0] if len(v) else np.zeros(bins)
            qs = np.quantile(v, [0.1, 0.25, 0.5, 0.75, 0.9]) if len(v) else [None] * 5
            out["groups"].append(
                {
                    "group": gname,
                    "n": int(len(v)),
                    "nulls": int(f.filter(pl.col("_g") == gname)[feature].null_count()),
                    "mean": _f(v.mean()) if len(v) else None,
                    "p10": _f(qs[0]),
                    "p25": _f(qs[1]),
                    "p50": _f(qs[2]),
                    "p75": _f(qs[3]),
                    "p90": _f(qs[4]),
                    "hist": [int(h) for h in hist],
                }
            )
        return out
    vals = f[feature].cast(pl.String).fill_null("∅")
    cats = vals.value_counts(sort=True).head(12)[feature].to_list()
    out |= {"numeric": False, "categories": cats}
    for gname in groups:
        g = f.filter(pl.col("_g") == gname)[feature].cast(pl.String).fill_null("∅")
        n = g.len()
        vc = dict(g.value_counts().iter_rows())
        out["groups"].append(
            {"group": gname, "n": n, "shares": {c: _f(vc.get(c, 0) / n) if n else None for c in cats}}
        )
    return out


# ---------------------------------------------------------------- BH-FDR screen


def fdr_screen(results: list[dict[str, Any]], q: float = 0.10) -> list[dict[str, Any]]:
    """Benjamini–Hochberg across behaviours (§9.3) on the one-sided bootstrap p-values,
    before costs (does the behaviour predict anything?) and after pessimistic costs
    (is it tradeable?)."""
    out = [dict(r) for r in results]
    for key in ("gross", "net"):
        ps = [r.get(f"p_{key}") for r in out]
        idx = [i for i, p in enumerate(ps) if p is not None]
        adj = robust.benjamini_hochberg([ps[i] for i in idx], q)
        for i, a in zip(idx, adj, strict=True):
            out[i][f"q_{key}"] = a["q_value"]
            out[i][f"discovery_{key}"] = a["rejected"]
    return out
