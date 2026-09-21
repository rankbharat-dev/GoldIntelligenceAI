"""ci-ingest — bulk XAUUSD pulls through the direct MT5 Python API.

    ci-ingest status                 connection + safety posture + symbol spec
    ci-ingest probe                  history depth per timeframe and tick window depth
    ci-ingest snapshot --tf M5 --days 30

Snapshots are raw, read-only Parquet with a JSON sidecar. They are not yet a
validated dataset version — that is the Phase 1 quality gate's job.
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

from candle_intel.config import CANONICAL_SYMBOL, RESEARCH_TIMEFRAMES, get_settings
from candle_intel.ingest import mt5_session

log = logging.getLogger("ci-ingest")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def _safety_warnings(info: mt5_session.SessionInfo) -> list[str]:
    warnings = []
    if info.account_mode != "demo":
        warnings.append(f"Account mode is {info.account_mode!r}, not demo.")
    if info.account_trading_permitted:
        warnings.append(
            "Session permits trading. Log in with the INVESTOR (read-only) password "
            "to make trading impossible at the broker."
        )
    if info.terminal_algo_trading_enabled:
        warnings.append("Terminal Algo Trading is ON. Turn it off for research sessions.")
    return warnings


def cmd_status(_: argparse.Namespace) -> int:
    with mt5_session.session() as info:
        out = {
            "session": asdict(info),
            "safety_warnings": _safety_warnings(info),
            "terminal_max_bars": mt5_session.max_bars() + 1,
            "symbol_spec": mt5_session.symbol_spec(),
            "latest_tick": mt5_session.latest_tick(),
            "settings": get_settings().redacted(),
        }
    print(json.dumps(out, indent=2, default=str))
    return 0


def _tick_depth_days(now: datetime, max_days: int = 1500) -> int:
    """Approximate days back for which a one-hour window still holds real ticks.

    Samples weekdays at doubling distances, then bisects. MT5 may return a single
    stale tick for an empty window, so 'has ticks' means more than 50 of them.
    """

    def has_ticks(days_back: int) -> bool:
        probe = (now - timedelta(days=days_back)).replace(hour=14, minute=0, second=0, microsecond=0)
        probe -= timedelta(days=max(0, probe.weekday() - 3))  # land on Mon-Thu
        return mt5_session.fetch_ticks_range(probe, probe + timedelta(hours=1)).height > 50

    if not has_ticks(0) and not has_ticks(1):
        return 0
    lo, hi = 1, 2
    while hi <= max_days and has_ticks(hi):
        lo, hi = hi, hi * 2
    hi = min(hi, max_days)
    while hi - lo > 3:
        mid = (lo + hi) // 2
        lo, hi = (mid, hi) if has_ticks(mid) else (lo, mid)
    return lo


def cmd_probe(_: argparse.Namespace) -> int:
    report: dict[str, Any] = {"symbol": CANONICAL_SYMBOL, "probed_at_utc": _utc_now().isoformat()}
    with mt5_session.session() as info:
        limit = mt5_session.max_bars()
        report["session"] = asdict(info)
        report["terminal_max_bars"] = limit + 1
        per_tf = {}
        for tf in RESEARCH_TIMEFRAMES:
            df = mt5_session.fetch_rates_latest(tf, limit)
            per_tf[tf] = {
                "bars": df.height,
                "earliest_ts_server": str(df["ts_server"].min()) if df.height else None,
                "latest_ts_server": str(df["ts_server"].max()) if df.height else None,
                # A full response means the terminal limit, not the server, cut it off.
                "capped_by_terminal_limit": df.height >= limit,
            }
        report["rates"] = per_tf
        report["tick_window_days_approx"] = _tick_depth_days(mt5_session.server_now())
    if any(v["capped_by_terminal_limit"] for v in report["rates"].values()):
        report["action_required"] = (
            "History is capped by the terminal's 'Max bars in chart' setting "
            "(Tools > Options > Charts). Set it to Unlimited, restart MT5, re-probe."
        )
    path = get_settings().storage_root / "reports" / f"coverage_{_utc_now():%Y%m%dT%H%M%SZ}.json"
    _write_json(path, report)
    print(json.dumps(report, indent=2, default=str))
    print(f"\nreport: {path}", file=sys.stderr)
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    s = get_settings()
    with mt5_session.session() as info:
        end = mt5_session.server_now() + timedelta(minutes=1)
        start = end - timedelta(days=args.days)
        df = mt5_session.fetch_rates_chunked(args.tf, start, end)
        df = mt5_session.mark_complete(df, args.tf)
        spec = mt5_session.symbol_spec()
    forming = df.filter(~pl.col("complete")).height
    df = df.filter(pl.col("complete")).drop("complete")  # raw stores closed bars only
    if df.is_empty():
        print("No bars returned.", file=sys.stderr)
        return 1

    stamp = f"{_utc_now():%Y%m%dT%H%M%SZ}"
    out_dir = s.storage_root / "raw" / "xauusd" / "snapshots" / args.tf
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet = out_dir / f"xauusd_{args.tf}_{stamp}.parquet"
    df.write_parquet(parquet, compression="zstd", statistics=True)
    parquet.chmod(0o444)  # raw is read-only after write

    meta = {
        "symbol": CANONICAL_SYMBOL,
        "broker_symbol": info.broker_symbol,
        "broker": info.terminal_company,
        "terminal_build": info.terminal_build,
        "account_mode": info.account_mode,
        "timeframe": args.tf,
        "price_side": "bid",
        "clock": "broker_server",
        "server_offset_hours_estimate": info.server_offset_hours,
        "request_window_ts_server": [start.isoformat(), end.isoformat()],
        "rows": df.height,
        "forming_bars_dropped": forming,
        "first_ts_server": str(df["ts_server"].min()),
        "last_ts_server": str(df["ts_server"].max()),
        "sha256": hashlib.sha256(parquet.read_bytes()).hexdigest(),
        "symbol_spec": spec,
        "created_utc": _utc_now().isoformat(),
    }
    _write_json(parquet.with_suffix(".json"), meta)
    print(json.dumps({k: v for k, v in meta.items() if k != "symbol_spec"}, indent=2))
    print(df.tail(5))
    return 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="ci-ingest", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("probe").set_defaults(fn=cmd_probe)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--tf", choices=list(RESEARCH_TIMEFRAMES), default="M5")
    snap.add_argument("--days", type=int, default=30)
    snap.set_defaults(fn=cmd_snapshot)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except mt5_session.MT5Error as e:
        print(f"MT5 error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
