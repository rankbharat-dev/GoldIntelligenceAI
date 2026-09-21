"""CEO Work Lab mission store: plan → dependencies → claim → hand-in → report, with the
limits, permissions and recovery rules that keep agents honest and bounded."""

from __future__ import annotations

from datetime import timedelta

import pytest

from candle_intel.ceo.store import CeoError, CeoStore, _now
from candle_intel.research.ledger import Ledger

PLAN = [
    {
        "key": "data",
        "agent": "data_scientist",
        "title": "Check data",
        "instructions": "Validate M5 coverage.",
    },
    {
        "key": "pat",
        "agent": "pattern_analyst",
        "title": "Find sweeps",
        "instructions": "Detect PDH/PDL sweeps.",
        "depends_on": ["data"],
    },
    {
        "key": "strat",
        "agent": "strategy_architect",
        "title": "Write rules",
        "instructions": "Turn sweeps into rules.",
        "depends_on": ["pat"],
    },
    {
        "key": "val",
        "agent": "validator",
        "title": "Backtest",
        "instructions": "Backtest on tier A and B.",
        "depends_on": ["strat"],
    },
]
OUT = {"summary": "Work done, see artifacts.", "limitations": ["synthetic test"]}


@pytest.fixture
def led() -> Ledger:
    return Ledger.from_url("sqlite://")


@pytest.fixture
def store(led) -> CeoStore:
    return CeoStore(led)


def states(store, mid):
    return [t["state"] for t in store.mission(mid)["tasks"]]


def run(store, task, agent, output=OUT):
    store.start_task(task["task_id"], agent)
    return store.finish_task(task["task_id"], agent, output)


def test_plan_runs_in_dependency_order(store) -> None:
    m = store.create_mission("Study PDH/PDL sweeps on M5")
    assert m["status"] == "draft"
    m = store.add_tasks(m["mission_id"], PLAN, note="four steps")
    mid = m["mission_id"]
    assert m["status"] == "running" and m["plan_note"] == "four steps"
    assert states(store, mid) == ["queued", "waiting_deps", "waiting_deps", "waiting_deps"]
    order = []
    while ready := store.ready_tasks(mid):
        assert len(ready) == 1
        t = ready[0]
        order.append(t["agent"])
        run(store, t, t["agent"])
    assert order == ["data_scientist", "pattern_analyst", "strategy_architect", "validator"]
    assert store.mission(mid)["progress"] == {
        "total": 4,
        "done": 4,
        "completed": 4,
        "running": 0,
        "failed": 0,
        "waiting_ceo": 0,
    }


def test_independent_tasks_are_ready_together(store) -> None:
    mid = store.create_mission("Parallel data work please")["mission_id"]
    store.add_tasks(
        mid,
        [
            {
                "key": "a",
                "agent": "data_scientist",
                "title": "Sessions",
                "instructions": "Session stats please.",
            },
            {
                "key": "b",
                "agent": "pattern_analyst",
                "title": "Sweeps",
                "instructions": "Sweep events please.",
            },
        ],
    )
    assert {t["agent"] for t in store.ready_tasks(mid)} == {"data_scientist", "pattern_analyst"}


def test_only_the_owning_agent_can_claim_and_only_once(store) -> None:
    mid = store.add_tasks(store.create_mission("Claim rules test")["mission_id"], PLAN[:1])["mission_id"]
    t = store.ready_tasks(mid)[0]
    with pytest.raises(CeoError, match="belongs to data_scientist"):
        store.start_task(t["task_id"], "validator")
    store.start_task(t["task_id"], "data_scientist")
    with pytest.raises(CeoError, match="not queued"):
        store.start_task(t["task_id"], "data_scientist")


