"""Previous-day high/low sweep detector: exact rule, no look-ahead, stored as a study run."""

from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

from candle_intel.backtest.split import Split
from candle_intel.patterns import PatternError, SweepParams, catalogue, prev_day, run_pattern_study
from candle_intel.research.ledger import Ledger
from tests.leakage.test_backtest_leakage import mk_of


@pytest.fixture(scope="module")
def feats(syn_m1):
    from candle_intel.features.compute import Bars, compute_features

    return compute_features(Bars.from_m1(syn_m1), 0.001, research_start=datetime(2025, 2, 10))


@pytest.fixture(scope="module")
def mk(syn_m1, feats):
    m = mk_of(syn_m1, feats)
    m.split = Split(datetime(2025, 2, 10), datetime(2025, 3, 15), datetime(2025, 3, 29))
    return m


def test_levels_come_from_the_previous_trading_day(mk) -> None:
    b = prev_day.with_levels(prev_day.m5_bars(mk))
    days = b.group_by("day").agg(pl.col("h").max(), pl.col("l").min(), pl.col("pdh").first()).sort("day")
    assert days["pdh"][1:].to_list() == days["h"][:-1].to_list()
    # 17:00 New York is the day boundary: 16:55 and 18:00 New York (EDT) are different trading days
    t = b.filter(pl.col("event_time").is_in([datetime(2025, 3, 11, 20, 55), datetime(2025, 3, 11, 22, 0)]))
    assert t["day"].n_unique() == 2


def test_sweep_rule_holds_for_every_event(mk) -> None:
    for level in ("pdh", "pdl"):
        ev = prev_day.detect(mk, level, first_only=False, no_prior_acceptance=False, max_depth_atr=None)
        assert ev.height > 20
        bars = prev_day.m5_bars(mk).join(ev.select("event_time", "level"), on="event_time")
        if level == "pdh":
            assert (bars["h"] > bars["level"] - 1e-6).all() and (bars["c"] < bars["level"] + 1e-6).all()
            assert (ev["side"] == -1).all()
        else:
            assert (bars["l"] < bars["level"] + 1e-6).all() and (bars["c"] > bars["level"] - 1e-6).all()
            assert (ev["side"] == 1).all()
        assert (ev["decision_time"] > ev["event_time"]).all()  # decided at the bar close


def test_options_only_remove_events(mk) -> None:
    loose = prev_day.detect(mk, "pdh", first_only=False, no_prior_acceptance=False, max_depth_atr=None)
    strict = prev_day.detect(mk, "pdh", sessions=["london", "new_york", "london_ny_overlap"])
    assert 0 < strict.height < loose.height
    assert set(strict["event_time"]) <= set(loose["event_time"])
    assert strict.group_by("day").len()["len"].max() == 1  # first_only
    assert set(strict["session"]) <= {"london", "new_york", "london_ny_overlap"}


def test_no_look_ahead(mk, syn_m1, feats) -> None:
    """Cutting the history after a date must not change any event before it."""
    cut = datetime(2025, 3, 20)
    full = prev_day.detect(mk, "pdl").filter(pl.col("decision_time") < cut)
    short = mk_of(syn_m1.filter(pl.col("ts_utc") < cut), feats.filter(pl.col("available_at") < cut))
    short.split = mk.split
    part = prev_day.detect(short, "pdl")
    assert full["event_time"].to_list() == part["event_time"].to_list()


def test_study_is_a_stored_run_and_tier_rules_hold(mk, tmp_path, monkeypatch) -> None:
    from candle_intel.config import Settings

    s = Settings(storage_root=tmp_path, _env_file=None)
    monkeypatch.setattr("candle_intel.backtest.market.get_settings", lambda: s)
    led = Ledger.from_url("sqlite://")
    doc = run_pattern_study(mk, led, "pdl_sweep", tier="A")
    assert doc["detector"] == "pdl_sweep" and doc["occurrences"] == doc["detector_counts"]["events"]
    assert doc["occurrences"] > 0 and "pessimistic" in doc["scenarios"]
    assert [r["run_id"] for r in led.runs()] == [doc["run_id"]]
    with pytest.raises(PatternError, match="default rule"):
        run_pattern_study(mk, led, "pdl_sweep", SweepParams(min_depth_atr=0.3), tier="B")
    with pytest.raises(PatternError, match="sealed"):
        run_pattern_study(mk, led, "pdl_sweep", tier="C")
    assert set(catalogue()["detectors"]) == {"pdh_sweep", "pdl_sweep"}


def test_pattern_api(mk, tmp_path, monkeypatch) -> None:
    import time

    from ci_api import main, research
    from fastapi.testclient import TestClient

    from candle_intel.config import Settings
    from candle_intel.research.jobs import JobRunner

    s = Settings(storage_root=tmp_path, _env_file=None)
    monkeypatch.setattr("candle_intel.backtest.market.get_settings", lambda: s)
    led = Ledger.from_url("sqlite://")
    runner = JobRunner(led)
    monkeypatch.setattr(research, "get_ledger", lambda: led)
    monkeypatch.setattr(research, "get_market", lambda: mk)
    monkeypatch.setattr(research, "get_runner", lambda: runner)
    c = TestClient(main.app)
    assert "pdh_sweep" in c.get("/api/patterns/catalogue").json()["detectors"]
    bad = {"detector": "pdh_sweep", "params": {"min_depth_atr": 0.5}, "tier": "B"}
    assert c.post("/api/jobs/pattern-study", json=bad).status_code == 422
    job = c.post(
        "/api/jobs/pattern-study", json={"detector": "pdh_sweep", "params": {"sessions": ["london"]}}
    ).json()
    for _ in range(200):
        j = c.get(f"/api/jobs/{job['job_id']}").json()
        if j["status"] not in ("queued", "running"):
            break
        time.sleep(0.2)
    assert j["status"] == "done", j
    run = c.get(f"/api/runs/{j['result']['run_id']}").json()
    assert run["detector"] == "pdh_sweep" and run["definition"]["params"]["sessions"] == ["london"]


def test_feature_store_columns_match_the_detector(mk) -> None:
    """features/3 pdh/pdl sweep columns select exactly the detector's events."""
    cols = ["pdl_sweep", "pdl_accepted_before", "pdl_sweeps_today", "pdl_sweep_depth_atr", "atr_pts"]
    f = mk.features(cols)
    via_features = f.filter(
        pl.col("pdl_sweep")
        & ~pl.col("pdl_accepted_before")
        & (pl.col("pdl_sweeps_today") == 1)
        & (pl.col("pdl_sweep_depth_atr") <= 1.5)
        & (pl.col("atr_pts") > 0)
    )["event_time"]
    via_detector = prev_day.detect(mk, "pdl", min_prev_day_bars=0)["event_time"]
    assert via_features.len() > 10
    assert sorted(via_features.to_list()) == sorted(via_detector.to_list())
