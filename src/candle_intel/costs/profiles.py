"""Account cost profiles (MASTER_PROMPT §5, §7; roadmap Phase 9).

A cost model belongs to one **account profile**:

    demo_trial7   the Exness-MT5Trial7 demo the bars and ticks come from (standard-type
                  account: spread includes the broker's markup, no commission)
    raw           the Exness **Raw Spread** account the owner will trade (near-zero
                  spread + commission per lot)

A Raw model has one of two statuses:

    provisional   no Raw-account ticks yet (open item A7). Spreads are copied from the
                  demo model — an *upper bound*, since a Raw account's spread is the
                  demo's minus the markup — and the commission is the owner's figure.
                  Anything that survives it would survive the real Raw account; it can
                  still not promote (the promotion profile must be calibrated).
    validated     calibrated from a Raw demo account's own ticks (``ci-costs build
                  --profile raw --raw-ticks <raw_version>``) and passed the Phase 2
                  out-of-sample acceptance test.

The *active* profile (Data Center switch) is what new backtests, studies and searches
use; every run records its cost model id, profile and status.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from candle_intel.config import get_settings
from candle_intel.costs import execution

DEFAULT_PROFILE = "demo_trial7"
PROFILES = {
    "demo_trial7": "Exness-MT5Trial7 demo (standard-type: spread incl. markup, no commission)",
    "raw": "Exness Raw Spread (near-zero spread + commission) — the account the owner will trade",
}
PROMOTION_PROFILE = "raw"  # MASTER_PROMPT §5: promotion uses the account that will trade
OWNER_RAW_COMMISSION_USD = 10.0  # owner, 2026-09-21: "exness raw ka 10 usd maan ke chalo 1 lot ka"
COPIED_FILES = (
    "M1_costs.parquet",
    "M5_costs.parquet",
    "spread_cells.parquet",
    "measured_minutes.parquet",
    "level_daily.parquet",
    "validation.json",
)


def _doc(model_dir: Path) -> dict[str, Any]:
    return json.loads((model_dir / "cost_model.json").read_text(encoding="utf-8"))


def profile_of(doc: dict[str, Any]) -> tuple[str, str]:
    """(profile, status) of a cost model document; models built before profiles existed
    are the demo account's own, validated if their validation passed."""
    profile = doc.get("profile", DEFAULT_PROFILE)
    status = doc.get("status") or (
        "validated" if doc.get("validation", {}).get("passed") else "failed_validation"
    )
    return profile, status


def models(dataset_dir: Path) -> list[Path]:
    root = dataset_dir / "costs"
    if not root.exists():
        return []
    return sorted(
        (p for p in root.iterdir() if (p / "cost_model.json").exists()), key=lambda p: _doc(p)["built_utc"]
    )


def newest(dataset_dir: Path, profile: str = DEFAULT_PROFILE) -> Path | None:
    """Newest cost model of a profile; a validated one is preferred over a provisional one."""
    cands = [(p, profile_of(_doc(p))) for p in models(dataset_dir)]
    mine = [(p, st) for p, (pr, st) in cands if pr == profile]
    if not mine:
        return None
    validated = [p for p, st in mine if st == "validated"]
    return validated[-1] if validated else mine[-1][0]


def listing(dataset_dir: Path) -> list[dict[str, Any]]:
    out = []
    for name, label in PROFILES.items():
        m = newest(dataset_dir, name)
        if m is None:
            out.append({"profile": name, "label": label, "status": "missing", "cost_model_id": None})
            continue
        d = _doc(m)
        c = d["execution"]["commission"]
        summ = d.get("summary", {}).get("mean_spread_points", {})
        out.append(
            {
                "profile": name,
                "label": label,
                "status": profile_of(d)[1],
                "cost_model_id": d["cost_model_id"],
                "built_utc": d["built_utc"],
                "commission_round_turn_usd": c["per_lot_round_turn_usd"],
                "commission_confirmed": c["confirmed"],
                "spread_basis": d.get("spread_basis", "measured on this account's ticks"),
                "mean_spread_points_last_60_days": summ.get("last_60_days"),
                "validation_passed": d.get("validation", {}).get("passed"),
                "tick_source_raw_version": d.get("tick_source_raw_version"),
            }
        )
    return out


# ---------------------------------------------------------------- active profile (Data Center switch)


def _active_path() -> Path:
    return get_settings().storage_root / "research" / "cost_profile.json"


def active() -> str:
    try:
        return json.loads(_active_path().read_text(encoding="utf-8"))["profile"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return DEFAULT_PROFILE


def set_active(profile: str, dataset_dir: Path) -> dict[str, Any]:
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}")
    if newest(dataset_dir, profile) is None:
        raise FileNotFoundError(f"no cost model for profile {profile!r} yet")
    p = _active_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {"profile": profile, "set_utc": datetime.now(UTC).isoformat()}
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


# ---------------------------------------------------------------- provisional Raw profile


def build_provisional_raw(dataset_dir: Path, commission_usd: float = OWNER_RAW_COMMISSION_USD) -> Path:
    """A Raw profile before any Raw-account ticks exist: the demo model's spread tables
    (upper bound) + the owner's commission, applied in every scenario (it is a stated
    account term, not a guess). Status ``provisional``: never the promotion basis."""
    base = newest(dataset_dir, DEFAULT_PROFILE)
    if base is None:
        raise FileNotFoundError("build the demo cost model first: ci-costs build")
    bdoc = _doc(base)
    built = datetime.now(UTC)
    cid = f"{bdoc['broker_server'].lower()}_rawprov_c{built:%Y%m%dT%H%M%SZ}"
    out = dataset_dir / "costs" / cid
    out.mkdir(parents=True)
    for f in COPIED_FILES:
        shutil.copyfile(base / f, out / f)
        (out / f).chmod(0o444)
    commission = execution.Commission(per_lot_round_turn_usd=commission_usd, confirmed=True)
    doc = bdoc | {
        "cost_model_id": cid,
        "built_utc": built.isoformat(),
        "profile": "raw",
        "account_label": "raw",
        "status": "provisional",
        "spread_basis": (
            f"copied from demo model {bdoc['cost_model_id']} as an upper bound — Raw-account spreads are "
            "not measured yet (open item A7)"
        ),
        "spread_source_model": bdoc["cost_model_id"],
        "commission_source": f"owner, 2026-09-21: USD {commission_usd:g} per lot round turn (Exness Raw)",
        "execution": execution.describe(commission, bdoc["symbol_spec"]),
    }
    p = out / "cost_model.json"
    p.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    p.chmod(0o444)
    return out