def test_metrics_need_a_real_source(store, led) -> None:
    mid = store.add_tasks(store.create_mission("Source rule test")["mission_id"], PLAN[:1])["mission_id"]
    t = store.ready_tasks(mid)[0]
    store.start_task(t["task_id"], "data_scientist")
    with pytest.raises(Exception, match="must cite"):
        store.finish_task(
            t["task_id"], "data_scientist", OUT | {"findings": [{"text": "wins", "metrics": {"pf": 2.1}}]}
        )
    bad = OUT | {"findings": [{"text": "wins", "metrics": {"pf": 2.1}, "source": {"run_id": "made_up"}}]}
    with pytest.raises(CeoError, match="not in the ledger"):
        store.finish_task(t["task_id"], "data_scientist", bad)
    led.record_run("bt_1", "backtest", "abc", "fam", "A", {"n": 10})
    good = OUT | {
        "findings": [{"text": "profit factor", "metrics": {"pf": 2.1}, "source": {"run_id": "bt_1"}}],
        "artifacts": [{"kind": "run", "ref": "bt_1"}],
    }
    assert store.finish_task(t["task_id"], "data_scientist", good)["state"] == "completed"


def test_bounded_retries_then_dependents_cancelled(store) -> None:
    mid = store.add_tasks(store.create_mission("Retry rules test")["mission_id"], PLAN)["mission_id"]
    t = store.ready_tasks(mid)[0]
    store.start_task(t["task_id"], "data_scientist")
    assert store.fail_task(t["task_id"], "data_scientist", "api down")["state"] == "queued"
    store.start_task(t["task_id"], "data_scientist")
    assert store.fail_task(t["task_id"], "data_scientist", "api down again")["state"] == "failed"
    assert states(store, mid) == ["failed", "cancelled", "cancelled", "cancelled"]
    assert store.ready_tasks(mid) == []


def test_limits_stop_endless_plans(store) -> None:
    mid = store.create_mission("Limit test", limits={"max_tasks": 3, "max_revisions": 1})["mission_id"]
    with pytest.raises(CeoError, match="task limit"):
        store.add_tasks(mid, PLAN)
    store.add_tasks(mid, PLAN[:1])
    t = store.ready_tasks(mid)[0]
    run(store, t, "data_scientist")
    rev = {
        "key": "r1",
        "agent": "data_scientist",
        "title": "Redo",
        "instructions": "Redo with H1 too.",
        "revision_of": t["task_id"],
    }
    store.add_tasks(mid, [rev])
    with pytest.raises(CeoError, match="revision limit"):
        store.add_tasks(mid, [rev | {"key": "r2"}])


def test_cycles_and_unknown_dependencies_rejected(store) -> None:
    mid = store.create_mission("Cycle test mission")["mission_id"]
    with pytest.raises(CeoError, match="cycle"):
        store.add_tasks(
            mid,
            [
                {
                    "key": "a",
                    "agent": "validator",
                    "title": "A task",
                    "instructions": "aaaaaaaaaa",
                    "depends_on": ["b"],
                },
                {
                    "key": "b",
                    "agent": "validator",
                    "title": "B task",
                    "instructions": "bbbbbbbbbb",
                    "depends_on": ["a"],
                },
            ],
        )
    with pytest.raises(CeoError, match="unknown"):
        store.add_tasks(mid, [PLAN[1]])
    assert store.mission(mid)["tasks"] == []  # nothing half-written


def test_ceo_plan_approval_and_task_approval(store) -> None:
    mid = store.create_mission("Approval test", require_plan_approval=True)["mission_id"]
    store.add_tasks(mid, [PLAN[0], PLAN[1] | {"needs_approval": True}])
    assert store.mission(mid)["status"] == "awaiting_approval"
    assert store.ready_tasks(mid) == []
    store.approve_plan(mid)
    run(store, store.ready_tasks(mid)[0], "data_scientist")
    assert states(store, mid) == ["completed", "waiting_ceo"]
    assert store.ready_tasks(mid) == []
    store.approve_task(f"{mid}-t02")
    assert store.ready_tasks(mid)[0]["agent"] == "pattern_analyst"


