"""Research ledger — the durable record behind the §9 guardrails.

    research_specs      every strategy spec ever saved (content-hashed, with lineage)
    research_trials     one row per (family, spec) ever evaluated → the true trial count
    research_runs       every backtest / optimisation / validation run and its headline
    holdout_access_log  tier-C unseals; the database allows one per family, ever
    research_jobs       long-running work and its progress (Phase 6)

The trial count is *derived* (rows per family), so it cannot drift from what was
actually evaluated. Re-running an identical spec is not a new trial; any change to
its rules is. Tables live in PostgreSQL (schema ``ci``) by default; tests use SQLite.
Run files (trades, reports) stay in ``storage/research/runs`` — the ledger indexes them.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from candle_intel.config import get_settings


class HoldoutError(PermissionError):
    """Tier C was requested without a valid, unused unseal."""


def _now() -> datetime:
    return datetime.now(UTC)


def _tables(schema: str | None) -> tuple[MetaData, dict[str, Table]]:
    md = MetaData(schema=schema)
    t = {
        "specs": Table(
            "research_specs",
            md,
            Column("spec_hash", String(16), primary_key=True),
            Column("family", String(60), nullable=False, index=True),
            Column("name", String(80), nullable=False),
            Column("spec", JSON, nullable=False),
            Column("created_by", String(16), nullable=False),
            Column("parent_hash", String(16)),
            Column("favourite", Boolean, nullable=False, default=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
        ),
        "trials": Table(
            "research_trials",
            md,
            Column("family", String(60), primary_key=True),
            Column("spec_hash", String(16), primary_key=True),
            Column("first_tier", String(1), nullable=False),
            Column("sharpe", Float),
            Column("n_trades", Integer),
            Column("source", String(24), nullable=False),  # backtest / optimize / walkforward / engine
            Column("created_at", DateTime(timezone=True), nullable=False),
        ),
        "runs": Table(
            "research_runs",
            md,
            Column("run_id", String(40), primary_key=True),
            Column("kind", String(16), nullable=False),
            Column("spec_hash", String(16), nullable=False, index=True),
            Column("family", String(60), nullable=False),
            Column("tier", String(4), nullable=False),
            Column("summary", JSON, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
        ),
        "holdout": Table(
            "holdout_access_log",
            md,
            Column("access_id", Integer, primary_key=True, autoincrement=True),
            Column("family", Text, nullable=False),
            Column("strategy_id", Text, nullable=False),
            Column("reason", Text, nullable=False),
            Column("accessed_at", DateTime(timezone=True), nullable=False, default=_now),
            UniqueConstraint("family", name="holdout_one_access_per_family"),
        ),
        "jobs": Table(
            "research_jobs",
            md,
            Column("job_id", String(40), primary_key=True),
            Column("kind", String(16), nullable=False),
            Column("title", String(160), nullable=False),
            Column("params", JSON, nullable=False),
            Column("status", String(12), nullable=False),  # queued running done failed cancelled
            Column("progress", Float, nullable=False, default=0.0),
            Column("message", Text, nullable=False, default=""),
            Column("result", JSON),
            Column("error", Text),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("started_at", DateTime(timezone=True)),
            Column("finished_at", DateTime(timezone=True)),
        ),
    }
    return md, t


class Ledger:
    def __init__(self, engine: Engine, schema: str | None) -> None:
        self.engine = engine
        self.md, self.t = _tables(schema)
        self.md.create_all(engine, checkfirst=True)

    @classmethod
    def from_url(cls, url: str) -> Ledger:
        if url.startswith("sqlite"):
            # tests: one shared connection, usable from the job thread too
            eng = create_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
            return cls(eng, None)
        return cls(create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5}), "ci")

    # ------------------------------------------------------------ specs
    def save_spec(
        self, spec_hash: str, family: str, name: str, spec: dict, created_by: str, parent: str | None
    ) -> bool:
        """True if new. The same rules saved again keep their first record."""
        with self.engine.begin() as c:
            if c.execute(
                select(self.t["specs"].c.spec_hash).where(self.t["specs"].c.spec_hash == spec_hash)
            ).first():
                return False
            c.execute(
                insert(self.t["specs"]).values(
                    spec_hash=spec_hash,
                    family=family,
                    name=name,
                    spec=spec,
                    created_by=created_by,
                    parent_hash=parent,
                    favourite=False,
                    created_at=_now(),
                )
            )
            return True

    def spec(self, spec_hash: str) -> dict[str, Any] | None:
        with self.engine.connect() as c:
            r = (
                c.execute(select(self.t["specs"]).where(self.t["specs"].c.spec_hash == spec_hash))
                .mappings()
                .first()
            )
        return dict(r) if r else None

    def specs(self) -> list[dict[str, Any]]:
        s, tr, ru = self.t["specs"], self.t["trials"], self.t["runs"]
        runs = (
            select(ru.c.spec_hash, func.count().label("runs"), func.max(ru.c.created_at).label("last_run"))
            .group_by(ru.c.spec_hash)
            .subquery()
        )
        fam = select(tr.c.family, func.count().label("family_trials")).group_by(tr.c.family).subquery()
        q = (
            select(s, runs.c.runs, runs.c.last_run, fam.c.family_trials)
            .outerjoin(runs, runs.c.spec_hash == s.c.spec_hash)
            .outerjoin(fam, fam.c.family == s.c.family)
            .order_by(s.c.created_at.desc())
        )
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(q).mappings()]

    def set_favourite(self, spec_hash: str, on: bool) -> None:
        with self.engine.begin() as c:
            c.execute(
                update(self.t["specs"]).where(self.t["specs"].c.spec_hash == spec_hash).values(favourite=on)
            )

    # ------------------------------------------------------------ trials
    def record_trial(
        self, family: str, spec_hash: str, tier: str, sharpe: float | None, n_trades: int, source: str
    ) -> int:
        """Count a variant once per family; returns the family's trial count after it."""
        tr = self.t["trials"]
        with self.engine.begin() as c:
            try:
                with c.begin_nested():
                    c.execute(
                        insert(tr).values(
                            family=family,
                            spec_hash=spec_hash,
                            first_tier=tier,
                            sharpe=sharpe,
                            n_trades=n_trades,
                            source=source,
                            created_at=_now(),
                        )
                    )
            except IntegrityError:
                pass
            return int(
                c.execute(select(func.count()).select_from(tr).where(tr.c.family == family)).scalar_one()
            )

    def trials(self, family: str) -> tuple[int, list[float]]:
        tr = self.t["trials"]
        with self.engine.connect() as c:
            rows = c.execute(select(tr.c.sharpe).where(tr.c.family == family)).all()
        return len(rows), [r[0] for r in rows if r[0] is not None]

    def families(self) -> list[dict[str, Any]]:
        tr, h = self.t["trials"], self.t["holdout"]
        q = (
            select(tr.c.family, func.count().label("trials"), func.max(tr.c.created_at).label("last_trial"))
            .group_by(tr.c.family)
            .order_by(tr.c.family)
        )
        with self.engine.connect() as c:
            fams = [dict(r) for r in c.execute(q).mappings()]
            unsealed = {r.family: r for r in c.execute(select(h)).all()}
        for f in fams:
            u = unsealed.get(f["family"])
            f["holdout_used"] = u is not None
            f["holdout_strategy"] = u.strategy_id if u else None
        return fams

    # ------------------------------------------------------------ runs
    def record_run(
        self, run_id: str, kind: str, spec_hash: str, family: str, tier: str, summary: dict
    ) -> None:
        with self.engine.begin() as c:
            c.execute(
                insert(self.t["runs"]).values(
                    run_id=run_id,
                    kind=kind,
                    spec_hash=spec_hash,
                    family=family,
                    tier=tier,
                    summary=json.loads(json.dumps(summary, default=str)),
                    created_at=_now(),
                )
            )

    def runs(self, spec_hash: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        ru = self.t["runs"]
        q = select(ru).order_by(ru.c.created_at.desc()).limit(limit)
        if spec_hash:
            q = q.where(ru.c.spec_hash == spec_hash)
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(q).mappings()]

    # ------------------------------------------------------------ holdout
    def holdout_status(self, family: str) -> dict[str, Any] | None:
        h = self.t["holdout"]
        with self.engine.connect() as c:
            r = c.execute(select(h).where(h.c.family == family)).mappings().first()
        return dict(r) if r else None

    def unseal(self, family: str, spec_hash: str, reason: str) -> dict[str, Any]:
        """The one tier-C access of a family. Raises if it was already used."""
        if len(reason.strip()) < 10:
            raise HoldoutError("state a reason (at least 10 characters) — it is logged permanently")
        h = self.t["holdout"]
        try:
            with self.engine.begin() as c:
                c.execute(
                    insert(h).values(
                        family=family, strategy_id=spec_hash, reason=reason.strip(), accessed_at=_now()
                    )
                )
        except IntegrityError as e:
            prev = self.holdout_status(family)
            raise HoldoutError(
                f"family {family!r} already used its holdout on {prev['accessed_at']} "
                f"(strategy {prev['strategy_id']}). Tier C is now development data for this family."
            ) from e
        return self.holdout_status(family) or {}

    # ------------------------------------------------------------ jobs
    def job_create(self, job_id: str, kind: str, title: str, params: dict) -> None:
        with self.engine.begin() as c:
            c.execute(
                insert(self.t["jobs"]).values(
                    job_id=job_id,
                    kind=kind,
                    title=title,
                    params=params,
                    status="queued",
                    progress=0.0,
                    message="queued",
                    created_at=_now(),
                )
            )

    def job_update(self, job_id: str, **values: Any) -> None:
        if "result" in values:
            values["result"] = json.loads(json.dumps(values["result"], default=str))
        with self.engine.begin() as c:
            c.execute(update(self.t["jobs"]).where(self.t["jobs"].c.job_id == job_id).values(**values))

    def job(self, job_id: str) -> dict[str, Any] | None:
        j = self.t["jobs"]
        with self.engine.connect() as c:
            r = c.execute(select(j).where(j.c.job_id == job_id)).mappings().first()
        return dict(r) if r else None

    def jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        j = self.t["jobs"]
        cols = [c for c in j.c if c.name != "result"]
        with self.engine.connect() as c:
            return [
                dict(r)
                for r in c.execute(select(*cols).order_by(j.c.created_at.desc()).limit(limit)).mappings()
            ]

    def jobs_interrupted(self) -> int:
        """On start-up: work that was running when the process stopped cannot resume."""
        j = self.t["jobs"]
        with self.engine.begin() as c:
            res = c.execute(
                update(j)
                .where(j.c.status.in_(["queued", "running"]))
                .values(
                    status="failed",
                    error="interrupted: the API stopped while this job was running",
                    finished_at=_now(),
                )
            )
            return res.rowcount or 0

    def _wipe(self) -> None:  # tests only
        with self.engine.begin() as c:
            for t in self.t.values():
                c.execute(delete(t))


@lru_cache(maxsize=1)
def default_ledger() -> Ledger:
    s = get_settings()
    url = (s.research_db_url or s.postgres_dsn).get_secret_value()
    return Ledger.from_url(url)
