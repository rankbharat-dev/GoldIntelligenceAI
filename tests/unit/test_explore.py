"""Phase 7: behaviour library + pre-registration, event studies (planted truth), FDR,
Behaviour Explorer / Chart-Based Creator / structure endpoints on a synthetic market."""

from __future__ import annotations

import time
from datetime import datetime

import polars as pl
import pytest
from ci_api import explore, main, research
from fastapi.testclient import TestClient

from candle_intel.backtest.split import Split
from candle_intel.config import Settings
from candle_intel.features.compute import Bars, compute_features
from candle_intel.research import behaviours, events
from candle_intel.research.jobs import JobRunner
from candle_intel.research.ledger import Ledger
from candle_intel.statistics.robust import benjamini_hochberg
from tests.leakage.test_backtest_leakage import mk_of, plant

SPLIT = Split(datetime(2025, 2, 10), datetime(2025, 3, 15), datetime(2025, 3, 29))
DDU = {
    "side": "long",
    "conditions": [{"feature": "dirs_3", "op": "==", "value": "DDU"}],
    "barriers": {"target_atr": 1.0, "stop_atr": 1.0, "horizon_bars": 6},
}


@pytest.fixture(scope="module")
def feats(syn_m1):
    return compute_features(Bars.from_m1(syn_m1), 0.001, research_start=SPLIT.a_start)


@pytest.fixture(scope="module")
def mk(syn_m1, feats):
    m = mk_of(syn_m1, feats)
    m.split = SPLIT
    return m


@pytest.fixture(scope="module")
def planted_mk(syn_m1, feats):
    m = mk_of(plant(syn_m1, feats, pl.col("dirs_3") == "DDU"), feats)
    m.split = SPLIT
    return m


def test_study_finds_a_planted_behaviour(planted_mk, mk) -> None:
    found = events.study(DDU, planted_mk, "A", registered=True)
    control = events.study(DDU, mk, "A", registered=True)
    fp, cp = found["scenarios"]["optimistic"], control["scenarios"]["optimistic"]
    assert found["occurrences"] > 300
    assert fp["mean_r_gross"] > 0.3 and abs(cp["mean_r_gross"]) < 0.1
    assert found["lift_vs_baseline"]["target_rate"] > 0.15
    assert found["gross"]["bootstrap"]["p_mean_le_0"] < 0.01
    assert control["gross"]["bootstrap"]["p_mean_le_0"] > 0.05
    # every occurrence is labelled (overlap allowed), unlike a one-position backtest
    assert fp["n"] == found["occurrences"]
    # pessimistic never beats optimistic
    assert found["scenarios"]["pessimistic"]["mean_r_net"] < fp["mean_r_net"]
    assert found["sample"] == {
        "min": 1000,
        "n": found["occurrences"],
        "sufficient": found["occurrences"] >= 1000,
        "consequence": None
        if found["occurrences"] >= 1000
        else "research observation only — cannot become a strategy",
    }


def test_study_guardrails(mk) -> None:
    with pytest.raises(events.StudyError):
        events.study(DDU, mk, "C", registered=True)
    with pytest.raises(events.StudyError):
        events.study(DDU, mk, "B", registered=False)  # ad-hoc may not touch validation data


def test_registration_is_immutable_and_versioned() -> None:
    led = Ledger.from_url("sqlite://")
    first = {p["pattern_id"]: p["registered_at"] for p in behaviours.ensure_registered(led)}
    assert len(first) == len(behaviours.LIBRARY) == 18
    time.sleep(0.01)
    again = {p["pattern_id"]: p["registered_at"] for p in behaviours.ensure_registered(led)}
    assert again == first  # the first timestamp stands
    p = behaviours.register_custom(
        led, "my_idea", "My idea", "custom", "long", DDU["conditions"], "DDU goes up"
    )
    q = behaviours.register_custom(
        led, "my_idea", "My idea", "custom", "long", [{"feature": "dir", "op": "==", "value": 1}], "changed"
    )
    assert (p["slug"], p["version"], q["version"]) == ("my_idea", 1, 2)  # a changed rule is a new version
    assert (
        behaviours.register_custom(led, "my_idea", "x", "custom", "long", DDU["conditions"], "again")[
            "version"
        ]
        == 1
    )
    assert p["rule_version"] == behaviours.RULE_VERSION


def test_benjamini_hochberg() -> None:
    out = benjamini_hochberg([0.001, 0.02, 0.03, 0.5], q=0.05)
    assert [o["rejected"] for o in out] == [True, True, True, False]
    assert out[0]["q_value"] == pytest.approx(0.004)
    assert out[3]["q_value"] == pytest.approx(0.5)
    shuffled = benjamini_hochberg([0.5, 0.001], q=0.05)
    assert [o["rejected"] for o in shuffled] == [False, True]


