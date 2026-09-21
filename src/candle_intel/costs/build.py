"""ci-costs — build, validate and version the cost model of a derived dataset.

    ci-costs build [--dataset <derived id>] [--commission-per-lot USD --commission-confirmed]
    ci-costs list  [--dataset <derived id>]

Output: storage/derived/xauusd/<dataset_id>/costs/<cost_model_id>/   (read-only files)
    M1_costs.parquet  M5_costs.parquet   per-bar spread quantiles, source, scenarios
    spread_cells.parquet                 conditional cells (abs + ratio, full + current window)
    measured_minutes.parquet             per-minute spread measured from ticks
    level_daily.parquet                  daily spread level (bars) and measured mean (ticks)
    validation.json                      out-of-sample report
    cost_model.json                      parameters, lineage, hashes, summary

Reads the raw tick archive and derived Parquet only; never contacts MT5.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from candle_intel.config import get_settings
from candle_intel.costs import execution, spread, ticks, validate, volatility
from candle_intel.provenance import code_version, config_hash

log = logging.getLogger("ci-costs")

MODEL_VERSION = "cost-model/1"


def derived_root() -> Path:
    return get_settings().storage_root / "derived" / "xauusd"


def raw_root() -> Path:
    return get_settings().storage_root / "raw" / "xauusd"


def latest_dataset() -> Path:
    ds = sorted(p for p in derived_root().iterdir() if (p / "manifest.json").exists())
    if not ds:
        raise FileNotFoundError("No derived dataset. Run: ci-data build")
    return ds[-1]


def cost_models(dataset_dir: Path) -> list[Path]:
    root = dataset_dir / "costs"
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if (p / "cost_model.json").exists())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(df: pl.DataFrame, path: Path) -> dict[str, Any]:
    df.write_parquet(path, compression="zstd", statistics=True)
    path.chmod(0o444)
    return {"rows": df.height, "sha256": _sha256(path)}


def _write_json(obj: Any, path: Path) -> None:
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    path.chmod(0o444)


def build(dataset_dir: Path, commission: execution.Commission | None = None) -> Path:
    commission = commission or execution.Commission()
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    spec = manifest["symbol_spec"]
    point = float(spec["point"])
    raw_dir = raw_root() / manifest["raw_version"]
    if _sha256(raw_dir / "manifest.json") != manifest["raw_manifest_sha256"]:
        raise RuntimeError("Raw manifest changed since the derived dataset was built")

    config = {
        "model_version": MODEL_VERSION,
        "quote_cap_seconds": ticks.QUOTE_CAP_SECONDS,
        "atr_bars": volatility.ATR_BARS,
        "vol_baseline_bars": volatility.BASELINE_BARS,
        "quantiles": spread.QUANTILES,
        "cell_levels": [list(lv) for lv in spread.LEVELS],
        "min_cell_minutes": spread.MIN_CELL_MINUTES,
        "current_days": spread.CURRENT_DAYS,
        "rollover_window_ny": spread.ROLLOVER_WINDOW_NY,
        "abnormal_norm_bars": spread.NORM_BARS,
        "holdout_share": validate.HOLDOUT_SHARE,
        "acceptance": validate.ACCEPTANCE,
        "scenarios": {k: asdict(v) for k, v in execution.SCENARIOS.items()},
        "commission": asdict(commission),
    }

    # ------------------------------------------------------------ inputs
    weekly = pl.read_parquet(dataset_dir / "clock_weekly.parquet")
    m1 = pl.read_parquet(dataset_dir / "M1.parquet", columns=["ts_utc", "ts_server", "spread_points"])
    m5 = pl.read_parquet(dataset_dir / "M5.parquet", columns=["ts_utc", "high", "low", "close"])
    window_start = datetime.fromisoformat(manifest["research_window_utc"][0])

    vol = volatility.m5_volatility(m5, point)
    edges = volatility.tercile_edges(vol, window_start)
    keys = spread.bar_keys(m1, vol, edges)
    log.info("M1 bars: %d · vol tercile edges %.3f / %.3f", keys.height, *edges)

    hist, tick_info = ticks.build_histogram(raw_dir, weekly, point)
    measured = ticks.minutes(hist)
    khist = spread.keyed_histogram(hist, keys)

    # ------------------------------------------------------------ validate, then fit on everything
    report = validate.validate(khist, measured, keys)
    log.info(
        "validation %s: level×ratio bias %.3f cov90 %.3f | abs-cells bias %.3f",
        "PASSED" if report["passed"] else "FAILED",
        report["models"]["level_x_ratio"]["relative_bias_p50"],
        report["models"]["level_x_ratio"]["coverage_p90"],
        report["models"]["abs_cells"]["relative_bias_p50"],
    )

    current = spread.current_window(khist)
    all_cells = pl.concat(
        [
            spread.cells(khist, "ratio", "full"),
            spread.cells(khist, "abs", "full"),
            spread.cells(current, "abs", "current"),
        ]
    )
    ratio_full = all_cells.filter((pl.col("basis") == "ratio") & (pl.col("window") == "full"))
    abs_current = all_cells.filter(pl.col("window") == "current")
    m1_costs = spread.flag_abnormal(spread.price_bars(keys, measured, ratio_full, abs_current))
    m5_costs = spread.to_m5(m1_costs)

    level_daily = (
        m1_costs.group_by(day=pl.col("ts_utc").dt.date())
        .agg(level_median=pl.col("spread_level").median(), bars=pl.len())
        .join(
            measured.group_by(day=pl.col("ts_utc").dt.date()).agg(
                measured_mean=(pl.col("spread_twmean") * pl.col("seconds")).sum() / pl.col("seconds").sum()
            ),
            on="day",
            how="left",
        )
        .sort("day")
    )

    # ------------------------------------------------------------ persist
    built = datetime.now(UTC)
    cost_model_id = f"{manifest['broker_server'].lower()}_c{built:%Y%m%dT%H%M%SZ}"
    out = dataset_dir / "costs" / cost_model_id
    out.mkdir(parents=True)
    files = {
        "M1_costs": _write(m1_costs, out / "M1_costs.parquet"),
        "M5_costs": _write(m5_costs, out / "M5_costs.parquet"),
        "spread_cells": _write(all_cells, out / "spread_cells.parquet"),
        "measured_minutes": _write(measured, out / "measured_minutes.parquet"),
        "level_daily": _write(level_daily, out / "level_daily.parquet"),
    }
    _write_json(report, out / "validation.json")
    files["validation"] = {"sha256": _sha256(out / "validation.json")}

    doc = {
        "cost_model_id": cost_model_id,
        "model_version": MODEL_VERSION,
        "dataset_id": manifest["dataset_id"],
        "raw_version": manifest["raw_version"],
        "broker": manifest["broker"],
        "broker_server": manifest["broker_server"],
        "price_side": manifest["price_side"],
        "built_utc": built.isoformat(),
        "code_version": code_version(),
        "config": config,
        "config_hash": config_hash(config),
        "tick_window": tick_info,
        "vol_tercile_edges": {"low_below": edges[0], "high_from": edges[1]},
        "validation": {k: report[k] for k in ("passed", "chosen_model", "acceptance", "models")},
        "summary": summarise(m1_costs, window_start),
        "execution": execution.describe(commission, spec),
        "symbol_spec": spec,
        "files": files,
    }
    _write_json(doc, out / "cost_model.json")
    _register(doc)
    return out


def summarise(m1_costs: pl.DataFrame, window_start: datetime) -> dict[str, Any]:
    b = m1_costs.filter(pl.col("ts_utc") >= window_start)
    scen = ["spread_optimistic", "spread_base", "spread_pessimistic"]

    def means(df: pl.DataFrame) -> dict[str, float]:
        return {c.removeprefix("spread_"): round(df[c].mean(), 2) for c in scen}

    last = b["ts_utc"].max()
    by_year = (
        b.group_by(year=pl.col("ts_utc").dt.year())
        .agg(*[pl.col(c).mean().round(2).alias(c.removeprefix("spread_")) for c in scen], bars=pl.len())
        .sort("year")
    )
    return {
        "bars": b.height,
        "measured_bars": int((b["spread_source"] == "measured").sum()),
        "measured_share": round(float((b["spread_source"] == "measured").mean()), 4),
        "level_imputed_bars": int(b["level_imputed"].sum()),
        "abnormal_spread_bars": int(b["abnormal_spread"].sum()),
        "rollover_window_bars": int(b["in_rollover_window"].sum()),
        "cell_level_share": {
            str(r["cell_level"]): round(r["share"], 4)
            for r in b.group_by("cell_level")
            .agg(share=pl.len() / b.height)
            .sort("cell_level")
            .iter_rows(named=True)
        },
        "mean_spread_points": {
            "research_window": means(b),
            "last_60_days": means(b.filter(pl.col("ts_utc") >= last - timedelta(days=60))),
            "by_year": by_year.to_dicts(),
        },
    }


def _register(doc: dict[str, Any]) -> None:
    """Best effort: files are the source of truth, the database is an index."""
    try:
        from sqlalchemy import text

        from candle_intel import db

        with db.engine().begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO ci.cost_models (cost_model_id, dataset_id, params)
                    VALUES (:id, :ds, CAST(:params AS JSONB))
                    ON CONFLICT (cost_model_id) DO NOTHING
                    """
                ),
                {
                    "id": doc["cost_model_id"],
                    "ds": f"{doc['dataset_id']}:M1",
                    "params": json.dumps({k: v for k, v in doc.items() if k != "files"}, default=str),
                },
            )
        log.info("registered in PostgreSQL")
    except Exception as e:  # noqa: BLE001 — DB is optional for a build
        log.warning("PostgreSQL registration skipped: %s", e)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="ci-costs", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--dataset", help="derived dataset id; default newest")
    b.add_argument("--commission-per-lot", type=float, default=0.0, help="round-turn USD per lot")
    b.add_argument(
        "--commission-confirmed", action="store_true", help="the commission is the account's actual one"
    )
    ls = sub.add_parser("list")
    ls.add_argument("--dataset")
    args = p.parse_args(argv)

    dataset_dir = derived_root() / args.dataset if args.dataset else latest_dataset()
    if args.cmd == "list":
        items = [
            json.loads((c / "cost_model.json").read_text(encoding="utf-8")) for c in cost_models(dataset_dir)
        ]
        print(
            json.dumps(
                [
                    {k: m[k] for k in ("cost_model_id", "dataset_id", "built_utc", "config_hash")}
                    | {"validation_passed": m["validation"]["passed"]}
                    for m in items
                ],
                indent=2,
            )
        )
        return 0

    commission = execution.Commission(
        per_lot_round_turn_usd=args.commission_per_lot, confirmed=args.commission_confirmed
    )
    out = build(dataset_dir, commission)
    doc = json.loads((out / "cost_model.json").read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                k: doc[k]
                for k in ("cost_model_id", "tick_window", "vol_tercile_edges", "validation", "summary")
            },
            indent=2,
            default=str,
        )
    )
    return 0 if doc["validation"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
