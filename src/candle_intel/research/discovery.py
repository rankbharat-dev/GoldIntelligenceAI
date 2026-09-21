"""Research engine — automated strategy search inside the §9 / §15 guardrails (Phase 8).

A **search** is a pre-registered space of hypotheses: entry building blocks (registered
behaviours or owner-written conditions) × filters (session, volatility regime, H1
structure alignment) × exits (stop, target, time). Every hypothesis is one strategy spec
in the search's family, written to ``research_hypotheses`` **before** it is tested.

Stages, each recorded with reasons:

1. **Screen (tier A only).** Each hypothesis is backtested on tier A at pessimistic
   costs and counted as a trial on the family. Rejected if it trades less than the
   screen floor or loses after costs.
   Methods: ``grid`` (every combination, sampled down to the budget), ``random``
   (uniform sample), ``evolutionary`` (generations of the best, mutated and crossed —
   each child registered before it is run).
2. **Validate (top K).** The best screened hypotheses go through the full Validate
   run (tiers A, B, A∪B, walk-forward, Deflated Sharpe at the family's true trial
   count, the §15 checklist). Any failed criterion rejects with its name; one with
   nothing failed but the sealed holdout pending becomes a **candidate**.
3. Everything else is ``not_selected`` (screened fine but ranked below top K).

Tier C is never touched: a candidate still needs the owner's one-time unseal.
The trial counter raises the bar as the search grows: SR0 (the best Sharpe expected
from luck alone) is reported with the family's trial count.

Pause / resume: the job checks the search's control flag between hypotheses; state
lives in the ledger, so a paused or interrupted search resumes where it stopped.
"""

from __future__ import annotations

import itertools
import random
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator

from candle_intel.backtest import engine, metrics
from candle_intel.backtest.market import Market
from candle_intel.research import runs, validate
from candle_intel.research.ledger import Ledger
from candle_intel.statistics import robust
from candle_intel.strategy.spec import Condition, StrategySpec

Progress = Callable[[float, str], None]
SCREEN_SCENARIO = "pessimistic"
POPULATION = 16


class Block(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Annotated[str, Field(min_length=1, max_length=80)]
    side: Literal["long", "short"]
    conditions: Annotated[list[dict[str, Any]], Field(min_length=1, max_length=8)]
    pattern_id: str | None = None

    @field_validator("conditions")
    @classmethod
    def _valid(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for c in v:
            Condition.model_validate(c)
        return v


Sessions = list[Literal["asian", "london", "new_york", "london_ny_overlap", "off"]] | None
Regimes = list[Literal["low", "mid", "high"]] | None


class SearchSpace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=3, max_length=120)]
    family: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_\-]{2,59}$")]
    hypothesis: str = ""
    blocks: Annotated[list[Block], Field(min_length=1, max_length=40)]
    sessions: Annotated[list[Sessions], Field(min_length=1, max_length=8)] = [None]
    vol_regimes: Annotated[list[Regimes], Field(min_length=1, max_length=6)] = [None]
    htf_align: Annotated[list[bool], Field(min_length=1, max_length=2)] = [False]
    stop_atr: Annotated[list[Annotated[float, Field(gt=0, le=20)]], Field(min_length=1, max_length=8)] = [1.0]
    target_atr: Annotated[list[Annotated[float, Field(gt=0, le=50)]], Field(min_length=1, max_length=8)] = [
        1.5
    ]
    time_exit_bars: Annotated[
        list[Annotated[int, Field(ge=1, le=2016)]], Field(min_length=1, max_length=8)
    ] = [24]
    method: Literal["grid", "random", "evolutionary"] = "grid"
    max_trials: Annotated[int, Field(ge=1, le=600)] = 120
    max_minutes: Annotated[int, Field(ge=1, le=720)] = 60
    min_trades_a: Annotated[int, Field(ge=10, le=5000)] = 300
    top_k: Annotated[int, Field(ge=0, le=10)] = 3
    seed: int = 7

    def axes(self) -> list[int]:
        return [
            len(self.blocks),
            len(self.sessions),
            len(self.vol_regimes),
            len(self.htf_align),
            len(self.stop_atr),
            len(self.target_atr),
            len(self.time_exit_bars),
        ]

    def space_size(self) -> int:
        return int(np.prod(self.axes()))


