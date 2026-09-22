"""Research API end to end on a synthetic market: save → backtest job → optimise →
validate → holdout unseal, with the guardrails enforced through HTTP."""

from __future__ import annotations

import time
from datetime import datetime

import pytest
from ci_api import main, research
from fastapi.testclient import TestClient

from candle_intel.backtest.split import Split
from candle_intel.config import Settings
from candle_intel.research.jobs import JobRunner
from candle_intel.research.ledger import Ledger
from tests.leakage.test_backtest_leakage import mk_of

SPEC = {
    "meta": {"name": "DDU long", "family": "ddu"},
    "entries": [{"side": "long", "conditions": [{"feature": "dirs_3", "op": "==", "value": "DDU"}]}],
    "exit": {"stop_atr": 1.0, "target_atr": 1.5, "time_exit_bars": 6},
}


@pytest.fixture(scope="module")
def mk(syn_m1):
    from candle_intel.features.compute import Bars, compute_features

    split = Split(datetime(2025, 2, 10), datetime(2025, 3, 15), datetime(2025, 3, 29))
    feats = compute_features(Bars.from_m1(syn_m1), 0.001, research_start=split.a_start)
    m = mk_of(syn_m1, feats)
    m.split = split
    return m


@pytest.fixture
def client(mk, tmp_path, monkeypatch):
    led = Ledger.from_url("sqlite://")
    runner = JobRunner(led)
    s = Settings(storage_root=tmp_path, _env_file=None)
    monkeypatch.setattr("candle_intel.backtest.market.get_settings", lambda: s)
    monkeypatch.setattr(research, "get_ledger", lambda: led)
    monkeypatch.setattr(research, "get_market", lambda: mk)
    monkeypatch.setattr(research, "get_runner", lambda: runner)
    return TestClient(main.app)


def wait(client, job_id: str, timeout: float = 120) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.1)
    raise TimeoutError(job_id)


def test_catalogue_and_validation(client) -> None:
    cat = client.get("/api/strategy/catalogue").json()
    names = {f["name"] for f in cat["features"]}
    assert "dirs_3" in names and "hyg_no_entry" not in names
    ok = client.post("/api/strategy/validate", json=SPEC).json()
    assert ok["ok"] and len(ok["spec_hash"]) == 16
    bad = client.post("/api/strategy/validate", json=SPEC | {"exit": {"stop_atr": 1.0}})
    assert bad.status_code == 422 and bad.json()["detail"]["errors"]


def test_preview_never_shows_tier_c(client, mk) -> None:
    r = client.post("/api/strategy/preview", json={"spec": SPEC}).json()
    assert r["counts"]["A"] > 0 and r["counts"]["B"] > 0
    c_start = int((mk.split.c_start - datetime(1970, 1, 1)).total_seconds())
    assert max(r["event_time"]) < c_start


def test_backtest_job_and_results(client) -> None:
    job = client.post("/api/jobs/backtest", json={"spec": SPEC, "tier": "A"}).json()["job_id"]
    j = wait(client, job)
    assert j["status"] == "done", j.get("error")
    run = client.get(f"/api/runs/{j['result']['run_id']}").json()
    assert run["family_trials"] == 1 and run["results"]["pessimistic"]["n"] > 0
    tr = client.get(f"/api/runs/{run['run_id']}/trades", params={"scenario": "base", "limit": 5}).json()
    assert tr["total"] == run["results"]["base"]["n"] and len(tr["trades"]) == 5
    lib = client.get("/api/strategies").json()
    assert lib[0]["family_trials"] == 1 and lib[0]["runs"] == 1


def test_tier_c_cannot_be_requested_directly(client) -> None:
    r = client.post("/api/jobs/backtest", json={"spec": SPEC, "tier": "C"})
    assert r.status_code == 422


def test_optimize_counts_every_variant(client) -> None:
    body = {
        "spec": SPEC,
        "params": [
            {"path": "exit.stop_atr", "values": [0.8, 1.0, 1.2]},
            {"path": "exit.target_atr", "values": [1.0, 2.0]},
        ],
    }
    j = wait(client, client.post("/api/jobs/optimize", json=body).json()["job_id"])
    assert j["status"] == "done", j.get("error")
    run = client.get(f"/api/runs/{j['result']['run_id']}").json()
    assert run["optimize"]["variants"] == 6
    assert run["optimize"]["family_trials"] == 6
    too_big = {
        "spec": SPEC,
        "params": [{"path": "exit.stop_atr", "values": list(range(1, 21))}] * 2
        + [{"path": "exit.target_atr", "values": [1, 2]}],
    }
    assert client.post("/api/jobs/optimize", json=too_big).status_code == 422


def test_validate_then_unseal_once(client) -> None:
    j = wait(client, client.post("/api/jobs/validate", json={"spec": SPEC}).json()["job_id"], 300)
    assert j["status"] == "done", j.get("error")
    v = client.get(f"/api/runs/{j['result']['run_id']}").json()
    assert v["checklist"]["verdict"] in ("rejected", "pending")
    assert {i["key"] for i in v["checklist"]["items"]} >= {"expectancy_A", "deflated_sharpe", "holdout"}
    assert v["walk_forward"]["mode"] == "fixed spec per window"
    h = v["spec_hash"]
    wrong = client.post(
        "/api/holdout/unseal",
        json={"spec_hash": h, "reason": "testing the seal works", "confirm_family": "nope"},
    )
    assert wrong.status_code == 422
    ok = client.post(
        "/api/holdout/unseal",
        json={"spec_hash": h, "reason": "testing the seal works", "confirm_family": "ddu"},
    )
    j2 = wait(client, ok.json()["job_id"])
    assert j2["status"] == "done", j2.get("error")
    again = client.post(
        "/api/holdout/unseal", json={"spec_hash": h, "reason": "second look attempt", "confirm_family": "ddu"}
    )
    assert again.status_code == 409
    fams = client.get("/api/research/overview").json()["families"]
    assert next(f for f in fams if f["family"] == "ddu")["holdout_used"] is True


def test_explain_checks_each_rule_on_the_decision_bar(client, mk) -> None:
    """The owner can check a trade against their own rules: each condition + filter with
    the bar's actual value, evaluated by the engine; tier C bars are refused."""
    spec = SPEC | {"filters": {"sessions": ["london", "new_york", "asian", "london_ny_overlap", "off"]}}
    prev = client.post("/api/strategy/preview", json={"spec": spec, "limit": 1}).json()
    t = prev["event_time"][0] + 300  # decision = the bar's close
    r = client.post("/api/strategy/explain", json={"spec": spec, "time": t}).json()
    assert r["fires"] is True and r["event_time"] == prev["event_time"][0]
    cond = r["entries"][0]["conditions"][0]
    assert cond == {"feature": "dirs_3", "op": "==", "value": "DDU", "actual": "DDU", "passed": True}
    assert [f["key"] for f in r["filters"]] == ["hygiene", "sessions"]
    c_start = int((mk.split.c_start - datetime(1970, 1, 1)).total_seconds())
    assert client.post("/api/strategy/explain", json={"spec": spec, "time": c_start + 300}).status_code == 403
    assert client.post("/api/strategy/explain", json={"spec": spec, "time": t + 7}).status_code == 404