def test_pause_blocks_new_work_and_cancel_closes_everything(store) -> None:
    mid = store.add_tasks(store.create_mission("Pause test mission")["mission_id"], PLAN)["mission_id"]
    t = store.ready_tasks(mid)[0]
    store.pause(mid)
    assert store.ready_tasks(mid) == []
    with pytest.raises(CeoError, match="paused"):
        store.start_task(t["task_id"], "data_scientist")
    store.resume(mid)
    store.start_task(t["task_id"], "data_scientist")
    store.cancel(mid)
    m = store.mission(mid)
    assert m["status"] == "cancelled" and set(states(store, mid)) == {"cancelled"}
    with pytest.raises(CeoError):
        store.finish_task(t["task_id"], "data_scientist", OUT)


def test_stale_tasks_are_recovered_and_deadline_enforced(store) -> None:
    mid = store.add_tasks(store.create_mission("Recovery test mission")["mission_id"], PLAN)["mission_id"]
    t = store.ready_tasks(mid)[0]
    store.start_task(t["task_id"], "data_scientist")
    assert store.recover() == 0
    assert store.recover(_now() + timedelta(minutes=45)) == 1
    assert store.task(t["task_id"])["state"] == "queued"  # retried: one attempt left
    assert store.recover(_now() + timedelta(hours=7)) >= 1
    m = store.mission(mid)
    assert m["status"] == "failed" and set(states(store, mid)) == {"cancelled"}


def test_report_needs_closed_tasks_and_limitations(store) -> None:
    mid = store.add_tasks(store.create_mission("Report test mission")["mission_id"], PLAN[:1])["mission_id"]
    rep = {
        "headline": "No edge found",
        "summary": "Sweeps did not beat costs on tier A.",
        "verdict": "rejected",
        "limitations": ["5 years of data only"],
    }
    with pytest.raises(CeoError, match="still open"):
        store.submit_report(mid, rep)
    run(store, store.ready_tasks(mid)[0], "data_scientist")
    with pytest.raises(Exception, match="limitation"):
        store.submit_report(mid, rep | {"limitations": []})
    m = store.submit_report(mid, rep)
    assert m["status"] == "completed" and m["report"]["verdict"] == "rejected"
    kinds = [e["kind"] for e in m["events"]]
    assert kinds[0] == "mission_created" and kinds[-1] == "report"


def test_overview_shows_agent_status(store) -> None:
    mid = store.add_tasks(store.create_mission("Overview test mission")["mission_id"], PLAN)["mission_id"]
    store.start_task(store.ready_tasks(mid)[0]["task_id"], "data_scientist")
    ov = store.overview()
    by = {a["agent"]: a for a in ov["agents"]}
    assert by["data_scientist"]["status"] == "working"
    assert by["validator"]["status"] == "idle"
    assert ov["missions"]["running"] == 1 and ov["tasks"]["running"] == 1


def test_director_room_and_ceo_plan_edits(store) -> None:
    mid = store.create_mission("Director room test", require_plan_approval=True)["mission_id"]
    store.post_message(mid, "ceo", "Sirf London session dekhna")
    with pytest.raises(CeoError):
        store.post_message(mid, "validator", "not allowed here")
    store.add_tasks(mid, PLAN)
    t1, t2 = f"{mid}-t01", f"{mid}-t02"
    assert store.edit_task(t2, instructions="Only London session sweeps.")["instructions"].startswith("Only")
    store.drop_task(f"{mid}-t04")
    m = store.send_back_plan(mid, "Validation bhi London-only karo")
    assert m["status"] == "draft" and set(states(store, mid)) == {"cancelled"}
    assert [x["actor"] for x in store.messages(mid)] == ["ceo", "ceo"]
    # re-plan: the sent-back tasks do not use up the task limit (4 cancelled + 4 new ≤ 12 live)
    store.add_tasks(mid, PLAN)
    store.approve_plan(mid)
    run(store, store.ready_tasks(mid)[0], "data_scientist")
    with pytest.raises(CeoError, match="not started"):
        store.edit_task(f"{mid}-t05", title="Too late")
    store.post_message(mid, "director", "Plan badal diya: sab London-only.")
    assert store.messages(mid)[-1]["actor"] == "director"
    assert store.task(t1)["state"] == "cancelled"
