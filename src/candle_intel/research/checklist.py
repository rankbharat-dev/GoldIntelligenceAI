"""Blueprint §15 promotion checklist — every criterion, its value and why it failed.

Implementation reading (recorded in ARCHITECTURE §15 note, 2026-09-21):
- "Net expectancy / PF / drawdown at pessimistic costs" must hold on **both** tier A
  (development) and tier B (validation) — a result that only works in one is not stable.
- Stability, ambiguity and the Deflated Sharpe are measured on A∪B continuous. Stability =
  share of year / session buckets with *positive* expectancy (a consistently losing rule
  is "same-signed" but is not an edge).
- Deflated Sharpe gate is the literal "> 0": per-trade Sharpe above the expected
  maximum of the family's trial count (SR − SR0 > 0). Its probability is shown too.
- Holdout criteria stay *pending* until the family's one-time unseal.
There is no partial promotion: any failure → rejected; any pending → not yet a candidate.
"""

from __future__ import annotations

from typing import Any

T = {
    "expectancy_r": 0.10,
    "n_dev": 1000,
    "n_val": 250,
    "profit_factor": 1.15,
    "max_dd_r": 15.0,
    "max_dd_pct": 0.20,
    "stability": 0.70,
    "ambiguity": 0.05,
    "holdout_ratio": 0.5,
}


def _item(key: str, label: str, value: Any, threshold: str, ok: bool | None, why: str = "") -> dict[str, Any]:
    return {"key": key, "label": label, "value": value, "threshold": threshold, "passed": ok, "why": why}


def _ge(v: float | None, t: float) -> bool | None:
    return None if v is None else v >= t


def evaluate(
    a: dict | None, b: dict | None, ab: dict | None, c: dict | None, holdout_accesses: int
) -> dict[str, Any]:
    """Each argument is a run document (or None if not run yet); pessimistic results are used."""

    def p(doc: dict | None) -> dict[str, Any]:
        return (doc or {}).get("results", {}).get("pessimistic", {}) if doc else {}

    pa, pb, pab, pc = p(a), p(b), p(ab), p(c)
    items = []

    for tier, m in (("A", pa), ("B", pb)):
        e = m.get("expectancy_r")
        items.append(
            _item(
                f"expectancy_{tier}",
                f"Net expectancy, pessimistic — tier {tier}",
                e,
                "≥ +0.10 R",
                _ge(e, T["expectancy_r"]) if m else None,
                "" if m else f"tier {tier} not run",
            )
        )
    na, nb = pa.get("n"), pb.get("n")
    items.append(
        _item("n_dev", "Trades — development (A)", na, "≥ 1,000", _ge(na, T["n_dev"]) if pa else None)
    )
    items.append(_item("n_val", "Trades — validation (B)", nb, "≥ 250", _ge(nb, T["n_val"]) if pb else None))
    for tier, m in (("A", pa), ("B", pb)):
        pf = m.get("profit_factor")
        items.append(
            _item(
                f"pf_{tier}",
                f"Profit factor, pessimistic — tier {tier}",
                pf,
                "≥ 1.15",
                _ge(pf, T["profit_factor"]) if m else None,
            )
        )
    for tier, m in (("A", pa), ("B", pb)):
        dd, ddp = m.get("max_dd_r"), m.get("max_dd_pct")
        ok = None if not m else (dd is not None and dd <= T["max_dd_r"] and (ddp or 0) <= T["max_dd_pct"])
        items.append(
            _item(f"dd_{tier}", f"Max drawdown — tier {tier}", {"r": dd, "pct": ddp}, "≤ 15 R and ≤ 20 %", ok)
        )
    st = pab.get("stability", {}) if pab else {}
    for k in ("year", "session"):
        s = (st.get(k) or {}).get("score")
        items.append(
            _item(
                f"stability_{k}",
                f"Stability — {k} buckets with positive expectancy (A∪B)",
                s,
                "≥ 70 %",
                None if not pab else (s is not None and s >= T["stability"]),
                "" if pab else "A∪B not run",
            )
        )
    amb = pab.get("ambiguity_rate") if pab else None
    items.append(
        _item(
            "ambiguity",
            "Intrabar ambiguity rate (A∪B)",
            amb,
            "≤ 5 % or tick-verified",
            None if not pab else amb is not None and amb <= T["ambiguity"],
        )
    )
    dsr = (ab or {}).get("deflated_sharpe") or {}
    ex = dsr.get("deflated_excess")
    items.append(
        _item(
            "deflated_sharpe",
            f"Deflated Sharpe at {dsr.get('n_trials', '?')} trials (A∪B)",
            {"excess": ex, "probability": dsr.get("probability")},
            "SR − SR0 > 0",
            None if not ab else (ex is not None and ex > 0),
        )
    )
    ec, ea = pc.get("expectancy_r"), pa.get("expectancy_r")
    items.append(
        _item(
            "holdout",
            "Final holdout (C) expectancy",
            ec,
            "> 0 and ≥ 50 % of development",
            None
            if not pc
            else (ec is not None and ec > 0 and ea is not None and ec >= T["holdout_ratio"] * ea),
            "" if pc else "sealed — unseal once, after everything else passes",
        )
    )
    items.append(
        _item(
            "holdout_accesses",
            "Holdout accesses for this family",
            holdout_accesses,
            "exactly 1",
            None if holdout_accesses == 0 else holdout_accesses == 1,
        )
    )
    fails = [i for i in items if i["passed"] is False]
    pending = [i for i in items if i["passed"] is None]
    verdict = "rejected" if fails else "pending" if pending else "candidate"
    ready_to_unseal = not fails and all(i["key"] in ("holdout", "holdout_accesses") for i in pending)
    return {
        "verdict": verdict,
        "items": items,
        "failed": len(fails),
        "pending": len(pending),
        "ready_to_unseal": ready_to_unseal,
    }
