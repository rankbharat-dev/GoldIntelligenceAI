"""ci-data — turn a raw MT5 dataset into a validated, UTC, multi-timeframe dataset.

    ci-data build [--raw <raw_version>]     default: newest raw version
    ci-data list

Output: storage/derived/xauusd/<dataset_id>/
    M1.parquet M5.parquet M15.parquet H1.parquet   (read-only)
    clock_weekly.parquet                            broker offset per ISO week
    quality.json                                    full quality-gate report
    manifest.json                                   lineage, versions, hashes, verification

Reads raw Parquet only; never contacts MT5.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from candle_intel.config import get_settings
from candle_intel.data import aggregate, clock, quality
from candle_intel.provenance import code_version, config_hash

log = logging.getLogger("ci-data")

TIMEFRAMES = ("M1", "M5", "M15", "H1")
BUILD_CONFIG = {
    "clock": {
        "anchor": "17:00 America/New_York",
        "min_days_per_week": clock.MIN_DAYS_PER_WEEK,
        "min_agreement": clock.MIN_AGREEMENT,
    },
    "quality": {
        "jump_range_multiple": quality.JUMP_RANGE_MULTIPLE,
        "jump_gap_multiple": quality.JUMP_GAP_MULTIPLE,
        "rolling_bars": quality.ROLLING_BARS,
        "daily_break_ny_window": quality.DAILY_BREAK_NY_WINDOW,
    },
    "aggregation": {"label": "left", "closed": "left", "anchor": "ts_utc"},
}


def raw_root() -> Path:
    return get_settings().storage_root / "raw" / "xauusd"


def derived_root() -> Path:
    return get_settings().storage_root / "derived" / "xauusd"


def latest_raw() -> Path:
    versions = sorted(p for p in raw_root().iterdir() if (p / "manifest.json").exists())
    if not versions:
        raise FileNotFoundError("No raw dataset. Run: ci-ingest raw")
    return versions[-1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(df: pl.DataFrame, path: Path) -> dict[str, Any]:
    df.write_parquet(path, compression="zstd", statistics=True)
    path.chmod(0o444)
    return {"rows": df.height, "sha256": _sha256(path)}


def build(raw_dir: Path) -> Path:
    raw_manifest = json.loads((raw_dir / "manifest.json").read_text(encoding="utf-8"))
    for c in raw_manifest["m1_chunks"]:  # raw must be exactly what was ingested
        if _sha256(raw_dir / "m1" / c["file"]) != c["sha256"]:
            raise RuntimeError(f"Raw chunk {c['file']} does not match its manifest hash")

    m1 = pl.read_parquet(raw_dir / "m1" / "*.parquet").sort("ts_server")
    log.info("M1 bars: %d", m1.height)

    clk = clock.infer_clock(m1)
    m1 = clock.to_utc(m1, clk)
    report = quality.run(m1)
    if not report["passed"]:
        raise RuntimeError(f"Blocking quality failures: {report['blocking']}")

    built = datetime.now(UTC)
    dataset_id = f"xauusd_{raw_manifest['session']['broker_server'].lower()}_d{built:%Y%m%dT%H%M%SZ}"
    out = derived_root() / dataset_id
    out.mkdir(parents=True)

    files = {"M1": _write(m1, out / "M1.parquet")}
    verification = {}
    for tf in ("M5", "M15", "H1"):
        bars = aggregate.aggregate(m1, tf)
        files[tf] = _write(bars, out / f"{tf}.parquet")
        native = pl.read_parquet(raw_dir / "reference" / f"{tf}.parquet")
        verification[tf] = aggregate.verify_against_reference(bars, native)
        log.info(
            "%s: %d bars, match vs broker %.4f", tf, bars.height, verification[tf]["ohlc_match_rate"] or 0
        )
    _write(clk.weekly, out / "clock_weekly.parquet")
    (out / "quality.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    session = raw_manifest["session"]
    manifest = {
        "dataset_id": dataset_id,
        "symbol": raw_manifest["symbol"],
        "raw_version": raw_manifest["raw_version"],
        "raw_manifest_sha256": _sha256(raw_dir / "manifest.json"),
        "broker": session["broker_company"],
        "broker_server": session["broker_server"],
        "broker_symbol": session["broker_symbol"],
        "price_side": "bid",
        "clock": "utc (ts_utc); broker clock kept as ts_server",
        "clock_model": clk.summary(),
        "files": files,
        "verification_vs_broker": verification,
        "quality_passed": report["passed"],
        "research_window_utc": report["coverage"]["research_window_utc"],
        "config": BUILD_CONFIG,
        "config_hash": config_hash(BUILD_CONFIG),
        "code_version": code_version(),
        "symbol_spec": raw_manifest["symbol_spec"],
        "built_utc": built.isoformat(),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    _register(raw_dir, raw_manifest, out, manifest, report)
    return out


def _register(raw_dir: Path, raw_manifest: dict, out: Path, manifest: dict, report: dict) -> None:
    """Best effort: files are the source of truth, the database is an index."""
    try:
        from candle_intel import db

        session = raw_manifest["session"]
        common = {
            "broker": session["broker_company"],
            "broker_server": session["broker_server"],
            "broker_symbol": session["broker_symbol"],
        }
        with db.engine().begin() as conn:
            m1_first, m1_last = raw_manifest["m1_window_ts_server"]
            db.register_dataset(
                conn,
                {
                    "dataset_id": raw_manifest["raw_version"],
                    "timeframe": "M1",
                    "first_ts_server": m1_first,
                    "last_ts_server": m1_last,
                    "row_count": sum(c["rows"] for c in raw_manifest["m1_chunks"]),
                    "parquet_path": str(raw_dir),
                    "sha256": manifest["raw_manifest_sha256"],
                    **common,
                },
            )
            for tf in TIMEFRAMES:
                df = pl.read_parquet(out / f"{tf}.parquet", columns=["ts_server"])
                db.register_dataset(
                    conn,
                    {
                        "dataset_id": f"{manifest['dataset_id']}:{tf}",
                        "timeframe": tf,
                        "first_ts_server": df["ts_server"].min(),
                        "last_ts_server": df["ts_server"].max(),
                        "row_count": df.height,
                        "parquet_path": str(out / f"{tf}.parquet"),
                        "sha256": manifest["files"][tf]["sha256"],
                        "parent_dataset_id": raw_manifest["raw_version"],
                        "config_hash": manifest["config_hash"],
                        **common,
                    },
                )
            db.register_quality_run(conn, f"{manifest['dataset_id']}:M1", report)
            db.register_symbol_spec(
                conn, session["broker_company"], session["broker_symbol"], raw_manifest["symbol_spec"]
            )
        log.info("registered in PostgreSQL")
    except Exception as e:  # noqa: BLE001 — DB is optional for a build
        log.warning("PostgreSQL registration skipped: %s", e)


def list_datasets() -> list[dict[str, Any]]:
    root = derived_root()
    if not root.exists():
        return []
    items = []
    for p in sorted(root.iterdir()):
        mf = p / "manifest.json"
        if mf.exists():
            m = json.loads(mf.read_text(encoding="utf-8"))
            items.append(
                {
                    "dataset_id": m["dataset_id"],
                    "broker_server": m["broker_server"],
                    "research_window_utc": m["research_window_utc"],
                    "built_utc": m["built_utc"],
                }
            )
    return items


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="ci-data", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--raw", help="raw version directory name; default newest")
    sub.add_parser("list")
    args = p.parse_args(argv)

    if args.cmd == "list":
        print(json.dumps(list_datasets(), indent=2))
        return 0
    raw_dir = raw_root() / args.raw if args.raw else latest_raw()
    out = build(raw_dir)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    q = json.loads((out / "quality.json").read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "dataset_id": m["dataset_id"],
                "rows": {k: v["rows"] for k, v in m["files"].items()},
                "clock_model": m["clock_model"],
                "verification_vs_broker": {
                    k: v["ohlc_match_rate"] for k, v in m["verification_vs_broker"].items()
                },
                "quality_passed": q["passed"],
                "gaps": q["gaps"],
                "daily_break_ny": q["daily_break_ny"],
                "price_anomalies": q["price_anomalies"]["count"],
                "spread_points": q["spread_points"],
                "coverage": q["coverage"],
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