Gene = tuple[int, int, int, int, int, int, int]


def spec_of(space: SearchSpace, gene: Gene, created_by: str = "engine") -> StrategySpec:
    b, s, v, h, st, tg, te = gene
    block = space.blocks[b]
    conds = list(block.conditions)
    if space.htf_align[h]:
        conds.append({"feature": "h1_sw_trend", "op": "==", "value": 1 if block.side == "long" else -1})
    return StrategySpec.model_validate(
        {
            "meta": {
                "name": label_of(space, gene)[:80],
                "family": space.family,
                "hypothesis": space.hypothesis,
                "created_by": created_by,
                "preregistration_id": block.pattern_id,
            },
            "entries": [{"side": block.side, "conditions": conds}],
            "filters": {"sessions": space.sessions[s], "vol_regimes": space.vol_regimes[v]},
            "exit": {
                "stop_atr": space.stop_atr[st],
                "target_atr": space.target_atr[tg],
                "time_exit_bars": space.time_exit_bars[te],
                "flat_before_weekend": True,
            },
        }
    )


def label_of(space: SearchSpace, gene: Gene) -> str:
    b, s, v, h, st, tg, te = gene
    parts = [space.blocks[b].label]
    if space.sessions[s]:
        parts.append("/".join(space.sessions[s]))  # type: ignore[arg-type]
    if space.vol_regimes[v]:
        parts.append("vol " + "/".join(space.vol_regimes[v]))  # type: ignore[arg-type]
    if space.htf_align[h]:
        parts.append("H1-aligned")
    parts.append(f"S{space.stop_atr[st]:g}/T{space.target_atr[tg]:g}/{space.time_exit_bars[te]}b")
    return " · ".join(parts)


def _hyp(space: SearchSpace, gene: Gene, seq: int, generation: int = 0) -> dict[str, Any]:
    spec = spec_of(space, gene)
    return {
        "spec_hash": spec.spec_hash,
        "seq": seq,
        "generation": generation,
        "gene": list(gene),
        "label": label_of(space, gene)[:200],
        "spec": spec.model_dump(mode="json"),
        "status": "planned",
        "reasons": [],
        "metrics": {},
        "validate_run": None,
    }


def initial_genes(space: SearchSpace) -> list[Gene]:
    rng = random.Random(space.seed)  # noqa: S311 - reproducible sampling, not security
    axes = space.axes()
    if space.method == "grid" and space.space_size() <= 100_000:
        allg = list(itertools.product(*[range(n) for n in axes]))
        if len(allg) > space.max_trials:  # the budget is smaller than the grid: an even sample
            allg = rng.sample(allg, space.max_trials)
            allg.sort()
        return [tuple(g) for g in allg]  # type: ignore[misc]
    n = space.max_trials if space.method != "evolutionary" else min(POPULATION, space.max_trials)
    n = min(n, space.space_size())
    seen: set[Gene] = set()
    while len(seen) < n:
        seen.add(tuple(rng.randrange(k) for k in axes))  # type: ignore[arg-type]
    return sorted(seen)


def create(
    space: SearchSpace,
    ledger: Ledger,
    mode: Literal["auto", "approve"] = "approve",
    created_by: str = "owner",
) -> dict[str, Any]:
    """Register the search and its first hypotheses (pre-registration, §9.2)."""
    sid = f"se_{datetime.now(UTC):%Y%m%dT%H%M%S}_{secrets.token_hex(3)}"
    genes = initial_genes(space)
    hyps, seen = [], set()
    for g in genes:
        h = _hyp(space, g, len(hyps))
        if h["spec_hash"] not in seen:  # two genes can make the same rules (e.g. align on a no-op)
            seen.add(h["spec_hash"])
            hyps.append(h)
    ledger.search_create(
        {
            "search_id": sid,
            "name": space.name,
            "family": space.family,
            "definition": space.model_dump(mode="json"),
            "mode": mode,
            "status": "proposed",
            "summary": {"space_size": space.space_size(), "registered": len(hyps)},
            "created_by": created_by,
        },
        hyps,
    )
    return ledger.search(sid) or {}


