"""Phase 8 exit condition: the research engine rediscovers a planted edge in synthetic
data and rejects pure noise — with every hypothesis registered before it is tested,
every variant counted as a trial, and pause / resume working."""

from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

from candle_intel.backtest.split import Split
from candle_intel.config import Settings
from candle_intel.features.compute import Bars, compute_features
from candle_intel.research import discovery
from candle_intel.research.ledger import Ledger
from tests.leakage.test_backtest_leakage import mk_of, plant

SPLIT = Split(datetime(2025, 2, 10), datetime(2025, 3, 15), datetime(2025, 3, 29))


def c(feature, op, value):
    return {"feature": feature, "op": op, "value": value}


SPACE = {
    "name": "Candle sequences",
    "family": "engine-test",
    "blocks": [
        {"label": "DDU long", "side": "long", "conditions": [c("dirs_3", "==", "DDU")]},
        {"label": "UUD long", "side": "long", "conditions": [c("dirs_3", "==", "UUD")]},
        {"label": "DDU short", "side": "short", "conditions": [c("dirs_3", "==", "DDU")]},
        {"label": "strong close long", "side": "long", "conditions": [c("close_loc", ">", 0.8)]},
        {"label": "weak close short", "side": "short", "conditions": [c("close_loc", "<", 0.2)]},
    ],
    "stop_atr": [1.0],
    "target_atr": [1.0, 1.5],
    "time_exit_bars": [6],
    "method": "grid",
    "min_trades_a": 30,
    "top_k": 2,
}


@pytest.fixture(scope="module")
def feats(syn_m1):
    return compute_features(Bars.from_m1(syn_m1), 0.001, research_start=SPLIT.a_start)


def market(m1, feats):
    m = mk_of(m1, feats)
    m.split = SPLIT
    return m


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    s = Settings(storage_root=tmp_path, _env_file=None)
    monkeypatch.setattr("candle_intel.backtest.market.get_settings", lambda: s)


def run_search(mk, space=SPACE, **kw):
    led = Ledger.from_url("sqlite://")
    rec = discovery.create(discovery.SearchSpace.model_validate(space | kw), led, mode="auto")
    discovery.run(rec["search_id"], mk, led)
    return led, rec["search_id"]


SAMPLE_SIZE_ITEMS = ("Trades — development", "Trades — validation", "Stability", "Deflated Sharpe")


def test_engine_rediscovers_the_planted_edge(syn_m1, feats) -> None:
    mk = market(plant(syn_m1, feats, pl.col("dirs_3") == "DDU"), feats)
    led, sid = run_search(mk)
    hyps = led.hypotheses(sid)
    assert len(hyps) == 10
    best = max(hyps, key=discovery._score)
    assert best["label"].startswith("DDU long")
    assert best["validate_run"] is not None
    assert best["metrics"]["B_expectancy_r"] > 0.2  # the edge holds on unseen tier B
    # on this 2-month synthetic sample only the sample-size-type criteria may fail
    for r in best["reasons"]:
        assert r.startswith(SAMPLE_SIZE_ITEMS) or r.startswith("passes"), r
    mirror = next(h for h in hyps if h["label"].startswith("DDU short"))
    assert mirror["status"] == "rejected" and any("expectancy" in r for r in mirror["reasons"])
    # every screened hypothesis is a trial on the family
    n_trials, _ = led.trials("engine-test")
    assert n_trials == len([h for h in hyps if h["status"] != "planned"])
    s = led.search(sid)
    assert s["status"] == "done" and s["summary"]["family_trials"] == n_trials


def test_engine_rejects_pure_noise(syn_m1, feats) -> None:
    led, sid = run_search(market(syn_m1, feats))
    hyps = led.hypotheses(sid)
    assert not [h for h in hyps if h["status"] == "candidate"]
    assert all(h["status"] in ("rejected", "not_selected") for h in hyps)
    assert all(h["reasons"] for h in hyps)  # every rejection says why


def test_evolutionary_respects_budget_and_registers_first(syn_m1, feats) -> None:
    space = SPACE | {"target_atr": [0.8, 1.0, 1.5, 2.0], "time_exit_bars": [3, 6, 12]}
    led, sid = run_search(market(syn_m1, feats), space, method="evolutionary", max_trials=30, top_k=0)
    hyps = led.hypotheses(sid)
    assert 16 < len(hyps) <= 30
    assert max(h["generation"] for h in hyps) >= 1
    assert all(h["status"] != "planned" for h in hyps)
    assert all(h["created_at"] <= h["updated_at"] for h in hyps)


def test_pause_and_resume(syn_m1, feats) -> None:
    mk = market(syn_m1, feats)
    led = Ledger.from_url("sqlite://")
    rec = discovery.create(discovery.SearchSpace.model_validate(SPACE), led, mode="approve")
    assert rec["status"] == "proposed"
    led.search_update(rec["search_id"], control="pause")
    out = discovery.run(rec["search_id"], mk, led)
    assert out.get("paused") and led.search(rec["search_id"])["status"] == "paused"
    assert all(h["status"] == "planned" for h in led.hypotheses(rec["search_id"]))
    discovery.run(rec["search_id"], mk, led)
    assert led.search(rec["search_id"])["status"] == "done"
    assert all(h["status"] != "planned" for h in led.hypotheses(rec["search_id"]))


# ---------------------------------------------------------------- API


def test_search_api_end_to_end(syn_m1, feats, monkeypatch) -> None:
    import time

    from ci_api import main, research
    from fastapi.testclient import TestClient

    from candle_intel.research.jobs import JobRunner

    led = Ledger.from_url("sqlite://")
    runner = JobRunner(led)
    mk = market(syn_m1, feats)
    monkeypatch.setattr(research, "get_ledger", lambda: led)
    monkeypatch.setattr(research, "get_market", lambda: mk)
    monkeypatch.setattr(research, "get_runner", lambda: runner)
    client = TestClient(main.app)

    space = client.get("/api/search/space").json()
    assert len(space["blocks"]) == 18 and "london" in space["sessions"]
    bad = client.post("/api/searches", json={"space": SPACE | {"blocks": []}})
    assert bad.status_code == 422
    rec = client.post("/api/searches", json={"space": SPACE, "mode": "approve"}).json()
    assert rec["status"] == "proposed" and rec["summary"]["registered"] == 10
    assert client.post(f"/api/searches/{rec['search_id']}/pause").status_code == 409
    job = client.post(f"/api/searches/{rec['search_id']}/approve").json()["job_id"]
    t0 = time.time()
    while (
        client.get(f"/api/jobs/{job}").json()["status"] not in ("done", "failed") and time.time() - t0 < 300
    ):
        time.sleep(0.2)
    j = client.get(f"/api/jobs/{job}").json()
    assert j["status"] == "done", j.get("error")
    got = client.get(f"/api/searches/{rec['search_id']}").json()
    assert got["status"] == "done" and len(got["hypotheses"]) == 10 and not got["resumable"]
    assert got["live"]["family_trials"] == 10
    assert client.post(f"/api/searches/{rec['search_id']}/approve").status_code == 409
    board = client.get("/api/candidates").json()
    assert isinstance(board, list)  # noise: nothing survived the screen to reach Validate
    assert all(r["verdict"] in ("rejected", "pending", "candidate") for r in board)
