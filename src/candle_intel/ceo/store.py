"""Mission store — the durable record of the CEO Work Lab.

    ceo_missions   one research objective from the owner, its plan note, limits and report
    ceo_tasks      the Director's plan: one row per task, with agent, dependencies and state
    ceo_events     append-only audit trail (who did what, when)

Everything lives in the research ledger's database (same engine and schema), in new
tables — no existing table is touched. The store is the referee, not a worker: agents
(Claude Code subagents, through the ``candle-intelligence-ceo`` MCP server) claim tasks,
log progress and hand in structured outputs; the store enforces the rules:

* tasks run only when their dependencies are completed (``waiting_deps`` until then);
* a task flagged for approval waits for the owner (``waiting_ceo``);
* only the task's own agent can start or finish it, and only from the expected state
  (compare-and-set updates, so two sessions can never both run one task);
* retries, revisions, tasks per mission and the deadline are bounded (no endless loops);
* a finding that states metrics must cite a run or job that exists in the ledger —
  numbers without a source are rejected;
* a task whose heartbeat went quiet (the session stopped) is failed as *stale* and
  retried if attempts remain, so a restart never leaves a mission stuck.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Connection

from candle_intel.research.ledger import Ledger

AGENTS: dict[str, dict[str, str]] = {
    "director": {
        "name": "Research Director",
        "role": "Plans the mission, assigns tasks, reviews the work and writes the report.",
    },
    "data_scientist": {
        "name": "Data Scientist",
        "role": "Checks the data and measures sessions, volatility and market regimes.",
    },
    "pattern_analyst": {
        "name": "Pattern Analyst",
        "role": "Turns chart ideas into exact, measurable patterns and studies what happens after them.",
    },
    "strategy_architect": {
        "name": "Strategy Architect",
        "role": "Writes precise, testable strategy rules (entry, exit, risk) from the findings.",
    },
    "validator": {
        "name": "Validation & Risk Analyst",
        "role": "Independently backtests the strategies with real costs and checks for overfitting.",
    },
}
WORKERS = tuple(a for a in AGENTS if a != "director")

MISSION_STATES = ("draft", "awaiting_approval", "running", "paused", "completed", "failed", "cancelled")
MISSION_FINAL = {"completed", "failed", "cancelled"}
TASK_STATES = (
    "pending",
    "waiting_deps",
    "waiting_ceo",
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
)
TASK_FINAL = {"completed", "failed", "cancelled"}
EDITABLE = ("pending", "waiting_deps", "waiting_ceo", "queued")  # not started yet

STALE_AFTER = timedelta(minutes=30)
BRIDGE_ALIVE = timedelta(seconds=60)


class CeoError(ValueError):
    """A request the rules do not allow (wrong state, wrong agent, limit reached …)."""


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(t: datetime | None) -> datetime | None:
    return None if t is None else (t if t.tzinfo else t.replace(tzinfo=UTC))


# ---------------------------------------------------------------- contracts


class Limits(BaseModel):
    max_tasks: Annotated[int, Field(ge=1, le=40)] = 12
    max_attempts: Annotated[int, Field(ge=1, le=5)] = 2
    max_revisions: Annotated[int, Field(ge=0, le=10)] = 2
    deadline_hours: Annotated[float, Field(gt=0, le=72)] = 6.0


class PlanTask(BaseModel):
    key: Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[a-z0-9_\-]+$")]
    agent: Literal["data_scientist", "pattern_analyst", "strategy_architect", "validator"]
    title: Annotated[str, Field(min_length=3, max_length=160)]
    instructions: Annotated[str, Field(min_length=10, max_length=6000)]
    depends_on: list[str] = []  # keys in this batch, or task ids already in the mission
    needs_approval: bool = False
    revision_of: str | None = None


class Source(BaseModel):
    """Where a number came from: a ledger run or job, or — for read-only statistics that
    make no run (data health, feature distributions) — the dataset id plus the exact
    tool call that reproduces it."""

    run_id: str | None = None
    job_id: str | None = None
    dataset_id: Annotated[str, Field(max_length=80)] | None = None
    query: Annotated[str, Field(max_length=300)] | None = None

    @model_validator(mode="after")
    def _one(self) -> Source:
        if not (self.run_id or self.job_id or (self.dataset_id and self.query)):
            raise ValueError("a source needs a run_id, a job_id, or dataset_id + query")
        return self


class Finding(BaseModel):
    text: Annotated[str, Field(min_length=3, max_length=2000)]
    metrics: dict[str, float | int | str | None] = {}
    source: Source | None = None

    @model_validator(mode="after")
    def _cited(self) -> Finding:
        if self.metrics and self.source is None:
            raise ValueError(
                "a finding with metrics must cite the run_id / job_id (or dataset_id + query) "
                "that produced them (numbers without a source are not accepted)"
            )
        return self


class Artifact(BaseModel):
    kind: Literal["run", "job", "spec", "search", "pattern", "note"]
    ref: Annotated[str, Field(min_length=1, max_length=120)]
    title: Annotated[str, Field(max_length=200)] = ""


class TaskOutput(BaseModel):
    summary: Annotated[str, Field(min_length=10, max_length=6000)]
    findings: list[Finding] = []
    artifacts: list[Artifact] = []
    limitations: list[Annotated[str, Field(max_length=1000)]] = []
    next_steps: list[Annotated[str, Field(max_length=1000)]] = []


class Report(BaseModel):
    """The Director's final report to the owner (plain Hinglish in ``summary``)."""

    headline: Annotated[str, Field(min_length=5, max_length=300)]
    summary: Annotated[str, Field(min_length=20, max_length=12000)]
    verdict: Literal["promising", "inconclusive", "rejected", "blocked"]
    findings: list[Finding] = []
    strategies: list[Annotated[str, Field(max_length=16)]] = []  # spec hashes
    recommendations: list[Annotated[str, Field(max_length=1000)]] = []
    limitations: list[Annotated[str, Field(max_length=1000)]] = []

    @field_validator("limitations")
    @classmethod
    def _honest(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("state at least one limitation — every study has some")
        return v


# ---------------------------------------------------------------- tables


def _tables(md: MetaData) -> dict[str, Table]:
    return {
        "missions": Table(
            "ceo_missions",
            md,
            Column("mission_id", String(40), primary_key=True),
            Column("objective", Text, nullable=False),
            Column("constraints", JSON, nullable=False),
            Column("limits", JSON, nullable=False),
            Column("require_plan_approval", Boolean, nullable=False, default=False),
            Column("status", String(20), nullable=False),
            Column("plan_note", Text, nullable=False, default=""),
            Column("report", JSON),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            Column("started_at", DateTime(timezone=True)),
            Column("finished_at", DateTime(timezone=True)),
        ),
        "tasks": Table(
            "ceo_tasks",
            md,
            Column("task_id", String(48), primary_key=True),
            Column("mission_id", String(40), nullable=False, index=True),
            Column("seq", Integer, nullable=False),
            Column("agent", String(24), nullable=False),
            Column("title", String(160), nullable=False),
            Column("instructions", Text, nullable=False),
            Column("depends_on", JSON, nullable=False),
            Column("needs_approval", Boolean, nullable=False, default=False),
            Column("approved", Boolean, nullable=False, default=False),
            Column("revision_of", String(48)),
            Column("state", String(16), nullable=False),
            Column("attempt", Integer, nullable=False, default=0),
            Column("max_attempts", Integer, nullable=False),
            Column("output", JSON),
            Column("error", Text),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("started_at", DateTime(timezone=True)),
            Column("finished_at", DateTime(timezone=True)),
            Column("heartbeat_at", DateTime(timezone=True)),
        ),
        # Phase 7: runs of the Director started by the local bridge (``ci-ceo-bridge``), with
        # what Claude Code reported it used. Heartbeat of the bridge in ``ceo_bridge``.
        "runs": Table(
            "ceo_runs",
            md,
            Column("run_id", String(40), primary_key=True),
            Column("mission_id", String(40), nullable=False, index=True),
            Column("status", String(12), nullable=False),  # requested running done failed cancelled
            Column("requested_at", DateTime(timezone=True), nullable=False),
            Column("started_at", DateTime(timezone=True)),
            Column("finished_at", DateTime(timezone=True)),
            Column("exit_code", Integer),
            Column("usage", JSON),  # tokens, cost_usd, turns, duration — as Claude Code reports them
            Column("result_tail", Text),
        ),
        "bridge": Table(
            "ceo_bridge",
            md,
            Column("bridge_id", String(20), primary_key=True),
            Column("heartbeat_at", DateTime(timezone=True), nullable=False),
            Column("info", JSON, nullable=False),
        ),
        "events": Table(
            "ceo_events",
            md,
            Column("event_id", Integer, primary_key=True, autoincrement=True),
            Column("mission_id", String(40), nullable=False, index=True),
            Column("task_id", String(48)),
            Column("actor", String(24), nullable=False),  # ceo / director / <agent> / system
            Column("kind", String(24), nullable=False),
            Column("message", Text, nullable=False),
            Column("data", JSON),
            Column("created_at", DateTime(timezone=True), nullable=False),
        ),
    }


# ---------------------------------------------------------------- store


class CeoStore:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self.engine = ledger.engine
        self.md = MetaData(schema=ledger.md.schema)
        self.t = _tables(self.md)
        try:
            self.md.create_all(self.engine, checkfirst=True)
        except Exception:  # noqa: BLE001 - another process created them first; check again
            self.md.create_all(self.engine, checkfirst=True)

    # ------------------------------------------------------------ helpers
    def _event(
        self,
        c: Connection,
        mission_id: str,
        actor: str,
        kind: str,
        message: str,
        task_id: str | None = None,
        data: Any = None,
    ) -> None:
        c.execute(
            insert(self.t["events"]).values(
                mission_id=mission_id,
                task_id=task_id,
                actor=actor,
                kind=kind,
                message=message[:4000],
                data=data,
                created_at=_now(),
            )
        )

    def _mission_row(self, c: Connection, mission_id: str) -> dict[str, Any]:
        m = self.t["missions"]
        r = c.execute(select(m).where(m.c.mission_id == mission_id)).mappings().first()
        if r is None:
            raise KeyError(f"unknown mission {mission_id}")
        return dict(r)

    def _task_row(self, c: Connection, task_id: str) -> dict[str, Any]:
        t = self.t["tasks"]
        r = c.execute(select(t).where(t.c.task_id == task_id)).mappings().first()
        if r is None:
            raise KeyError(f"unknown task {task_id}")
        return dict(r)

    def _tasks_of(self, c: Connection, mission_id: str) -> list[dict[str, Any]]:
        t = self.t["tasks"]
        q = select(t).where(t.c.mission_id == mission_id).order_by(t.c.seq)
        return [dict(r) for r in c.execute(q).mappings()]

    def _set_mission(self, c: Connection, mission_id: str, **values: Any) -> None:
        m = self.t["missions"]
        c.execute(update(m).where(m.c.mission_id == mission_id).values(**values, updated_at=_now()))

    def _cas_task(self, c: Connection, task_id: str, expect: set[str], **values: Any) -> bool:
        """Compare-and-set: change the task only if it is still in one of ``expect``."""
        t = self.t["tasks"]
        res = c.execute(update(t).where((t.c.task_id == task_id) & t.c.state.in_(expect)).values(**values))
        return (res.rowcount or 0) == 1

    def _refresh(self, c: Connection, mission_id: str) -> None:
        """Move waiting tasks forward once their dependencies are settled. Repeats until
        nothing changes, so a failure cancels the whole chain that depends on it."""
        if self._mission_row(c, mission_id)["status"] != "running":
            return
        changed = True
        while changed:
            changed = False
            tasks = self._tasks_of(c, mission_id)
            state = {x["task_id"]: x["state"] for x in tasks}
            for x in tasks:
                if x["state"] not in ("pending", "waiting_deps"):
                    continue
                deps = x["depends_on"] or []
                broken = [d for d in deps if state.get(d) in ("failed", "cancelled")]
                if broken:
                    new = "cancelled"
                elif all(state.get(d) == "completed" for d in deps):
                    new = "waiting_ceo" if x["needs_approval"] and not x["approved"] else "queued"
                else:
                    new = "waiting_deps"
                if new == x["state"]:
                    continue
                extra: dict[str, Any] = {}
                if new == "cancelled":
                    extra = {"error": f"dependency {broken[0]} did not complete", "finished_at": _now()}
                if self._cas_task(c, x["task_id"], {x["state"]}, state=new, **extra):
                    changed = True
                    if new == "cancelled":
                        self._event(
                            c,
                            mission_id,
                            "system",
                            "task_cancelled",
                            f"{x['title']}: a dependency failed",
                            x["task_id"],
                        )

    def _ref_exists(self, c: Connection, kind: str, ref: str) -> bool:
        lt = self.ledger.t
        table, col = {
            "run": (lt["runs"], "run_id"),
            "job": (lt["jobs"], "job_id"),
            "spec": (lt["specs"], "spec_hash"),
            "search": (lt["searches"], "search_id"),
        }.get(kind, (None, None))
        if table is None:
            return True  # pattern / note: free text
        return c.execute(select(table.c[col]).where(table.c[col] == ref)).first() is not None

    def _check_sources(self, c: Connection, findings: list[Finding], artifacts: list[Artifact]) -> None:
        for f in findings:
            if f.source is None:
                continue
            if f.source.run_id and not self._ref_exists(c, "run", f.source.run_id):
                raise CeoError(f"finding cites run {f.source.run_id}, which is not in the ledger")
            if f.source.job_id and not self._ref_exists(c, "job", f.source.job_id):
                raise CeoError(f"finding cites job {f.source.job_id}, which is not in the ledger")
        for a in artifacts:
            if not self._ref_exists(c, a.kind, a.ref):
                raise CeoError(f"artifact {a.kind} {a.ref} is not in the ledger")

    # ------------------------------------------------------------ missions
    def create_mission(
        self,
        objective: str,
        constraints: dict[str, Any] | None = None,
        limits: dict[str, Any] | None = None,
        require_plan_approval: bool = False,
    ) -> dict[str, Any]:
        objective = objective.strip()
        if len(objective) < 10:
            raise CeoError("describe the research objective in at least 10 characters")
        lim = Limits.model_validate(limits or {})
        mission_id = f"m_{_now():%Y%m%dT%H%M%S}_{secrets.token_hex(3)}"
        now = _now()
        with self.engine.begin() as c:
            c.execute(
                insert(self.t["missions"]).values(
                    mission_id=mission_id,
                    objective=objective[:4000],
                    constraints=constraints or {},
                    limits=lim.model_dump(),
                    require_plan_approval=require_plan_approval,
                    status="draft",
                    plan_note="",
                    created_at=now,
                    updated_at=now,
                )
            )
            self._event(c, mission_id, "ceo", "mission_created", objective[:500])
        return self.mission(mission_id)

    def mission(self, mission_id: str, events: int = 200) -> dict[str, Any]:
        e = self.t["events"]
        with self.engine.connect() as c:
            m = self._mission_row(c, mission_id)
            m["tasks"] = self._tasks_of(c, mission_id)
            q = select(e).where(e.c.mission_id == mission_id).order_by(e.c.event_id.desc()).limit(events)
            m["events"] = [dict(r) for r in c.execute(q).mappings()][::-1]
        m["progress"] = _progress(m["tasks"])
        m["runs"] = self.runs(mission_id)
        m["usage"] = _usage(m)
        return m

    def missions(self, limit: int = 50) -> list[dict[str, Any]]:
        m, t = self.t["missions"], self.t["tasks"]
        with self.engine.connect() as c:
            rows = [
                dict(r) for r in c.execute(select(m).order_by(m.c.created_at.desc()).limit(limit)).mappings()
            ]
            ids = [r["mission_id"] for r in rows]
            tasks = [
                dict(r)
                for r in c.execute(
                    select(t.c.mission_id, t.c.state, t.c.agent).where(t.c.mission_id.in_(ids))
                ).mappings()
            ]
        for r in rows:
            mine = [x for x in tasks if x["mission_id"] == r["mission_id"]]
            r["progress"] = _progress(mine)
            r["agents"] = sorted({x["agent"] for x in mine})
            r["has_report"] = r.pop("report", None) is not None
        return rows

    def next_mission(self) -> dict[str, Any] | None:
        """The mission the Director should work on: oldest active one that is not paused."""
        m = self.t["missions"]
        with self.engine.connect() as c:
            r = c.execute(
                select(m.c.mission_id)
                .where(m.c.status.in_(["running", "draft", "awaiting_approval"]))
                .order_by(m.c.created_at)
            ).first()
        return self.mission(r[0], events=30) if r else None

    def version(self, mission_id: str) -> str:
        """A cheap fingerprint that changes whenever the mission, a task or the audit trail
        changes — the live stream sends it, the page refetches when it moves."""
        t, e, r = self.t["tasks"], self.t["events"], self.t["runs"]
        with self.engine.connect() as c:
            row = self._mission_row(c, mission_id)
            ev = c.execute(select(func.max(e.c.event_id)).where(e.c.mission_id == mission_id)).scalar()
            ts = c.execute(
                select(t.c.state, func.count()).where(t.c.mission_id == mission_id).group_by(t.c.state)
            ).all()
            rs = c.execute(
                select(r.c.status, func.count()).where(r.c.mission_id == mission_id).group_by(r.c.status)
            ).all()
        return f"{row['status']}|{ev}|{sorted(ts)}|{sorted(rs)}|{row['updated_at']}"

    def events(self, mission_id: str, after: int = 0) -> list[dict[str, Any]]:
        e = self.t["events"]
        with self.engine.connect() as c:
            q = (
                select(e)
                .where((e.c.mission_id == mission_id) & (e.c.event_id > after))
                .order_by(e.c.event_id)
            )
            return [dict(r) for r in c.execute(q.limit(500)).mappings()]

    # ------------------------------------------------------------ plan
    def add_tasks(
        self, mission_id: str, tasks: list[dict[str, Any]], note: str | None = None, actor: str = "director"
    ) -> dict[str, Any]:
        """Add a plan (or more tasks to it). A draft mission becomes running — or
        awaiting_approval when the owner asked to approve plans first."""
        plan = [PlanTask.model_validate(x) for x in tasks]
        if not plan:
            raise CeoError("a plan needs at least one task")
        with self.engine.begin() as c:
            m = self._mission_row(c, mission_id)
            if m["status"] in MISSION_FINAL:
                raise CeoError(f"mission is {m['status']}")
            if m["status"] == "paused":
                raise CeoError("mission is paused by the CEO")
            lim = Limits.model_validate(m["limits"])
            existing = self._tasks_of(c, mission_id)
            live = [x for x in existing if x["state"] != "cancelled"]  # a sent-back plan does not count
            if len(live) + len(plan) > lim.max_tasks:
                raise CeoError(
                    f"task limit reached: {len(live)} existing + {len(plan)} new > {lim.max_tasks}"
                )
            revisions = sum(1 for x in existing if x["revision_of"]) + sum(1 for p in plan if p.revision_of)
            if revisions > lim.max_revisions:
                raise CeoError(f"revision limit reached ({lim.max_revisions} per mission)")
            known = {x["task_id"] for x in existing}
            keys = [p.key for p in plan]
            if len(set(keys)) != len(keys):
                raise CeoError("task keys must be unique within a plan")
            seq0 = max((x["seq"] for x in existing), default=0)
            ids = {p.key: f"{mission_id}-t{seq0 + i + 1:02d}" for i, p in enumerate(plan)}
            for p in plan:
                for d in p.depends_on:
                    if d not in ids and d not in known:
                        raise CeoError(f"task {p.key!r} depends on unknown {d!r}")
                if p.revision_of and p.revision_of not in known:
                    raise CeoError(f"revision_of {p.revision_of!r} is not a task of this mission")
            _check_acyclic({p.key: [d for d in p.depends_on if d in ids] for p in plan})
            now = _now()
            for i, p in enumerate(plan):
                c.execute(
                    insert(self.t["tasks"]).values(
                        task_id=ids[p.key],
                        mission_id=mission_id,
                        seq=seq0 + i + 1,
                        agent=p.agent,
                        title=p.title,
                        instructions=p.instructions,
                        depends_on=[ids.get(d, d) for d in p.depends_on],
                        needs_approval=p.needs_approval,
                        approved=False,
                        revision_of=p.revision_of,
                        state="pending",
                        attempt=0,
                        max_attempts=lim.max_attempts,
                        created_at=now,
                    )
                )
            if note is not None:
                self._set_mission(c, mission_id, plan_note=note[:6000])
            if m["status"] == "draft":
                if m["require_plan_approval"]:
                    self._set_mission(c, mission_id, status="awaiting_approval")
                else:
                    self._set_mission(c, mission_id, status="running", started_at=now)
            self._event(
                c,
                mission_id,
                actor,
                "plan" if not existing else "tasks_added",
                f"{len(plan)} task(s): " + "; ".join(f"{p.agent}: {p.title}" for p in plan)[:900],
                data={"task_ids": list(ids.values())},
            )
            self._refresh(c, mission_id)
        return self.mission(mission_id)

    def approve_plan(self, mission_id: str) -> dict[str, Any]:
        with self.engine.begin() as c:
            m = self._mission_row(c, mission_id)
            if m["status"] != "awaiting_approval":
                raise CeoError(f"mission is {m['status']}, not awaiting approval")
            self._set_mission(c, mission_id, status="running", started_at=_now())
            self._event(c, mission_id, "ceo", "plan_approved", "CEO approved the plan")
            self._refresh(c, mission_id)
        return self.mission(mission_id)

    # ------------------------------------------------------------ CEO controls
    def pause(self, mission_id: str) -> dict[str, Any]:
        with self.engine.begin() as c:
            m = self._mission_row(c, mission_id)
            if m["status"] not in ("running", "awaiting_approval", "draft"):
                raise CeoError(f"mission is {m['status']}")
            self._set_mission(c, mission_id, status="paused")
            self._event(c, mission_id, "ceo", "paused", "CEO paused the mission (running tasks may finish)")
        return self.mission(mission_id)

    def resume(self, mission_id: str) -> dict[str, Any]:
        with self.engine.begin() as c:
            m = self._mission_row(c, mission_id)
            if m["status"] != "paused":
                raise CeoError(f"mission is {m['status']}, not paused")
            has_tasks = bool(self._tasks_of(c, mission_id))
            self._set_mission(c, mission_id, status="running" if has_tasks else "draft")
            self._event(c, mission_id, "ceo", "resumed", "CEO resumed the mission")
            self._refresh(c, mission_id)
        return self.mission(mission_id)

    def cancel(self, mission_id: str, reason: str = "cancelled by the CEO") -> dict[str, Any]:
        t = self.t["tasks"]
        with self.engine.begin() as c:
            m = self._mission_row(c, mission_id)
            if m["status"] in MISSION_FINAL:
                raise CeoError(f"mission is already {m['status']}")
            c.execute(
                update(t)
                .where((t.c.mission_id == mission_id) & t.c.state.notin_(TASK_FINAL))
                .values(state="cancelled", error=reason, finished_at=_now())
            )
            r = self.t["runs"]
            c.execute(
                update(r)
                .where((r.c.mission_id == mission_id) & (r.c.status == "requested"))
                .values(status="cancelled", finished_at=_now())
            )
            self._set_mission(c, mission_id, status="cancelled", finished_at=_now())
            self._event(c, mission_id, "ceo", "cancelled", reason)
        return self.mission(mission_id)

    def send_back_plan(self, mission_id: str, feedback: str) -> dict[str, Any]:
        """CEO: "change the plan". Open tasks are cancelled, the mission goes back to draft
        and the feedback is posted to the Director Room; the Director re-plans."""
        feedback = feedback.strip()
        if len(feedback) < 5:
            raise CeoError("tell the Director what to change")
        t = self.t["tasks"]
        with self.engine.begin() as c:
            m = self._mission_row(c, mission_id)
            if m["status"] not in ("awaiting_approval", "running"):
                raise CeoError(f"mission is {m['status']}")
            if any(x["state"] == "running" for x in self._tasks_of(c, mission_id)):
                raise CeoError("a task is running — pause and wait for it, or cancel the mission")
            c.execute(
                update(t)
                .where((t.c.mission_id == mission_id) & t.c.state.notin_(TASK_FINAL))
                .values(state="cancelled", error="plan sent back by the CEO", finished_at=_now())
            )
            self._set_mission(c, mission_id, status="draft")
            self._event(c, mission_id, "ceo", "message", feedback[:4000])
            self._event(c, mission_id, "ceo", "plan_sent_back", "CEO sent the plan back for changes")
        return self.mission(mission_id)

    def edit_task(
        self, task_id: str, title: str | None = None, instructions: str | None = None
    ) -> dict[str, Any]:
        """CEO: reword a task that has not started yet."""
        values: dict[str, Any] = {}
        if title is not None:
            if not 3 <= len(title.strip()) <= 160:
                raise CeoError("title must be 3–160 characters")
            values["title"] = title.strip()
        if instructions is not None:
            if not 10 <= len(instructions.strip()) <= 6000:
                raise CeoError("instructions must be 10–6000 characters")
            values["instructions"] = instructions.strip()
        if not values:
            raise CeoError("nothing to change")
        with self.engine.begin() as c:
            x = self._task_row(c, task_id)
            if not self._cas_task(c, task_id, set(EDITABLE), **values):
                raise CeoError(f"task is {x['state']} — only tasks that have not started can be edited")
            msg = f"CEO edited: {values.get('title', x['title'])}"
            self._event(c, x["mission_id"], "ceo", "task_edited", msg, task_id)
        return self.task(task_id)

    def drop_task(self, task_id: str) -> dict[str, Any]:
        """CEO: remove a task that has not started (its dependents are cancelled too)."""
        with self.engine.begin() as c:
            x = self._task_row(c, task_id)
            if not self._cas_task(
                c, task_id, set(EDITABLE), state="cancelled", error="removed by the CEO", finished_at=_now()
            ):
                raise CeoError(f"task is {x['state']} — only tasks that have not started can be removed")
            self._event(c, x["mission_id"], "ceo", "task_removed", f"CEO removed: {x['title']}", task_id)
            self._refresh(c, x["mission_id"])
        return self.task(task_id)

    def post_message(self, mission_id: str, actor: str, text: str) -> dict[str, Any]:
        """Director Room: one message from the CEO or the Director."""
        if actor not in ("ceo", "director"):
            raise CeoError("only the CEO and the Director write in the Director Room")
        text = text.strip()
        if not text:
            raise CeoError("empty message")
        with self.engine.begin() as c:
            self._mission_row(c, mission_id)
            self._event(c, mission_id, actor, "message", text[:4000])
        return {"ok": True}

    def messages(self, mission_id: str) -> list[dict[str, Any]]:
        e = self.t["events"]
        with self.engine.connect() as c:
            self._mission_row(c, mission_id)
            q = (
                select(e)
                .where((e.c.mission_id == mission_id) & (e.c.kind == "message"))
                .order_by(e.c.event_id)
            )
            return [dict(r) for r in c.execute(q).mappings()]

    def approve_task(self, task_id: str) -> dict[str, Any]:
        with self.engine.begin() as c:
            x = self._task_row(c, task_id)
            if x["state"] != "waiting_ceo":
                raise CeoError(f"task is {x['state']}, not waiting for approval")
            self._cas_task(c, task_id, {"waiting_ceo"}, approved=True, state="queued")
            self._event(c, x["mission_id"], "ceo", "task_approved", x["title"], task_id)
        return self.task(task_id)

    # ------------------------------------------------------------ agents
    def task(self, task_id: str) -> dict[str, Any]:
        with self.engine.connect() as c:
            return self._task_row(c, task_id)

    def ready_tasks(self, mission_id: str) -> list[dict[str, Any]]:
        self.recover()
        with self.engine.begin() as c:
            self._refresh(c, mission_id)
            if self._mission_row(c, mission_id)["status"] != "running":
                return []
            return [x for x in self._tasks_of(c, mission_id) if x["state"] == "queued"]

    def start_task(self, task_id: str, agent: str) -> dict[str, Any]:
        with self.engine.begin() as c:
            x = self._task_row(c, task_id)
            if x["agent"] != agent:
                raise CeoError(f"task {task_id} belongs to {x['agent']}, not {agent}")
            m = self._mission_row(c, x["mission_id"])
            if m["status"] != "running":
                raise CeoError(f"mission is {m['status']} — do not start new work")
            now = _now()
            if not self._cas_task(
                c,
                task_id,
                {"queued"},
                state="running",
                attempt=x["attempt"] + 1,
                started_at=now,
                heartbeat_at=now,
                error=None,
            ):
                raise CeoError(f"task is {x['state']}, not queued (another session may have it)")
            self._event(
                c,
                x["mission_id"],
                agent,
                "task_started",
                f"{x['title']} (attempt {x['attempt'] + 1})",
                task_id,
            )
        return self.task(task_id)

    def log(self, task_id: str, agent: str, message: str, data: Any = None) -> None:
        with self.engine.begin() as c:
            x = self._task_row(c, task_id)
            if x["agent"] != agent:
                raise CeoError(f"task {task_id} belongs to {x['agent']}")
            if x["state"] == "running":
                self._cas_task(c, task_id, {"running"}, heartbeat_at=_now())
            self._event(c, x["mission_id"], agent, "log", message, task_id, data)

    def finish_task(self, task_id: str, agent: str, output: dict[str, Any]) -> dict[str, Any]:
        out = TaskOutput.model_validate(output)
        with self.engine.begin() as c:
            x = self._task_row(c, task_id)
            if x["agent"] != agent:
                raise CeoError(f"task {task_id} belongs to {x['agent']}")
            self._check_sources(c, out.findings, out.artifacts)
            if not self._cas_task(
                c, task_id, {"running"}, state="completed", output=out.model_dump(), finished_at=_now()
            ):
                raise CeoError(f"task is {x['state']}, not running")
            self._event(c, x["mission_id"], agent, "task_completed", out.summary[:600], task_id)
            self._refresh(c, x["mission_id"])
        return self.task(task_id)

    def fail_task(self, task_id: str, agent: str, error: str, actor: str | None = None) -> dict[str, Any]:
        with self.engine.begin() as c:
            x = self._task_row(c, task_id)
            if actor is None and x["agent"] != agent:
                raise CeoError(f"task {task_id} belongs to {x['agent']}")
            retry = x["attempt"] < x["max_attempts"]
            if not self._cas_task(
                c,
                task_id,
                {"running"},
                state="queued" if retry else "failed",
                error=error[:4000],
                finished_at=None if retry else _now(),
            ):
                raise CeoError(f"task is {x['state']}, not running")
            left = x["max_attempts"] - x["attempt"]
            msg = f"{x['title']}: {error[:400]}" + (
                f" — will retry ({left} attempt(s) left)" if retry else " — no attempts left"
            )
            self._event(
                c, x["mission_id"], actor or agent, "task_retry" if retry else "task_failed", msg, task_id
            )
            self._refresh(c, x["mission_id"])
        return self.task(task_id)

    def submit_report(self, mission_id: str, report: dict[str, Any]) -> dict[str, Any]:
        rep = Report.model_validate(report)
        with self.engine.begin() as c:
            m = self._mission_row(c, mission_id)
            if m["status"] != "running":
                raise CeoError(f"mission is {m['status']}")
            open_ = [x["title"] for x in self._tasks_of(c, mission_id) if x["state"] not in TASK_FINAL]
            if open_:
                raise CeoError(f"{len(open_)} task(s) are still open: {', '.join(open_[:5])}")
            self._check_sources(c, rep.findings, [Artifact(kind="spec", ref=h) for h in rep.strategies])
            self._set_mission(c, mission_id, status="completed", report=rep.model_dump(), finished_at=_now())
            self._event(c, mission_id, "director", "report", rep.headline)
        return self.mission(mission_id)

    # ------------------------------------------------------------ bridge (Phase 7)
    def request_run(self, mission_id: str) -> dict[str, Any]:
        """CEO: "start the agents now" — queued for the local bridge."""
        r = self.t["runs"]
        with self.engine.begin() as c:
            m = self._mission_row(c, mission_id)
            if m["status"] not in ("draft", "running"):
                raise CeoError(f"mission is {m['status']} — nothing for the agents to do")
            busy = c.execute(
                select(r.c.run_id).where(
                    (r.c.mission_id == mission_id) & r.c.status.in_(["requested", "running"])
                )
            ).first()
            if busy:
                raise CeoError("the agents are already requested or running for this mission")
            run_id = f"cr_{_now():%Y%m%dT%H%M%S}_{secrets.token_hex(3)}"
            c.execute(
                insert(r).values(
                    run_id=run_id, mission_id=mission_id, status="requested", requested_at=_now()
                )
            )
            self._event(c, mission_id, "ceo", "run_requested", "CEO asked the bridge to start the agents")
        return self.run(run_id)

    def run(self, run_id: str) -> dict[str, Any]:
        r = self.t["runs"]
        with self.engine.connect() as c:
            row = c.execute(select(r).where(r.c.run_id == run_id)).mappings().first()
        if row is None:
            raise KeyError(f"unknown run {run_id}")
        return dict(row)

    def runs(self, mission_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        r = self.t["runs"]
        q = select(r).order_by(r.c.requested_at.desc()).limit(limit)
        if mission_id:
            q = q.where(r.c.mission_id == mission_id)
        with self.engine.connect() as c:
            return [dict(x) for x in c.execute(q).mappings()]

    def claim_run(self) -> dict[str, Any] | None:
        """Bridge: take the oldest requested run (compare-and-set, one bridge wins)."""
        r = self.t["runs"]
        with self.engine.begin() as c:
            rows = c.execute(select(r).where(r.c.status == "requested").order_by(r.c.requested_at)).mappings()
            for row in list(rows):
                res = c.execute(
                    update(r)
                    .where((r.c.run_id == row["run_id"]) & (r.c.status == "requested"))
                    .values(status="running", started_at=_now())
                )
                if res.rowcount == 1:
                    self._event(
                        c, row["mission_id"], "system", "run_started", "Bridge started Claude Code (Director)"
                    )
                    return dict(row) | {"status": "running"}
        return None

    def finish_run(
        self, run_id: str, status: str, exit_code: int | None, usage: dict | None, tail: str = ""
    ) -> dict[str, Any]:
        if status not in ("done", "failed", "cancelled"):
            raise CeoError("status must be done, failed or cancelled")
        r = self.t["runs"]
        with self.engine.begin() as c:
            row = c.execute(select(r).where(r.c.run_id == run_id)).mappings().first()
            if row is None:
                raise KeyError(f"unknown run {run_id}")
            res = c.execute(
                update(r)
                .where((r.c.run_id == run_id) & r.c.status.in_(["requested", "running"]))
                .values(
                    status=status,
                    exit_code=exit_code,
                    usage=usage,
                    result_tail=(tail or "")[-4000:],
                    finished_at=_now(),
                )
            )
            if res.rowcount != 1:
                raise CeoError(f"run is already {row['status']}")
            msg = f"Bridge run {status}" + (f" (exit {exit_code})" if exit_code not in (None, 0) else "")
            self._event(c, row["mission_id"], "system", f"run_{status}", msg, data=usage)
        return self.run(run_id)

    def heartbeat(self, info: dict[str, Any], bridge_id: str = "local") -> None:
        b = self.t["bridge"]
        with self.engine.begin() as c:
            res = c.execute(
                update(b).where(b.c.bridge_id == bridge_id).values(heartbeat_at=_now(), info=info)
            )
            if not res.rowcount:
                c.execute(insert(b).values(bridge_id=bridge_id, heartbeat_at=_now(), info=info))

    def bridge_status(self, now: datetime | None = None) -> dict[str, Any]:
        b = self.t["bridge"]
        with self.engine.connect() as c:
            row = c.execute(select(b).where(b.c.bridge_id == "local")).mappings().first()
        if row is None:
            return {"alive": False, "seen": None, "info": {}}
        seen = _aware(row["heartbeat_at"])
        return {"alive": (now or _now()) - seen < BRIDGE_ALIVE, "seen": seen, "info": row["info"]}

    # ------------------------------------------------------------ recovery
    def recover(self, now: datetime | None = None) -> int:
        """Fail running tasks whose session went quiet, and missions past their deadline.
        Safe to call any time; returns how many tasks it changed."""
        now = now or _now()
        m, t = self.t["missions"], self.t["tasks"]
        changed = 0
        with self.engine.connect() as c:
            running = [dict(r) for r in c.execute(select(t).where(t.c.state == "running")).mappings()]
            active = [
                dict(r) for r in c.execute(select(m).where(m.c.status.in_(["running", "paused"]))).mappings()
            ]
        for x in running:
            hb = _aware(x["heartbeat_at"]) or _aware(x["started_at"])
            if hb and now - hb > STALE_AFTER:
                try:
                    self.fail_task(
                        x["task_id"],
                        x["agent"],
                        "stale: no heartbeat for 30 min (session stopped?)",
                        "system",
                    )
                    changed += 1
                except CeoError:
                    pass
        for r in active:
            begun = _aware(r["started_at"])  # the clock starts when work starts, not at the draft
            if begun is None:
                continue
            deadline = begun + timedelta(hours=Limits.model_validate(r["limits"]).deadline_hours)
            if now > deadline:
                with self.engine.begin() as c:
                    res = c.execute(
                        update(t)
                        .where((t.c.mission_id == r["mission_id"]) & t.c.state.notin_(TASK_FINAL))
                        .values(state="cancelled", error="mission deadline passed", finished_at=now)
                    )
                    changed += res.rowcount or 0
                    self._set_mission(c, r["mission_id"], status="failed", finished_at=now)
                    self._event(
                        c,
                        r["mission_id"],
                        "system",
                        "deadline",
                        "Mission deadline passed; open tasks cancelled",
                    )
        return changed

    # ------------------------------------------------------------ dashboard
    def overview(self) -> dict[str, Any]:
        self.recover()
        m, t = self.t["missions"], self.t["tasks"]
        with self.engine.connect() as c:
            by_status = dict(c.execute(select(m.c.status, func.count()).group_by(m.c.status)).all())
            tasks = [dict(r) for r in c.execute(select(t)).mappings()]
            ev = self.t["events"]
            recent = [
                dict(r) for r in c.execute(select(ev).order_by(ev.c.event_id.desc()).limit(15)).mappings()
            ]
        agents = []
        for key, meta in AGENTS.items():
            mine = [x for x in tasks if x["agent"] == key]
            if key == "director":
                mine_events = [e for e in recent if e["actor"] == "director"]
                current = None
            else:
                mine_events = [e for e in recent if e["actor"] == key]
                current = next((x for x in mine if x["state"] == "running"), None)
            agents.append(
                {
                    "agent": key,
                    **meta,
                    "status": "working"
                    if current
                    else ("waiting" if any(x["state"] == "queued" for x in mine) else "idle"),
                    "current_task": {k: current[k] for k in ("task_id", "mission_id", "title", "started_at")}
                    if current
                    else None,
                    "completed": sum(1 for x in mine if x["state"] == "completed"),
                    "failed": sum(1 for x in mine if x["state"] == "failed"),
                    "last_error": next(
                        (
                            x["error"]
                            for x in sorted(mine, key=lambda y: y["seq"], reverse=True)
                            if x["state"] == "failed"
                        ),
                        None,
                    ),
                    "last_activity": mine_events[0] if mine_events else None,
                }
            )
        return {
            "missions": {s: int(by_status.get(s, 0)) for s in MISSION_STATES},
            "tasks": {s: sum(1 for x in tasks if x["state"] == s) for s in TASK_STATES},
            "agents": agents,
            "recent_events": recent,
        }


# ---------------------------------------------------------------- pure helpers


def _progress(tasks: list[dict[str, Any]]) -> dict[str, int]:
    """Counts, not guessed percentages: done / total, from the stored task states."""
    total = len(tasks)
    done = sum(1 for x in tasks if x["state"] in TASK_FINAL)
    return {
        "total": total,
        "done": done,
        "completed": sum(1 for x in tasks if x["state"] == "completed"),
        "running": sum(1 for x in tasks if x["state"] == "running"),
        "failed": sum(1 for x in tasks if x["state"] == "failed"),
        "waiting_ceo": sum(1 for x in tasks if x["state"] == "waiting_ceo"),
    }


def _usage(m: dict[str, Any]) -> dict[str, Any]:
    """What a mission consumed, from stored facts only: tasks and attempts, the engine runs /
    jobs its outputs cite, wall time, and — for bridge runs — the tokens and notional cost
    Claude Code reported. Interactive /ceo-run sessions report no tokens to the app."""
    refs: dict[str, set[str]] = {"run": set(), "job": set(), "spec": set()}
    outputs = [t["output"] for t in m["tasks"] if t.get("output")] + (
        [m["report"]] if m.get("report") else []
    )
    for o in outputs:
        for f in o.get("findings", []):
            src = f.get("source") or {}
            for k in ("run", "job"):
                if src.get(f"{k}_id"):
                    refs[k].add(src[f"{k}_id"])
        for a in o.get("artifacts", []):
            if a["kind"] in refs:
                refs[a["kind"]].add(a["ref"])
        for h in o.get("strategies", []):
            refs["spec"].add(h)
    start, end = _aware(m.get("started_at")), _aware(m.get("finished_at")) or _now()
    tok = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "turns": 0}
    measured = 0
    for r in m.get("runs", []):
        u = r.get("usage") or {}
        if u:
            measured += 1
        for k in tok:
            tok[k] += u.get(k) or 0
    return {
        "tasks": len(m["tasks"]),
        "attempts": sum(t["attempt"] for t in m["tasks"]),
        "engine_runs_cited": len(refs["run"]),
        "jobs_cited": len(refs["job"]),
        "strategies": len(refs["spec"]),
        "minutes": round((end - start).total_seconds() / 60, 1) if start else None,
        "bridge_runs": len(m.get("runs", [])),
        "bridge_runs_measured": measured,
        **({k: round(v, 4) if isinstance(v, float) else v for k, v in tok.items()} if measured else {}),
    }


def _check_acyclic(graph: dict[str, list[str]]) -> None:
    seen: dict[str, int] = {}  # 1 = on stack, 2 = done

    def visit(n: str) -> None:
        if seen.get(n) == 2:
            return
        if seen.get(n) == 1:
            raise CeoError(f"the plan has a dependency cycle at {n!r}")
        seen[n] = 1
        for d in graph.get(n, []):
            visit(d)
        seen[n] = 2

    for n in graph:
        visit(n)