def test_distribution_covers_a_and_b_only(mk) -> None:
    d = events.distribution(mk, "close_loc", "tier", numeric=True)
    assert {g["group"] for g in d["groups"]} == {"A", "B"}
    assert sum(sum(g["hist"]) for g in d["groups"]) == sum(g["n"] for g in d["groups"])
    c = events.distribution(mk, "session", "year", numeric=False)
    assert abs(sum(v for v in c["groups"][0]["shares"].values() if v) - 1) < 1e-6


# ---------------------------------------------------------------- API


@pytest.fixture
def client(mk, syn_m1, tmp_path, monkeypatch):
    led = Ledger.from_url("sqlite://")
    runner = JobRunner(led)
    s = Settings(storage_root=tmp_path, _env_file=None)
    monkeypatch.setattr("candle_intel.backtest.market.get_settings", lambda: s)
    monkeypatch.setattr(research, "get_ledger", lambda: led)
    monkeypatch.setattr(research, "get_market", lambda: mk)
    monkeypatch.setattr(research, "get_runner", lambda: runner)
    m5 = Bars.from_m1(syn_m1).m5.rename({"ts_utc": "event_time"})

    def window(_mk, lo, hi):
        w = m5.filter(pl.col("event_time") < hi)
        w = pl.concat(
            [
                w.filter(pl.col("event_time") < lo).tail(explore.WARMUP_BARS),
                w.filter(pl.col("event_time") >= lo),
            ]
        )
        return w.join(mk._frame.select("event_time", "atr_pts"), on="event_time", how="left").with_columns(
            _atr=pl.col("atr_pts") * 0.001
        )

    monkeypatch.setattr(explore, "_m5_window", window)
    return TestClient(main.app)


def wait(client, job_id: str, timeout: float = 180) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.1)
    raise TimeoutError(job_id)


def epoch(t: datetime) -> int:
    return int((t - datetime(1970, 1, 1)).total_seconds())


def test_behaviours_and_studies_via_api(client) -> None:
    lib = client.get("/api/behaviours").json()
    assert len(lib["patterns"]) == 18 and lib["rule_version"] == behaviours.RULE_VERSION
    adhoc = client.post("/api/jobs/study", json={"conditions": DDU["conditions"], "tier": "A"}).json()
    j = wait(client, adhoc["job_id"])
    assert j["status"] == "done", j.get("error")
    run = client.get(f"/api/runs/{j['result']['run_id']}").json()
    assert run["kind"] == "study" and run["exploratory"] is True and run["occurrences"] > 0
    assert (
        client.post("/api/jobs/study", json={"conditions": DDU["conditions"], "tier": "B"}).status_code == 422
    )
    pid = lib["patterns"][0]["pattern_id"]
    jb = wait(client, client.post("/api/jobs/study", json={"pattern_id": pid, "tier": "B"}).json()["job_id"])
    assert jb["status"] == "done", jb.get("error")
    rb = client.get(f"/api/runs/{jb['result']['run_id']}").json()
    assert rb["registered"] is True and rb["tier"] == "B"
    latest = client.get("/api/behaviours").json()["patterns"][0]["latest"]
    assert latest["B"]["run_id"] == rb["run_id"]


def test_screen_applies_fdr(client) -> None:
    j = wait(client, client.post("/api/jobs/screen?tier=A").json()["job_id"], 600)
    assert j["status"] == "done", j.get("error")
    run = client.get(f"/api/runs/{j['result']['run_id']}").json()
    assert len(run["rows"]) == 18
    assert all("q_gross" in r for r in run["rows"] if r["p_gross"] is not None)


def test_structure_and_draft_endpoints(client) -> None:
    s = client.get(
        "/api/structure", params={"start": epoch(datetime(2025, 3, 3)), "end": epoch(datetime(2025, 3, 6))}
    ).json()
    assert s["swings"] and s["lines"] and s["events"]
    assert all(epoch(datetime(2025, 3, 3)) <= x["time"] for x in s["swings"])
    assert all(x["known_at"] >= x["time"] + 300 * 5 for x in s["swings"])  # confirmed K bars later
    d = client.post(
        "/api/strategy/draft-from-bar", json={"time": epoch(datetime(2025, 3, 4, 14, 5)), "side": "long"}
    )
    assert d.status_code == 200
    sug = d.json()["suggestions"]
    assert any(x["condition"]["feature"] == "close_loc" for x in sug)
    sealed = client.post("/api/strategy/draft-from-bar", json={"time": epoch(datetime(2025, 4, 2, 14, 5))})
    assert sealed.status_code == 403
    dist = client.get("/api/explore/distribution", params={"feature": "sweep_low", "by": "session"}).json()
    assert dist["numeric"] is False and dist["groups"]
