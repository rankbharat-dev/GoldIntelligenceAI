"""Run and store behaviour studies (Behaviour Explorer). Like backtests, every study
is a run with an id, a stored document and a ledger row — tier-B studies of
registered behaviours are therefore always logged (§9.1)."""

from __future__ import annotations

from typing import Any

from candle_intel.backtest.market import Market
from candle_intel.research import behaviours, events, runs
from candle_intel.research.ledger import Ledger


def _record(doc: dict[str, Any], kind: str, key: str, family: str, tier: str, summary: dict, ledger: Ledger):
    runs.write_doc(doc["run_id"], doc)
    ledger.record_run(doc["run_id"], kind, key, family, tier, summary)
    return doc


def run_study(
    defn: dict[str, Any],
    mk: Market,
    ledger: Ledger,
    tier: str = "A",
    name: str = "ad-hoc study",
    pattern_id: str | None = None,
    progress=None,
) -> dict[str, Any]:
    registered = False
    if pattern_id:
        rec = ledger.pattern(pattern_id)
        if rec is None:
            raise events.StudyError(f"unknown pattern {pattern_id}")
        d = rec["definition"]
        defn = {"side": d["side"], "conditions": d["conditions"], "barriers": d["barriers"]}
        name, registered = rec["name"], True
    key = behaviours.definition_hash(defn)
    res = events.study(defn, mk, tier, name, registered, progress)
    doc = {
        "run_id": runs.new_run_id("study", key, tier),
        "kind": "study",
        "name": name,
        "pattern_id": pattern_id,
        "definition_hash": key,
        "lineage": {
            "dataset_id": mk.dataset_id,
            "cost_model_id": mk.cost_model_id,
            "feature_set_id": mk.feature_set_id,
        },
    } | res
    p = res["scenarios"]["pessimistic"]
    summary = {
        "name": name,
        "pattern_id": pattern_id,
        "exploratory": not registered,
        "n": res["occurrences"],
        "target_rate": p.get("target_rate"),
        "mean_r_gross": p.get("mean_r_gross"),
        "mean_r_net": p.get("mean_r_net"),
        "lift_target_rate": (res["lift_vs_baseline"] or {}).get("target_rate"),
        "p_gross": res["gross"]["bootstrap"].get("p_mean_le_0"),
        "sufficient": res["sample"]["sufficient"],
    }
    fam = f"study:{pattern_id or 'adhoc'}"[:60]
    return _record(doc, "study", key, fam, tier, summary, ledger)


def run_screen(mk: Market, ledger: Ledger, tier: str = "A", progress=None) -> dict[str, Any]:
    """Every registered behaviour on one tier, with BH-FDR across them."""
    pats = behaviours.ensure_registered(ledger)
    rows = []
    for i, p in enumerate(pats):
        if progress:
            progress(i / max(len(pats), 1), f"{p['pattern_id']} ({i + 1}/{len(pats)})")
        d = p["definition"]
        defn = {"side": d["side"], "conditions": d["conditions"], "barriers": d["barriers"]}
        res = events.study(defn, mk, tier, p["name"], registered=True)
        ps = res["scenarios"]["pessimistic"]
        rows.append(
            {
                "pattern_id": p["pattern_id"],
                "name": p["name"],
                "behaviour": p["behaviour"],
                "side": d["side"],
                "registered_at": p["registered_at"],
                "n": res["occurrences"],
                "sufficient": res["sample"]["sufficient"],
                "target_rate": ps.get("target_rate"),
                "baseline_target_rate": res["baseline"].get("target_rate"),
                "mean_r_gross": ps.get("mean_r_gross"),
                "mean_r_net": ps.get("mean_r_net"),
                "mean_r_net_base": res["scenarios"]["base"].get("mean_r_net"),
                "p_gross": res["gross"]["bootstrap"].get("p_mean_le_0"),
                "p_net": res["net"]["bootstrap"].get("p_mean_le_0"),
                "ci_net": [res["net"]["bootstrap"].get("low"), res["net"]["bootstrap"].get("high")],
                "stability_year": _share_positive(res["by_year"]),
                "stability_session": _share_positive(res["by_session"]),
            }
        )
    rows = events.fdr_screen(rows, q=0.10)
    key = behaviours.definition_hash({"screen": tier, "n": len(rows)})
    doc = {
        "run_id": runs.new_run_id("screen", key, tier),
        "kind": "screen",
        "name": f"Behaviour screen · tier {tier}",
        "tier": tier,
        "fdr_q": 0.10,
        "rule_version": behaviours.RULE_VERSION,
        "rows": rows,
        "lineage": {
            "dataset_id": mk.dataset_id,
            "cost_model_id": mk.cost_model_id,
            "feature_set_id": mk.feature_set_id,
        },
    }
    summary = {
        "name": doc["name"],
        "behaviours": len(rows),
        "discoveries_gross": sum(bool(r.get("discovery_gross")) for r in rows),
        "discoveries_net": sum(bool(r.get("discovery_net")) for r in rows),
    }
    if progress:
        progress(1.0, "done")
    return _record(doc, "screen", key, "study:screen", tier, summary, ledger)


def _share_positive(buckets: list[dict[str, Any]]) -> float | None:
    s = [b for b in buckets if b.get("scored") and b.get("mean_r_gross") is not None]
    return round(sum(b["mean_r_gross"] > 0 for b in s) / len(s), 3) if s else None
