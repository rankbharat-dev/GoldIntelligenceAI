"""Research guardrails: trial counting, the sealed holdout, run storage, §15 checklist."""

from __future__ import annotations

import numpy as np
import pytest

from candle_intel.config import Settings
from candle_intel.research import checklist, runs
from candle_intel.research.ledger import HoldoutError, Ledger
from candle_intel.statistics import robust
from candle_intel.strategy.spec import with_params
from tests.unit.test_backtest import FLAT, market, spec


@pytest.fixture
def ledger() -> Ledger:
    return Ledger.from_url("sqlite://")


@pytest.fixture
def storage(tmp_path, monkeypatch):
    s = Settings(storage_root=tmp_path, _env_file=None)
    monkeypatch.setattr("candle_intel.backtest.market.get_settings", lambda: s)
    return tmp_path


def test_trials_count_distinct_variants(ledger) -> None:
    s = spec()
    assert ledger.record_trial("fam", s.spec_hash, "A", 0.1, 10, "backtest") == 1
    assert ledger.record_trial("fam", s.spec_hash, "B", 0.1, 10, "backtest") == 1  # same rules, not new
    s2 = with_params(s, {"exit.stop_atr": 2.0})
    assert ledger.record_trial("fam", s2.spec_hash, "A", 0.2, 10, "optimize") == 2
    assert ledger.record_trial("other", s.spec_hash, "A", 0.1, 10, "backtest") == 1
    n, sharpes = ledger.trials("fam")
    assert n == 2 and sorted(sharpes) == [0.1, 0.2]


def test_holdout_is_sealed_and_single_use(ledger, storage) -> None:
    s = spec()
    mk = market([FLAT] * 5)
    with pytest.raises(HoldoutError, match="sealed"):
        runs.run_backtest(s, "C", mk, ledger)
    with pytest.raises(HoldoutError, match="reason"):
        ledger.unseal(s.meta.family, s.spec_hash, "short")
    ledger.unseal(s.meta.family, s.spec_hash, "all development and validation checks passed")
    runs.run_backtest(s, "C", mk, ledger)  # the unsealed spec may read C
    other = with_params(s, {"exit.stop_atr": 3.0})
    with pytest.raises(HoldoutError, match="already spent"):
        runs.run_backtest(other, "C", mk, ledger)
    with pytest.raises(HoldoutError, match="already used"):
        ledger.unseal(s.meta.family, other.spec_hash, "trying a second time for another variant")
    assert ledger.families()[0]["holdout_used"] is True


def test_run_is_stored_counted_and_reloadable(ledger, storage) -> None:
    mk = market([(2900.0, 2900.3, 2899.8, 2900.2), (2900.2, 2902.2, 2900.1, 2902.0), FLAT])
    doc = runs.run_backtest(spec(), "B", mk, ledger)
    assert doc["family_trials"] == 1
    assert set(doc["results"]) == {"optimistic", "base", "pessimistic"}
    assert doc["lineage"]["dataset_id"] == "test"
    again = runs.load_run(doc["run_id"])
    assert again["spec_hash"] == doc["spec_hash"]
    t = runs.load_trades(doc["run_id"], "optimistic")
    assert t.height == 1
    assert ledger.runs()[0]["run_id"] == doc["run_id"]
    assert ledger.specs()[0]["spec_hash"] == doc["spec_hash"]
    with pytest.raises(FileNotFoundError):
        runs.load_run("../../etc")


def test_deflated_sharpe_benchmark_grows_with_trials() -> None:
    sharpes = [0.01, -0.02, 0.03, 0.0, 0.05]
    one = robust.deflated_sharpe(0.05, 1000, 0.0, 3.0, 1, sharpes)
    many = robust.deflated_sharpe(0.05, 1000, 0.0, 3.0, 500, sharpes)
    assert one["sr0_expected_max"] == 0.0
    assert many["sr0_expected_max"] > one["sr0_expected_max"]
    assert many["probability"] < one["probability"]


def test_bootstrap_and_stress_are_reproducible() -> None:
    r = np.random.default_rng(1).normal(0.1, 1.0, 500)
    a, b = robust.stationary_bootstrap_ci(r), robust.stationary_bootstrap_ci(r)
    assert a == b and a["low"] < r.mean() < a["high"]
    st = robust.cost_stress(np.full(10, 0.2), np.full(10, 1000.0), 0.001, 100.0)
    assert st["breakeven_extra_spread_points"] == pytest.approx(200.0)  # 0.2 R × 1000 pts
    assert st["breakeven_extra_commission_usd_per_lot"] == pytest.approx(20.0)


def _doc(**p) -> dict:
    base = {
        "n": 1200,
        "expectancy_r": 0.15,
        "profit_factor": 1.3,
        "max_dd_r": 10.0,
        "max_dd_pct": 0.1,
        "ambiguity_rate": 0.01,
        "stability": {"year": {"score": 0.8}, "session": {"score": 0.75}},
    }
    return {"results": {"pessimistic": base | p}, "deflated_sharpe": {"deflated_excess": 0.02, "n_trials": 5}}


def test_checklist_verdicts() -> None:
    good = checklist.evaluate(_doc(), _doc(n=300), _doc(n=1500), None, 0)
    assert good["verdict"] == "pending" and good["ready_to_unseal"]
    bad = checklist.evaluate(_doc(), _doc(n=300, expectancy_r=0.05), _doc(), None, 0)
    assert bad["verdict"] == "rejected" and not bad["ready_to_unseal"]
    assert [i["key"] for i in bad["items"] if i["passed"] is False] == ["expectancy_B"]
    done = checklist.evaluate(_doc(), _doc(n=300), _doc(), _doc(expectancy_r=0.09), 1)
    assert done["verdict"] == "candidate"
    weak_holdout = checklist.evaluate(_doc(), _doc(n=300), _doc(), _doc(expectancy_r=0.05), 1)
    assert weak_holdout["verdict"] == "rejected"  # below 50 % of development


def test_stability_counts_only_profitable_buckets() -> None:
    from candle_intel.backtest.metrics import stability

    losing = [{"n": 50, "expectancy_r": -0.2}, {"n": 40, "expectancy_r": -0.1}, {"n": 5, "expectancy_r": 0.9}]
    assert stability(losing)["score"] == 0.0  # consistently losing is not a stable edge; tiny bucket ignored
    mixed = [{"n": 50, "expectancy_r": 0.2}, {"n": 40, "expectancy_r": -0.1}, {"n": 30, "expectancy_r": 0.05}]
    assert stability(mixed)["score"] == pytest.approx(2 / 3, abs=1e-4)