# ---------------------------------------------------------------- running


class Paused(Exception):
    pass


def _screen(spec: StrategySpec, mk: Market, ledger: Ledger, min_trades: int) -> tuple[str, list[str], dict]:
    trades, _ = engine.run(spec, mk, "A", (SCREEN_SCENARIO,))
    m = metrics.summarise(trades, spec.sizing.initial_equity_usd)
    n_trials = ledger.record_trial(
        spec.meta.family, spec.spec_hash, "A", m.get("sharpe_per_trade"), m["n"], "engine"
    )
    keep = ("n", "expectancy_r", "profit_factor", "max_dd_r", "win_rate", "sharpe_per_trade", "total_r")
    met = {k: m.get(k) for k in keep} | {
        "expectancy_before_costs_r": m.get("expectancy_before_costs_r"),
        "family_trials_after": n_trials,
    }
    reasons = []
    if m["n"] < min_trades:
        reasons.append(f"screen: {m['n']} trades on tier A < {min_trades} (screen floor)")
    e = m.get("expectancy_r")
    if e is None or e <= 0:
        reasons.append(
            f"screen: expectancy {e if e is not None else '—'} R ≤ 0 after pessimistic costs on tier A"
        )
    return ("rejected" if reasons else "passed_screen"), reasons, met


def _score(h: dict[str, Any]) -> float:
    e = (h.get("metrics") or {}).get("expectancy_r")
    return -1e9 if e is None else float(e)


def _children(space: SearchSpace, parents: list[Gene], rng: random.Random, n: int) -> list[Gene]:
    axes = space.axes()
    out: list[Gene] = []
    for _ in range(n * 4):
        if len(out) >= n:
            break
        a = list(rng.choice(parents))
        if len(parents) > 1 and rng.random() < 0.5:  # crossover
            b = rng.choice(parents)
            a = [a[i] if rng.random() < 0.5 else b[i] for i in range(len(a))]
        i = rng.randrange(len(a))  # mutation of one gene
        if axes[i] > 1:
            a[i] = (a[i] + rng.choice([-1, 1])) % axes[i]
        out.append(tuple(a))  # type: ignore[arg-type]
    return out


