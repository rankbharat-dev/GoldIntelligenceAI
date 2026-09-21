-- Candle Intelligence — CEO Work Lab tables (docs/requirements/2026-09-21_ceo-work-lab.md)
-- Additive migration: new tables only; no existing table is altered.
-- The API also creates these on start (candle_intel.ceo.store, CREATE IF NOT EXISTS),
-- so an existing database needs no manual step. This file documents the shape.

CREATE SCHEMA IF NOT EXISTS ci;
SET search_path TO ci;

CREATE TABLE IF NOT EXISTS ceo_missions (
    mission_id             VARCHAR(40) PRIMARY KEY,           -- m_YYYYmmddTHHMMSS_xxxxxx
    objective              TEXT NOT NULL,
    constraints            JSON NOT NULL,
    limits                 JSON NOT NULL,                     -- max_tasks, max_attempts, max_revisions, deadline_hours
    require_plan_approval  BOOLEAN NOT NULL DEFAULT FALSE,
    status                 VARCHAR(20) NOT NULL,              -- draft awaiting_approval running paused completed failed cancelled
    plan_note              TEXT NOT NULL DEFAULT '',
    report                 JSON,
    created_at             TIMESTAMPTZ NOT NULL,
    updated_at             TIMESTAMPTZ NOT NULL,
    started_at             TIMESTAMPTZ,
    finished_at            TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ceo_tasks (
    task_id         VARCHAR(48) PRIMARY KEY,                  -- <mission_id>-tNN
    mission_id      VARCHAR(40) NOT NULL,
    seq             INTEGER NOT NULL,
    agent           VARCHAR(24) NOT NULL,                     -- data_scientist pattern_analyst strategy_architect validator
    title           VARCHAR(160) NOT NULL,
    instructions    TEXT NOT NULL,
    depends_on      JSON NOT NULL,                            -- task ids
    needs_approval  BOOLEAN NOT NULL DEFAULT FALSE,
    approved        BOOLEAN NOT NULL DEFAULT FALSE,
    revision_of     VARCHAR(48),
    state           VARCHAR(16) NOT NULL,                     -- pending waiting_deps waiting_ceo queued running completed failed cancelled
    attempt         INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL,
    output          JSON,                                     -- summary, findings (cited), artifacts, limitations
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    heartbeat_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_ceo_tasks_mission_id ON ceo_tasks (mission_id);

CREATE TABLE IF NOT EXISTS ceo_events (                       -- append-only audit trail
    event_id    SERIAL PRIMARY KEY,
    mission_id  VARCHAR(40) NOT NULL,
    task_id     VARCHAR(48),
    actor       VARCHAR(24) NOT NULL,                         -- ceo director <agent> system
    kind        VARCHAR(24) NOT NULL,
    message     TEXT NOT NULL,
    data        JSON,
    created_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ceo_events_mission_id ON ceo_events (mission_id);

-- Phase 7: runs of the Director started by the local bridge, and the bridge's heartbeat.
CREATE TABLE IF NOT EXISTS ceo_runs (
    run_id        VARCHAR(40) PRIMARY KEY,                  -- cr_YYYYmmddTHHMMSS_xxxxxx
    mission_id    VARCHAR(40) NOT NULL,
    status        VARCHAR(12) NOT NULL,                     -- requested running done failed cancelled
    requested_at  TIMESTAMPTZ NOT NULL,
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ,
    exit_code     INTEGER,
    usage         JSON,                                     -- tokens, cost_usd, turns as Claude Code reports them
    result_tail   TEXT
);
CREATE INDEX IF NOT EXISTS ix_ceo_runs_mission_id ON ceo_runs (mission_id);

CREATE TABLE IF NOT EXISTS ceo_bridge (
    bridge_id     VARCHAR(20) PRIMARY KEY,
    heartbeat_at  TIMESTAMPTZ NOT NULL,
    info          JSON NOT NULL
);
