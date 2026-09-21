"""ML meta-filter vs the rule baseline (roadmap Phase 10; blueprint §8.3, §14.1).

Question answered: *given a rule strategy, can a model trained on tier A pick which of
its signals to take, so that the strategy does better on unseen tier B?*

1. **Labels (tier A).** Every signal of the base spec on tier A is labelled
   independently with the spec's own exits at pessimistic costs
   (``engine.simulate(overlap=True)``); y = 1 if it would have made money after costs.
2. **Features.** The feature-store row of the decision bar (known at its close):
   every numeric feature, booleans as 0/1, categorical ones (session, volatility
   regime, 3-candle code) as fixed codes. Nothing from later bars.
3. **Model.** LightGBM (fixed small parameters, fixed seed). The probability
   threshold is chosen from *out-of-fold* predictions on A — chronological folds with
   an embargo (no fold trains on data after the one it predicts, plus a one-day gap).
4. **Test (tier B, unseen).** The base strategy and the filtered strategy (only
   signals with probability ≥ threshold) both run through the event-driven engine,
   one position at a time, pessimistic costs.
5. **Verdict** — "helps" only if the filtered strategy's B expectancy beats the
   baseline's by ≥ 0.02 R, has ≥ 100 trades, and the lower end of its bootstrap CI
   is above the baseline's expectancy; otherwise "not helping". Both are results.

The filter counts as a trial on the base spec's family (it is another variant of the
idea). Tier C is never used. Models are stored under ``storage/research/models``.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from candle_intel.backtest import engine, metrics
from candle_intel.backtest.market import Market, research_root
from candle_intel.features.registry import FEATURES
from candle_intel.research.ledger import Ledger
from candle_intel.statistics import robust
from candle_intel.strategy.signals import columns_needed, signals
from candle_intel.strategy.spec import _NUMERIC_UNITS, StrategySpec

ML_VERSION = "ml-filter/1"
SEED = 20260921
PARAMS = {
    "objective": "binary",
    "learning_rate": 0.03,
    "num_leaves": 15,
    "min_child_samples": 50,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "n_estimators": 250,
    "random_state": SEED,
    "verbose": -1,
    "deterministic": True,
    "force_col_wise": True,
}
FOLDS = 5
EMBARGO = timedelta(days=1)
THRESHOLD_QUANTILES = (0.3, 0.4, 0.5, 0.6, 0.7)
MIN_KEEP_SHARE = 0.25
MIN_TRAIN = 300
HELP_DELTA_R = 0.02
HELP_MIN_TRADES = 100
SCENARIO = "pessimistic"
VOCAB = {  # fixed codes, so a stored model means the same thing next year
    "session": ["asian", "london", "new_york", "london_ny_overlap", "off"],
    "vol_regime": ["low", "mid", "high"],
    "dirs_3": [a + b + c for a in "UD-" for b in "UD-" for c in "UD-"],
}
CATEGORICAL = set(VOCAB)
EXCLUDE = {"hyg_no_entry"}


class MLError(ValueError):
    pass


def feature_columns() -> list[str]:
    out = []
    for f in FEATURES:
        if f.name in EXCLUDE:
            continue
        if f.unit in _NUMERIC_UNITS or f.unit == "bool" or f.name in CATEGORICAL:
            out.append(f.name)
    return out


def _matrix(frame: pl.DataFrame, cols: list[str]) -> np.ndarray:
    exprs = []
    for c in cols:
        if c in CATEGORICAL:
            codes = {v: float(i) for i, v in enumerate(VOCAB[c])}
            exprs.append(
                pl.col(c)
                .cast(pl.String)
                .replace_strict(codes, default=None, return_dtype=pl.Float64)
                .alias(c)
            )
        else:
            exprs.append(pl.col(c).cast(pl.Float64).alias(c))
    return frame.select(exprs).to_numpy()


def _labelled_signals(spec: StrategySpec, mk: Market, tier: str) -> pl.DataFrame:
    cols = sorted(set(columns_needed(spec)) | set(feature_columns()))
    feats = mk.features(cols)
    lo, hi = mk.split.bounds(tier)  # type: ignore[arg-type]
    sig = signals(spec, feats).filter((pl.col("decision_time") >= lo) & (pl.col("decision_time") < hi))
    t = engine.simulate(spec, mk, tier, SCENARIO, sig, overlap=True)  # type: ignore[arg-type]
    ctx = feats.select(pl.col("available_at").alias("decision_time"), *feature_columns())
    return (
        t.select("decision_time", "side", "r_net")
        .join(ctx, on="decision_time", how="left")
        .sort("decision_time")
    )


def _folds(times: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    """Chronological blocks; train only on data *before* the test block, minus an embargo."""
    n = len(times)
    edges = np.linspace(0, n, FOLDS + 1).astype(int)
    out = []
    for k in range(1, FOLDS):
        te = np.arange(edges[k], edges[k + 1])
        start = times[edges[k]]
        tr = np.flatnonzero(times < start - np.timedelta64(int(EMBARGO.total_seconds()), "s"))
        if len(tr) >= MIN_TRAIN and len(te):
            out.append((tr, te))
    return out


def _model():
    import lightgbm as lgb

    return lgb.LGBMClassifier(**PARAMS)


def _choose_threshold(p: np.ndarray, r: np.ndarray) -> dict[str, Any]:
    rows = []
    for q in THRESHOLD_QUANTILES:
        thr = float(np.quantile(p, q))
        keep = p >= thr
        if keep.mean() < MIN_KEEP_SHARE or keep.sum() < 30:
            continue
        rows.append(
            {"quantile": q, "threshold": thr, "kept": int(keep.sum()), "expectancy_r": float(r[keep].mean())}
        )
    if not rows:
        return {
            "threshold": float(np.quantile(p, 0.5)),
            "table": [],
            "note": "no quantile kept enough trades",
        }
    best = max(rows, key=lambda x: x["expectancy_r"])
    return {"threshold": best["threshold"], "quantile": best["quantile"], "table": rows}


def _summ(trades: pl.DataFrame, equity: float) -> dict[str, Any]:
    m = metrics.summarise(trades, equity)
    keep = ("n", "expectancy_r", "profit_factor", "max_dd_r", "win_rate", "total_r", "sharpe_per_trade")
    out = {k: m.get(k) for k in keep}
    t = trades.sort("exit_time")
    out["bootstrap"] = robust.stationary_bootstrap_ci(t["r_net"].to_numpy()) if t.height else {}
    return out


def models_root() -> Path:
    return research_root() / "models"


def train_and_test(spec: StrategySpec, mk: Market, ledger: Ledger, progress=None) -> dict[str, Any]:
    if progress:
        progress(0.05, "labelling tier-A signals")
    a = _labelled_signals(spec, mk, "A")
    if a.height < MIN_TRAIN * 2:
        raise MLError(
            f"only {a.height} tier-A signals — a filter needs at least {MIN_TRAIN * 2} to learn from"
        )
    cols = feature_columns()
    x, y = _matrix(a, cols), (a["r_net"].to_numpy() > 0).astype(int)
    r = a["r_net"].to_numpy()
    times = a["decision_time"].to_numpy()

    if progress:
        progress(0.25, "out-of-fold predictions on tier A")
    oof = np.full(len(y), np.nan)
    for tr, te in _folds(times):
        mdl = _model().fit(x[tr], y[tr])
        oof[te] = mdl.predict_proba(x[te])[:, 1]
    ok = ~np.isnan(oof)
    if ok.sum() < 100:
        raise MLError("not enough out-of-fold predictions to choose a threshold")
    thr = _choose_threshold(oof[ok], r[ok])
    auc = _auc(y[ok], oof[ok])

    if progress:
        progress(0.45, "final model on all of tier A")
    model = _model().fit(x, y)
    importance = sorted(
        zip(cols, model.booster_.feature_importance("gain").tolist(), strict=True), key=lambda z: -z[1]
    )[:20]

    if progress:
        progress(0.6, "tier B: baseline vs filtered")
    cols_need = sorted(set(columns_needed(spec)) | set(cols))
    feats = mk.features(cols_need)
    lo, hi = mk.split.bounds("B")
    sig_b = signals(spec, feats).filter((pl.col("decision_time") >= lo) & (pl.col("decision_time") < hi))
    xb = _matrix(
        sig_b.join(
            feats.select(pl.col("available_at").alias("decision_time"), *cols), on="decision_time", how="left"
        ),
        cols,
    )
    pb = model.predict_proba(xb)[:, 1] if len(sig_b) else np.zeros(0)
    ctx = feats.select(
        pl.col("available_at").alias("decision_time"), "session", "vol_regime", pl.col("dow").alias("weekday")
    )
    base_t = engine.simulate(spec, mk, "B", SCENARIO, sig_b).join(ctx, on="decision_time", how="left")
    keep = sig_b.filter(pl.Series(pb >= thr["threshold"]))
    filt_t = engine.simulate(spec, mk, "B", SCENARIO, keep).join(ctx, on="decision_time", how="left")
    eq = spec.sizing.initial_equity_usd
    base, filt = _summ(base_t, eq), _summ(filt_t, eq)
    delta = (
        None
        if base["expectancy_r"] is None or filt["expectancy_r"] is None
        else filt["expectancy_r"] - base["expectancy_r"]
    )
    lo_ci = (filt.get("bootstrap") or {}).get("low")
    helps = bool(
        delta is not None
        and delta >= HELP_DELTA_R
        and (filt["n"] or 0) >= HELP_MIN_TRADES
        and lo_ci is not None
        and lo_ci > (base["expectancy_r"] or 0)
    )
    reasons = []
    if delta is None or delta < HELP_DELTA_R:
        reasons.append(
            f"B expectancy change {delta if delta is None else round(delta, 4)} R < +{HELP_DELTA_R} R"
        )
    if (filt["n"] or 0) < HELP_MIN_TRADES:
        reasons.append(f"filtered strategy traded {filt['n']} times on B < {HELP_MIN_TRADES}")
    if lo_ci is None or lo_ci <= (base["expectancy_r"] or 0):
        reasons.append("the filtered expectancy's 95 % range still includes the baseline")

    # a filtered strategy is another variant of the idea: count it as a trial
    model_id = f"ml_{datetime.now(UTC):%Y%m%dT%H%M%S}_{spec.spec_hash[:8]}_{secrets.token_hex(2)}"
    variant = hashlib.sha256(f"{spec.spec_hash}|{ML_VERSION}|{thr['threshold']:.6f}".encode()).hexdigest()[
        :16
    ]
    n_trials = ledger.record_trial(
        spec.meta.family, variant, "A", filt.get("sharpe_per_trade"), filt["n"] or 0, "ml"
    )

    out_dir = models_root() / model_id
    out_dir.mkdir(parents=True)
    model.booster_.save_model(str(out_dir / "model.txt"))
    doc = {
        "run_id": model_id,
        "kind": "ml",
        "ml_version": ML_VERSION,
        "created_utc": datetime.now(UTC).isoformat(),
        "spec_hash": spec.spec_hash,
        "family": spec.meta.family,
        "name": spec.meta.name,
        "spec": spec.model_dump(mode="json"),
        "params": PARAMS,
        "features": cols,
        "train": {
            "tier": "A",
            "signals": int(a.height),
            "positive_share": round(float(y.mean()), 4),
            "oof_auc": auc,
            "folds": FOLDS,
            "embargo_days": EMBARGO.days,
        },
        "threshold": thr,
        "importance": [{"feature": f, "gain": round(g, 2)} for f, g in importance],
        "test": {
            "tier": "B",
            "signals": int(sig_b.height),
            "baseline": base,
            "filtered": filt,
            "delta_r": delta,
        },
        "verdict": "helps" if helps else "not helping",
        # "helps" compares with the rule; it does not mean the filtered rule makes money
        "filtered_profitable": bool((filt["expectancy_r"] or 0) > 0),
        "reasons": [] if helps else reasons,
        "family_trials": n_trials,
        "lineage": {
            "dataset_id": mk.dataset_id,
            "cost_model_id": mk.cost_model_id,
            "cost_profile": mk.cost_profile,
            "feature_set_id": mk.feature_set_id,
        },
    }
    (out_dir / "run.json").write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
    runs_dir = research_root() / "runs" / model_id  # visible through /api/runs like every result
    runs_dir.mkdir(parents=True)
    (runs_dir / "run.json").write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
    ledger.record_run(
        model_id,
        "ml",
        spec.spec_hash,
        spec.meta.family,
        "B",
        {
            "name": spec.meta.name,
            "verdict": doc["verdict"],
            "baseline_expectancy_r": base["expectancy_r"],
            "filtered_expectancy_r": filt["expectancy_r"],
            "delta_r": delta,
            "oof_auc": auc,
        },
    )
    if progress:
        progress(1.0, "done")
    return doc


def _auc(y: np.ndarray, p: np.ndarray) -> float | None:
    from sklearn.metrics import roc_auc_score

    if len(np.unique(y)) < 2:
        return None
    return round(float(roc_auc_score(y, p)), 4)