def run(search_id: str, mk: Market, ledger: Ledger, progress: Progress | None = None) -> dict[str, Any]:
    rec = ledger.search(search_id)
    if rec is None:
        raise KeyError(search_id)
    space = SearchSpace.model_validate(rec["definition"])
    t0 = time.monotonic()
    ledger.search_update(search_id, status="running", started_at=rec["started_at"] or datetime.now(UTC))
    rng = random.Random(space.seed + 1)  # noqa: S311 - reproducible evolution, not security
    note = ""

    def check_pause() -> None:
        r = ledger.search(search_id)
        if r and r["control"] == "pause":
            raise Paused

    try:
        generation = max((h["generation"] for h in ledger.hypotheses(search_id)), default=0)
        while True:
            todo = [h for h in ledger.hypotheses(search_id) if h["status"] == "planned"]
            done_n = len(ledger.hypotheses(search_id)) - len(todo)
            for h in todo:
                check_pause()
                if time.monotonic() - t0 > space.max_minutes * 60:
                    note = "time budget reached"
                    break
                if progress:
                    progress(
                        min(0.8, 0.8 * done_n / max(space.max_trials, 1)),
                        f"screening {done_n + 1}/{space.max_trials}: {h['label'][:80]}",
                    )
                spec = StrategySpec.model_validate(h["spec"])
                runs.save_spec(spec, ledger)
                status, reasons, met = _screen(spec, mk, ledger, space.min_trades_a)
                ledger.hypothesis_update(
                    search_id, h["spec_hash"], status=status, reasons=reasons, metrics=met
                )
                done_n += 1
            if note:
                break
            allh = ledger.hypotheses(search_id)
            if space.method != "evolutionary" or len(allh) >= space.max_trials:
                break
            # next generation: children of the best half, registered before they run
            ranked = sorted(allh, key=_score, reverse=True)
            parents = [tuple(h["gene"]) for h in ranked[: max(2, len(ranked) // 4)]]
            generation += 1
            want = min(POPULATION, space.max_trials - len(allh))
            known = {h["spec_hash"] for h in allh}
            kids: list[dict[str, Any]] = []
            for g in _children(space, parents, rng, want * 3):
                k = _hyp(space, g, len(allh) + len(kids), generation)
                if k["spec_hash"] not in known and len(kids) < want:
                    known.add(k["spec_hash"])
                    kids.append(k)
            if not ledger.hypotheses_add(search_id, kids):
                note = "evolution converged (no new hypotheses)"
                break

        # ------------------------------------------------------------ stage 2: validate the top K
        allh = ledger.hypotheses(search_id)
        passed = sorted([h for h in allh if h["status"] == "passed_screen"], key=_score, reverse=True)
        for i, h in enumerate(passed):
            check_pause()
            if i >= space.top_k:
                ledger.hypothesis_update(
                    search_id,
                    h["spec_hash"],
                    status="not_selected",
                    reasons=[f"ranked below the top {space.top_k} on tier A"],
                )
                continue
            if progress:
                progress(
                    0.8 + 0.18 * i / max(space.top_k, 1),
                    f"validating {i + 1}/{min(space.top_k, len(passed))}",
                )
            spec = StrategySpec.model_validate(h["spec"])
            doc = validate.validate(spec, mk, ledger)
            chk = doc["checklist"]
            failed = [
                f"{it['label']}: {_fmt(it['value'])} (needs {it['threshold']})"
                for it in chk["items"]
                if it["passed"] is False
            ]
            status = "rejected" if failed else "candidate" if chk.get("passes_pre_holdout") else "rejected"
            waiting = [it["label"] for it in chk["items"] if it["passed"] is None]
            reasons = failed or [
                "passes every criterion checked so far; still pending: " + "; ".join(waiting)
                if status == "candidate"
                else "pending: " + "; ".join(waiting)
            ]
            met = dict(h["metrics"]) | {
                "B_expectancy_r": doc["tiers"]["B"]["pessimistic"].get("expectancy_r"),
                "B_n": doc["tiers"]["B"]["pessimistic"].get("n"),
                "oos_expectancy_r": doc["walk_forward"]["oos"].get("expectancy_r"),
                "deflated_excess": (doc.get("deflated_sharpe") or {}).get("deflated_excess"),
                "verdict": chk["verdict"],
            }
            ledger.hypothesis_update(
                search_id,
                h["spec_hash"],
                status=status,
                reasons=reasons,
                metrics=met,
                validate_run=doc["run_id"],
            )
    except Paused:
        ledger.search_update(search_id, status="paused", control="", summary=summarise(search_id, ledger))
        return {"run_id": search_id, "paused": True}
    except Exception:
        ledger.search_update(search_id, status="failed", summary=summarise(search_id, ledger))
        raise
    summ = summarise(search_id, ledger) | ({"note": note} if note else {})
    ledger.search_update(search_id, status="done", finished_at=datetime.now(UTC), summary=summ)
    if progress:
        progress(1.0, "done")
    return {"run_id": search_id}


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.3f}"
    if isinstance(v, dict):
        return ", ".join(f"{k} {_fmt(x)}" for k, x in v.items() if x is not None)
    return str(v)


def summarise(search_id: str, ledger: Ledger) -> dict[str, Any]:
    rec = ledger.search(search_id) or {}
    allh = ledger.hypotheses(search_id)
    counts: dict[str, int] = {}
    for h in allh:
        counts[h["status"]] = counts.get(h["status"], 0) + 1
    n_trials, sharpes = ledger.trials(rec.get("family", ""))
    finite = [s for s in sharpes if s is not None and np.isfinite(s)]
    var = float(np.var(finite, ddof=1)) if len(finite) >= 2 else 0.0
    best = max(allh, key=_score) if allh else None
    return {
        "space_size": (rec.get("summary") or {}).get("space_size"),
        "registered": len(allh),
        "counts": counts,
        "family_trials": n_trials,
        "sr0_expected_max": round(robust.expected_max_sharpe(n_trials, var), 5) if var > 0 else None,
        "best": {"label": best["label"], "metrics": best["metrics"], "status": best["status"]}
        if best
        else None,
        "candidates": counts.get("candidate", 0),
    }
