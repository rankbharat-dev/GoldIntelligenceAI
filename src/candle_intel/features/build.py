"""ci-features — build, leakage-check and version the M5 feature dataset.

    ci-features build [--dataset <derived id>]
    ci-features list  [--dataset <derived id>]
    ci-features show  --time 2026-09-18T14:05 [--dataset <derived id>]   (bar open, UTC)

Output: storage/derived/xauusd/<dataset_id>/features/<feature_set_id>/   (read-only files)
    features_M5.parquet   one row per M5 bar: event_time, available_at, features
    feature_set.json      schema, config, lineage, leakage self-check, summary, sha256

The build is gated: it recomputes the features on truncated and perturbed copies of
the real history (blueprint §7.2) and writes nothing if any past value changes.
Reads derived Parquet only; never contacts MT5.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from candle_intel.costs.build import cost_models, derived_root, latest_dataset
from candle_intel.features import leakage
from candle_intel.features.compute import CONFIG, FEATURE_VERSION, Bars, compute_features
from candle_intel.features.registry import FEATURES, GROUPS
from candle_intel.features.store import FEATURES_FILE, MANIFEST_FILE
from candle_intel.provenance import code_version, config_hash

log = logging.getLogger("ci-features")


class LeakageError(RuntimeError):
    pass


def feature_sets(dataset_dir: Path) -> list[Path]:
    root = dataset_dir / "features"
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if (p / MANIFEST_FILE).exists())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_bars(dataset_dir: Path) -> Bars:
    return Bars(*(pl.read_parquet(dataset_dir / f"{tf}.parquet") for tf in ("M1", "M5", "M15", "H1")))


def selfcheck_cutoffs(start: datetime, end: datetime) -> list[datetime]:
    """Deterministic cut points spread over the history, on the Wednesday on or before
    each point, in the middle of an M5 and an H1 bar during the London/NY overlap (so
    a forming bar exists at every higher timeframe)."""
    span = end - start
    out = []
    for share in (0.2, 0.4, 0.6, 0.8):
        p = start + span * share
        wednesday = p - timedelta(days=(p.weekday() - 2) % 7)
        out.append(wednesday.replace(hour=14, minute=37, second=0, microsecond=0))
    last = end - timedelta(days=(end.weekday() - 2) % 7 or 7)  # the last complete Wednesday
    out.append(last.replace(hour=14, minute=37, second=0, microsecond=0))
    return out


def selfcheck(bars: Bars, point: float, research_start: datetime, features: pl.DataFrame) -> dict[str, Any]:
    def pipeline(b: Bars) -> pl.DataFrame:
        return compute_features(b, point, research_start)

    end = bars.m1["ts_utc"].max()
    cutoffs = selfcheck_cutoffs(research_start, end)
    recompute = leakage.recomputation_check(pipeline, bars, cutoffs)
    perturb = leakage.perturbation_check(pipeline, bars, cutoffs[-1:])
    audit = leakage.availability_audit(features)
    passed = not recompute and not perturb and not any(audit.values())
    return {
        "passed": passed,
        "cutoffs_utc": [c.isoformat() for c in cutoffs],
        "recomputation_mismatches": recompute,
        "perturbation_mismatches": perturb,
        "availability_audit": audit,
    }


def summarise(f: pl.DataFrame, cost_dir: Path | None) -> dict[str, Any]:
    w = f.filter("in_research_window")
    out: dict[str, Any] = {
        "rows": f.height,
        "research_rows": w.height,
        "first_event_utc": str(f["event_time"].min()),
        "last_event_utc": str(f["event_time"].max()),
        "null_share": {
            c: round(n / w.height, 5)
            for c, n in w.select(pl.all().null_count()).row(0, named=True).items()
            if n and w.height
        },
        "hygiene_bars": {c: int(w[c].sum()) for c in w.columns if c.startswith("hyg_")},
        "session_share": {
            r["session"]: round(r["share"], 4)
            for r in w.group_by("session")
            .agg(share=pl.len() / w.height)
            .sort("session")
            .iter_rows(named=True)
        },
        "vol_regime_share": {
            str(r["vol_regime"]): round(r["share"], 4)
            for r in w.group_by("vol_regime")
            .agg(share=pl.len() / w.height)
            .sort("vol_regime")
            .iter_rows(named=True)
        },
    }
    if cost_dir is not None:
        # The cost model flags abnormal spread against a full-history p99 (fine for
        # describing costs, but it uses the future). The feature flag is causal.
        ct = pl.read_parquet(cost_dir / "M5_costs.parquet", columns=["ts_utc", "abnormal_spread"])
        j = w.select("event_time", "hyg_abnormal_spread").join(
            ct.rename({"ts_utc": "event_time"}), on="event_time", how="inner"
        )
        out["abnormal_spread_vs_cost_model"] = {
            "cost_model_id": cost_dir.name,
            "feature_causal": int(j["hyg_abnormal_spread"].sum()),
            "cost_model_full_history": int(j["abnormal_spread"].sum()),
            "both": int((j["hyg_abnormal_spread"] & j["abnormal_spread"]).sum()),
        }
    return out


def build(dataset_dir: Path, run_selfcheck: bool = True) -> Path:
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    point = float(manifest["symbol_spec"]["point"])
    research_start = datetime.fromisoformat(manifest["research_window_utc"][0])
    costs = cost_models(dataset_dir)
    cost_dir = costs[-1] if costs else None

    bars = load_bars(dataset_dir)
    features = compute_features(bars, point, research_start)
    log.info("features: %d rows × %d columns", *features.shape)

    check: dict[str, Any] = {"passed": None, "skipped": True}
    if run_selfcheck:
        log.info("leakage self-check on the real history …")
        check = selfcheck(bars, point, research_start, features)
        log.info("leakage self-check %s", "PASSED" if check["passed"] else "FAILED")
        if not check["passed"]:
            raise LeakageError(json.dumps(check, indent=2))

    built = datetime.now(UTC)
    feature_set_id = f"{manifest['broker_server'].lower()}_f{built:%Y%m%dT%H%M%SZ}"
    out = dataset_dir / "features" / feature_set_id
    out.mkdir(parents=True)
    path = out / FEATURES_FILE
    features.write_parquet(path, compression="zstd", statistics=True)
    path.chmod(0o444)

    config = CONFIG | {"point": point}
    doc = {
        "feature_set_id": feature_set_id,
        "feature_version": FEATURE_VERSION,
        "dataset_id": manifest["dataset_id"],
        "raw_version": manifest["raw_version"],
        "dataset_manifest_sha256": _sha256(dataset_dir / "manifest.json"),
        "companion_cost_model_id": cost_dir.name if cost_dir else None,
        "broker": manifest["broker"],
        "broker_server": manifest["broker_server"],
        "price_side": manifest["price_side"],
        "timeframe": "M5",
        "row_semantics": "event_time = M5 bar open (UTC); available_at = bar close = event_time + 5 min",
        "built_utc": built.isoformat(),
        "code_version": code_version(),
        "config": config,
        "config_hash": config_hash(config),
        "groups": GROUPS,
        "schema": [s.to_dict() | {"dtype": str(features.schema[s.name])} for s in FEATURES],
        "leakage_selfcheck": check,
        "summary": summarise(features, cost_dir),
        "files": {FEATURES_FILE: {"rows": features.height, "sha256": _sha256(path)}},
    }
    mpath = out / MANIFEST_FILE
    mpath.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    mpath.chmod(0o444)
    return out


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="ci-features", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--dataset", help="derived dataset id; default newest")
    b.add_argument(
        "--skip-selfcheck", action="store_true", help="development only; the build is marked unchecked"
    )
    ls = sub.add_parser("list")
    ls.add_argument("--dataset")
    sh = sub.add_parser("show")
    sh.add_argument("--dataset")
    sh.add_argument("--time", required=True, help="M5 bar open, UTC, e.g. 2026-09-18T14:05")
    args = p.parse_args(argv)

    dataset_dir = derived_root() / args.dataset if args.dataset else latest_dataset()
    if args.cmd == "list":
        docs = [
            json.loads((d / MANIFEST_FILE).read_text(encoding="utf-8")) for d in feature_sets(dataset_dir)
        ]
        print(
            json.dumps(
                [
                    {k: m[k] for k in ("feature_set_id", "feature_version", "built_utc", "config_hash")}
                    | {
                        "rows": m["summary"]["rows"],
                        "leakage_selfcheck_passed": m["leakage_selfcheck"]["passed"],
                    }
                    for m in docs
                ],
                indent=2,
            )
        )
        return 0
    if args.cmd == "show":
        sets = feature_sets(dataset_dir)
        if not sets:
            print("No feature set. Run: ci-features build", file=sys.stderr)
            return 1
        t = datetime.fromisoformat(args.time)
        row = pl.scan_parquet(sets[-1] / FEATURES_FILE).filter(pl.col("event_time") == t).collect()
        if row.is_empty():
            print(f"No M5 bar opens at {t} (UTC)", file=sys.stderr)
            return 1
        print(json.dumps(row.row(0, named=True), indent=2, default=str))
        return 0

    try:
        out = build(dataset_dir, run_selfcheck=not args.skip_selfcheck)
    except LeakageError as e:
        log.error("LEAKAGE — nothing written:\n%s", e)
        return 2
    doc = json.loads((out / MANIFEST_FILE).read_text(encoding="utf-8"))
    print(
        json.dumps(
            {k: doc[k] for k in ("feature_set_id", "dataset_id", "config_hash", "leakage_selfcheck", "files")}
            | {"summary": {k: doc["summary"][k] for k in ("rows", "research_rows", "hygiene_bars")}},
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
