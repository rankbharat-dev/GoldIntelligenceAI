"""Selection statistics and robustness checks (blueprint §9.3, MASTER_PROMPT Robustness Lab).

- Deflated Sharpe (Bailey & López de Prado 2014) at the family's true trial count.
- Stationary bootstrap (Politis & Romano 1994) confidence interval on expectancy —
  respects the autocorrelation of consecutive trades.
- Monte Carlo reshuffle of trade order → the drawdown you could have had.
- Cost stress: how much extra spread / commission the edge survives.

Every random draw uses a fixed seed, so reports are reproducible.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.stats import norm

EULER_GAMMA = 0.5772156649015329
SEED = 20260921


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """SR0: the best Sharpe you expect from ``n_trials`` skill-less variants."""
    if n_trials <= 1 or var_sr <= 0:
        return 0.0
    n = float(n_trials)
    return math.sqrt(var_sr) * (
        (1 - EULER_GAMMA) * norm.ppf(1 - 1 / n) + EULER_GAMMA * norm.ppf(1 - 1 / (n * math.e))
    )


def deflated_sharpe(
    sr: float, n_obs: int, skew: float, kurtosis: float, n_trials: int, trial_sharpes: list[float]
) -> dict[str, Any]:
    """Per-trade Sharpe vs the trial-count benchmark. ``kurtosis`` is non-excess.

    Variance of Sharpe across trials comes from the family's recorded trials; with
    fewer than two it falls back to the sampling variance of one Sharpe estimate."""
    finite = [s for s in trial_sharpes if s is not None and math.isfinite(s)]
    if len(finite) >= 2:
        var_sr, var_source = float(np.var(finite, ddof=1)), "across recorded trials"
    else:
        var_sr, var_source = (1 + 0.5 * sr * sr) / max(n_obs - 1, 1), "sampling variance (too few trials)"
    sr0 = expected_max_sharpe(n_trials, var_sr)
    denom_sq = 1 - skew * sr + (kurtosis - 1) / 4 * sr * sr
    if n_obs < 2 or denom_sq <= 0:
        prob = None
    else:
        prob = float(norm.cdf((sr - sr0) * math.sqrt(n_obs - 1) / math.sqrt(denom_sq)))
    return {
        "sharpe_per_trade": round(sr, 5),
        "n_trials": n_trials,
        "sr0_expected_max": round(sr0, 5),
        "deflated_excess": round(sr - sr0, 5),  # §15 gate: > 0
        "probability": None if prob is None else round(prob, 4),  # P(true SR > SR0)
        "var_sr": var_sr,
        "var_source": var_source,
    }


def stationary_bootstrap_ci(
    r: np.ndarray, n_boot: int = 2000, mean_block: float | None = None, alpha: float = 0.05
) -> dict[str, Any]:
    n = len(r)
    if n < 10:
        return {"low": None, "high": None, "n_boot": 0}
    rng = np.random.default_rng(SEED)
    block = mean_block or max(1.0, n ** (1 / 3))
    p = 1.0 / block
    means = np.empty(n_boot)
    pos = np.arange(n)
    for b in range(n_boot):
        new_block = rng.random(n) < p
        new_block[0] = True
        begins = np.flatnonzero(new_block)  # positions where a block starts
        block_id = np.cumsum(new_block) - 1
        start_idx = rng.integers(n, size=begins.size)  # random start of each block
        idx = (start_idx[block_id] + pos - begins[block_id]) % n
        means[b] = r[idx].mean()
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return {
        "low": round(float(lo), 4),
        "high": round(float(hi), 4),
        "p_mean_le_0": round(float((means <= 0).mean()), 4),
        "mean_block": round(block, 2),
        "n_boot": n_boot,
    }


def monte_carlo_drawdown(r: np.ndarray, n_sims: int = 1000) -> dict[str, Any]:
    if len(r) < 2:
        return {"p50": None, "p95": None, "p99": None}
    rng = np.random.default_rng(SEED)
    dds = np.empty(n_sims)
    for i in range(n_sims):
        path = np.concatenate([[0.0], np.cumsum(rng.permutation(r))])
        dds[i] = (np.maximum.accumulate(path) - path).max()
    q = np.quantile(dds, [0.5, 0.95, 0.99])
    return {
        "p50": round(float(q[0]), 2),
        "p95": round(float(q[1]), 2),
        "p99": round(float(q[2]), 2),
        "sims": n_sims,
    }


def cost_stress(r: np.ndarray, risk_pts: np.ndarray, point: float, contract_size: float) -> dict[str, Any]:
    """Expectancy if every trade paid ``extra`` more spread points (or commission USD / lot
    round turn). Linear in the extra cost, so break-even is exact."""
    if len(r) == 0:
        return {}
    inv = float((1.0 / risk_pts).mean())
    mean = float(r.mean())
    extra_pts = [0, 10, 20, 50, 100, 150, 200, 300]
    usd_per_pt_lot = point * contract_size  # 0.1 USD per point per lot on XAUUSD
    return {
        "spread_points": [{"extra": x, "expectancy_r": round(mean - x * inv, 4)} for x in extra_pts],
        "breakeven_extra_spread_points": round(mean / inv, 1) if inv > 0 else None,
        "breakeven_extra_commission_usd_per_lot": round(mean / inv * usd_per_pt_lot, 2) if inv > 0 else None,
    }


def benjamini_hochberg(pvals: list[float], q: float = 0.10) -> list[dict[str, Any]]:
    """Benjamini–Hochberg FDR (§9.3): adjusted q-value per p-value and whether it is a
    discovery at level ``q``. Order of the output = order of the input."""
    m = len(pvals)
    if m == 0:
        return []
    p = np.asarray(pvals, dtype=float)
    order = np.argsort(p)
    ranked = p[order] * m / np.arange(1, m + 1)
    adj = np.minimum.accumulate(ranked[::-1])[::-1].clip(max=1.0)
    out = np.empty(m)
    out[order] = adj
    return [{"q_value": round(float(v), 5), "rejected": bool(v <= q)} for v in out]
