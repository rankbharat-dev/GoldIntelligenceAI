"""Phase 10 exit: the ML filter beats the rule baseline on unseen tier B when there is
something to learn, and is reported as not helping when there is not."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import polars as pl
import pytest

from candle_intel.backtest.split import Split
from candle_intel.config import Settings
from candle_intel.features.compute import Bars, compute_features
from candle_intel.ml import filter as mlf
from candle_intel.research.ledger import Ledger
from candle_intel.strategy.spec import StrategySpec
from tests.leakage.test_backtest_leakage import mk_of, plant

SPLIT = Split(datetime(2025, 2, 10), datetime(2025, 3, 15), datetime(2025, 3, 29))
# Broad rule: any up-close bar. Only its DDU subset carries the planted drift.
SPEC = StrategySpec.model_validate(
    {
        "meta": {"name": "any up close", "family": "ml-test"},
        "entries": [{"side": "long", "conditions": [{"feature": "dir", "op": "==", "value": 1}]}],
        "exit": {"stop_atr": 1.0, "target_atr": 1.0, "time_exit_bars": 6},
    }
)


@pytest.fixture(scope="module")
def feats(syn_m1):
    return compute_features(Bars.from_m1(syn_m1), 0.001, research_start=SPLIT.a_start)


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    s = Settings(storage_root=tmp_path, _env_file=None)
    monkeypatch.setattr("candle_intel.backtest.market.get_settings", lambda: s)


def market(m1, feats):
    m = mk_of(m1, feats)
    m.split = SPLIT
    return m


def test_filter_learns_a_hidden_subset(syn_m1, feats) -> None:
    mk = market(plant(syn_m1, feats, pl.col("dirs_3") == "DDU", size=2.0), feats)
    led = Ledger.from_url("sqlite://")
    doc = mlf.train_and_test(SPEC, mk, led)
    t = doc["test"]
    assert t["tier"] == "B" and doc["train"]["tier"] == "A"
    assert doc["train"]["oof_auc"] > 0.55
    assert t["filtered"]["expectancy_r"] > t["baseline"]["expectancy_r"] + 0.05
    names = [i["feature"] for i in doc["importance"][:8]]
    assert any(n in names for n in ("dirs_3", "dir_lag1", "dir_lag2", "streak", "up_count_5")), names
    assert doc["family_trials"] == 1  # the filtered variant is a trial on the family


def test_filter_on_noise_is_not_helping(syn_m1, feats) -> None:
    led = Ledger.from_url("sqlite://")
    doc = mlf.train_and_test(SPEC, market(syn_m1, feats), led)
    assert doc["verdict"] == "not helping" and doc["reasons"]


def test_folds_never_train_on_the_future() -> None:
    times = np.array(np.arange(0, 20000) * 300 * 1_000_000, dtype="datetime64[us]")
    for tr, te in mlf._folds(times):
        assert times[tr].max() < times[te].min() - np.timedelta64(1, "D")
