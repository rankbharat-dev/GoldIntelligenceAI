"""V1 behaviour library (blueprint §17) and its pre-registration (§9.2).

Each behaviour is written down — side, exact conditions over feature-store columns,
triple-barrier horizon, minimum sample sizes, rule version — and stored in
``pattern_definitions`` with a timestamp **before** any outcome is computed. The
registration is immutable: a changed rule is a new id (``_v2``), so a result can
always be traced to a definition that existed before it.

Results for anything not registered are *exploratory* (Behaviour Explorer ad-hoc
studies) and cannot enter the promotion pipeline.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from candle_intel.features.compute import FEATURE_VERSION
from candle_intel.research.ledger import Ledger
from candle_intel.strategy.spec import Condition
from candle_intel.structure.geometry import STRUCTURE_VERSION

RULE_VERSION = f"{FEATURE_VERSION}+{STRUCTURE_VERSION}"
BARRIERS = {"target_atr": 1.5, "stop_atr": 1.0, "horizon_bars": 24}  # §8.1 defaults
MIN_SAMPLES = {"A": 1000, "B": 250, "C": 100}  # §11

GROUPS = {
    "momentum_continuation": "Momentum continuation",
    "breakout_retest": "Breakout + retest",
    "failed_breakout": "Failed breakout",
    "sr_rejection": "Support / resistance rejection",
    "liquidity_sweep": "Liquidity sweep with reclaim",
    "compression_expansion": "Volatility compression → expansion",
    "trendline": "Trendline / channel touch and break",
    "range_boundary": "Range boundary rejection",
}


def _c(feature: str, op: str, value: Any) -> dict[str, Any]:
    return {"feature": feature, "op": op, "value": value}


# (id, behaviour group, name, side, conditions, hypothesis)
LIBRARY: list[tuple[str, str, str, str, list[dict[str, Any]], str]] = [
    (
        "momentum_cont_long",
        "momentum_continuation",
        "Strong 5-bar push up, close near the high",
        "long",
        [_c("ret5_atr", ">=", 1.5), _c("close_loc", ">=", 0.7), _c("dir", "==", 1)],
        "After a strong push that closes near its high, price keeps going up.",
    ),
    (
        "momentum_cont_short",
        "momentum_continuation",
        "Strong 5-bar push down, close near the low",
        "short",
        [_c("ret5_atr", "<=", -1.5), _c("close_loc", "<=", 0.3), _c("dir", "==", -1)],
        "After a strong push that closes near its low, price keeps going down.",
    ),
    (
        "breakout_retest_long",
        "breakout_retest",
        "Retest of a broken swing high holds",
        "long",
        [_c("retest_up", "==", True)],
        "A broken swing high becomes support; a retest that holds continues up.",
    ),
    (
        "breakout_retest_short",
        "breakout_retest",
        "Retest of a broken swing low holds",
        "short",
        [_c("retest_down", "==", True)],
        "A broken swing low becomes resistance; a retest that holds continues down.",
    ),
    (
        "failed_breakout_short",
        "failed_breakout",
        "Breakout above a swing high fails",
        "short",
        [_c("failed_break_up", "==", True)],
        "A breakout that closes back below the level traps buyers and reverses down.",
    ),
    (
        "failed_breakout_long",
        "failed_breakout",
        "Breakdown below a swing low fails",
        "long",
        [_c("failed_break_down", "==", True)],
        "A breakdown that closes back above the level traps sellers and reverses up.",
    ),
    (
        "support_rejection_long",
        "sr_rejection",
        "Wick through a tested support, close back above",
        "long",
        [
            _c("sr_below_low_dist_atr", "<", 0),
            _c("sr_below_touches", ">=", 3),
            _c("lower_wick_frac", ">=", 0.4),
        ],
        "A support level touched 3+ times rejects a probe below it; price bounces.",
    ),
    (
        "resistance_rejection_short",
        "sr_rejection",
        "Wick through a tested resistance, close back below",
        "short",
        [
            _c("sr_above_high_dist_atr", "<", 0),
            _c("sr_above_touches", ">=", 3),
            _c("upper_wick_frac", ">=", 0.4),
        ],
        "A resistance level touched 3+ times rejects a probe above it; price falls.",
    ),
    (
        "sweep_low_reclaim_long",
        "liquidity_sweep",
        "Sweep below the last swing low, strong reclaim",
        "long",
        [_c("sweep_low", "==", True), _c("close_loc", ">=", 0.6)],
        "Stops below a swing low are taken and price reclaims the level; it moves up.",
    ),
    (
        "sweep_high_reject_short",
        "liquidity_sweep",
        "Sweep above the last swing high, strong rejection",
        "short",
        [_c("sweep_high", "==", True), _c("close_loc", "<=", 0.4)],
        "Stops above a swing high are taken and price falls back; it moves down.",
    ),
    (
        "compression_expansion_long",
        "compression_expansion",
        "Big up candle after compression",
        "long",
        [
            _c("compression", "<=", 0.7),
            _c("range_atr", ">=", 1.8),
            _c("body_frac", ">=", 0.6),
            _c("dir", "==", 1),
        ],
        "After quiet bars, a wide up candle starts an expansion move up.",
    ),
    (
        "compression_expansion_short",
        "compression_expansion",
        "Big down candle after compression",
        "short",
        [
            _c("compression", "<=", 0.7),
            _c("range_atr", ">=", 1.8),
            _c("body_frac", ">=", 0.6),
            _c("dir", "==", -1),
        ],
        "After quiet bars, a wide down candle starts an expansion move down.",
    ),
    (
        "trendline_bounce_long",
        "trendline",
        "Bounce on a rising trendline",
        "long",
        [_c("tl_up_dist_atr", "between", [0.0, 0.3]), _c("dir", "==", 1), _c("lower_wick_frac", ">=", 0.3)],
        "Price touching a rising trendline from above bounces along it.",
    ),
    (
        "trendline_bounce_short",
        "trendline",
        "Rejection at a falling trendline",
        "short",
        [_c("tl_dn_dist_atr", "between", [-0.3, 0.0]), _c("dir", "==", -1), _c("upper_wick_frac", ">=", 0.3)],
        "Price touching a falling trendline from below turns down along it.",
    ),
    (
        "trendline_break_long",
        "trendline",
        "Close above a falling trendline",
        "long",
        [_c("tl_dn_break", "==", True)],
        "Breaking a falling trendline ends the down-leg; price moves up.",
    ),
    (
        "trendline_break_short",
        "trendline",
        "Close below a rising trendline",
        "short",
        [_c("tl_up_break", "==", True)],
        "Breaking a rising trendline ends the up-leg; price moves down.",
    ),
    (
        "range_floor_long",
        "range_boundary",
        "Rejection at the floor of a sideways range",
        "long",
        [_c("sw_trend", "==", 0), _c("rng_pos", "<=", 0.15), _c("close_loc", ">=", 0.6)],
        "In a sideways swing structure, a rejection near the range low moves back up.",
    ),
    (
        "range_roof_short",
        "range_boundary",
        "Rejection at the roof of a sideways range",
        "short",
        [_c("sw_trend", "==", 0), _c("rng_pos", ">=", 0.85), _c("close_loc", "<=", 0.4)],
        "In a sideways swing structure, a rejection near the range high moves back down.",
    ),
]


def definition(side: str, conditions: list[dict[str, Any]], barriers: dict[str, Any] | None = None) -> dict:
    """The part of a behaviour that decides its outcomes (validated conditions)."""
    for c in conditions:
        Condition.model_validate(c)
    return {"side": side, "conditions": conditions, "barriers": barriers or dict(BARRIERS)}


def definition_hash(d: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]


def _register(
    ledger: Ledger,
    slug: str,
    name: str,
    behaviour: str,
    side: str,
    conds: list,
    hyp: str,
    barriers: dict[str, Any] | None,
    created_by: str,
) -> dict[str, Any]:
    d = definition(side, conds, barriers)
    rule = d | {
        "name": name[:120],
        "behaviour": behaviour if behaviour in GROUPS else "custom",
        "hypothesis": hyp,
        "rule_version": RULE_VERSION,
        "created_by": created_by,
        "definition_hash": definition_hash(d),
    }
    return ledger.register_pattern(
        slug, rule, hyp, side, int(d["barriers"]["horizon_bars"]), MIN_SAMPLES["A"], MIN_SAMPLES["B"]
    )


def ensure_registered(ledger: Ledger) -> list[dict[str, Any]]:
    """Pre-register the V1 library (idempotent: an unchanged rule keeps its first row)."""
    for slug, group, name, side, conds, hyp in LIBRARY:
        _register(ledger, slug, name, group, side, conds, hyp, None, "owner")
    return ledger.patterns()


def register_custom(
    ledger: Ledger,
    slug: str,
    name: str,
    behaviour: str,
    side: str,
    conditions: list[dict[str, Any]],
    hypothesis: str,
    barriers: dict[str, Any] | None = None,
    created_by: str = "owner",
) -> dict[str, Any]:
    """A new hypothesis, or a new version of ``slug`` if its rule changed."""
    return _register(ledger, slug, name, behaviour, side, conditions, hypothesis, barriers, created_by)
