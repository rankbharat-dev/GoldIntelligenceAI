"""CEO Work Lab over HTTP: the dashboard's calls and the agents' calls."""

from __future__ import annotations

import pytest
from ci_api import ceo, main, research
from fastapi.testclient import TestClient

from candle_intel.ceo.store import CeoStore
from candle_intel.research.ledger import Ledger


@pytest.fixture
def client(monkeypatch):
    led = Ledger.from_url("sqlite://")
    store = CeoStore(led)
    monkeypatch.setattr(research, "get_ledger", lambda: led)
    monkeypatch.setattr(ceo, "get_store", lambda: store)
    return TestClient(main.app)


def test_mission_round_trip(client) -> None:
    r = client.post("/api/ceo/missions", json={"objective": "Research PDH/PDL sweeps on M5 in London"})
    assert r.status_code == 200
    mid = r.json()["mission_id"]
    assert client.get("/api/ceo/missions/next").json()["mission"]["mission_id"] == mid
    plan = {
        "tasks": [
            {"key": "d", "agent": "data_scientist", "title": "Check data", "instructions": "Check M5 data."}
        ]
    }
    assert client.post(f"/api/ceo/missions/{mid}/plan", json=plan).json()["status"] == "running"
    ready = client.get(f"/api/ceo/missions/{mid}/ready").json()
    tid = ready[0]["task_id"]
    assert client.post(f"/api/ceo/tasks/{tid}/start", json={"agent": "validator"}).status_code == 409
    assert client.post(f"/api/ceo/tasks/{tid}/start", json={"agent": "data_scientist"}).status_code == 200
    assert client.post(
        f"/api/ceo/tasks/{tid}/log", json={"agent": "data_scientist", "message": "reading"}
    ).json() == {"ok": True}
    out = {"summary": "Data is fine for M5.", "limitations": ["demo broker feed"]}
    assert (
        client.post(
            f"/api/ceo/tasks/{tid}/finish", json={"agent": "data_scientist", "output": out}
        ).status_code
        == 200
    )
    rep = {
        "headline": "Data ready",
        "summary": "Only data checked in this test mission.",
        "verdict": "inconclusive",
        "limitations": ["test"],
    }
    assert client.post(f"/api/ceo/missions/{mid}/report", json=rep).json()["status"] == "completed"
    ov = client.get("/api/ceo/overview").json()
    assert ov["missions"]["completed"] == 1 and len(ov["agents"]) == 5
    assert [m["mission_id"] for m in client.get("/api/ceo/missions").json()] == [mid]
    assert client.get(f"/api/ceo/missions/{mid}/events?after=0").json()[-1]["kind"] == "report"


def test_errors_are_clear(client) -> None:
    assert client.get("/api/ceo/missions/nope").status_code == 404
    assert client.post("/api/ceo/missions", json={"objective": "short"}).status_code == 422
    mid = client.post("/api/ceo/missions", json={"objective": "A valid objective here"}).json()["mission_id"]
    bad = client.post(
        f"/api/ceo/missions/{mid}/plan",
        json={"tasks": [{"key": "x", "agent": "trader", "title": "Buy", "instructions": "place an order"}]},
    )
    assert bad.status_code == 422
    assert client.post(f"/api/ceo/missions/{mid}/approve").status_code == 409


def test_live_stream_sends_changes(client, monkeypatch) -> None:
    monkeypatch.setattr(ceo, "STREAM_MAX_S", 0.1)
    mid = client.post("/api/ceo/missions", json={"objective": "Stream test mission"}).json()["mission_id"]
    with client.stream("GET", f"/api/ceo/missions/{mid}/stream") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert "retry: 3000" in body and "event: change" in body and "draft" in body
    assert client.get("/api/ceo/missions/nope/stream").status_code == 404
