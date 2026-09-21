-- Candle Intelligence — metadata schema v1 (blueprint v1.1 §14.3)
-- Large numerical data lives in Parquet. PostgreSQL holds lineage, experiments and results.
-- Applied automatically on first container start. Later changes go through migrations.

CREATE SCHEMA IF NOT EXISTS ci;
SET search_path TO ci;

-- ---------------------------------------------------------------- data lineage
CREATE TABLE datasets (
    dataset_id        TEXT PRIMARY KEY,               -- e.g. xauusd_m1_v0001
    timeframe         TEXT NOT NULL CHECK (timeframe IN ('TICK','M1','M5','M15','H1')),
    broker            TEXT NOT NULL,
    broker_server     TEXT,
    broker_symbol     TEXT NOT NULL,
    price_side        TEXT NOT NULL DEFAULT 'bid',
    clock             TEXT NOT NULL DEFAULT 'broker_server',
    first_ts_server   TIMESTAMP NOT NULL,
    last_ts_server    TIMESTAMP NOT NULL,
    row_count         BIGINT NOT NULL,
    parquet_path      TEXT NOT NULL,
    sha256            TEXT NOT NULL,
    parent_dataset_id TEXT REFERENCES datasets(dataset_id),
    config_hash       TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE symbol_specs (
    spec_id      BIGSERIAL PRIMARY KEY,
    broker       TEXT NOT NULL,
    broker_symbol TEXT NOT NULL,
    captured_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    spec         JSONB NOT NULL
);

CREATE TABLE ingestion_log (
    ingestion_id  BIGSERIAL PRIMARY KEY,
    dataset_id    TEXT REFERENCES datasets(dataset_id),
    timeframe     TEXT NOT NULL,
    window_start  TIMESTAMP NOT NULL,
    window_end    TIMESTAMP NOT NULL,
    rows_returned BIGINT,
    status        TEXT NOT NULL CHECK (status IN ('ok','empty','error','retried')),
    error         TEXT,
    logged_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE data_quality_runs (
    run_id      BIGSERIAL PRIMARY KEY,
    dataset_id  TEXT NOT NULL REFERENCES datasets(dataset_id),
    passed      BOOLEAN NOT NULL,
    findings    JSONB NOT NULL,
    research_window_start TIMESTAMP,
    research_window_end   TIMESTAMP,
    rollover_minute_server TEXT,
    run_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE cost_models (
    cost_model_id TEXT PRIMARY KEY,
    dataset_id    TEXT NOT NULL REFERENCES datasets(dataset_id),
    params        JSONB NOT NULL,          -- conditional spread cells, slippage, commission, swap
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- research
CREATE TABLE experiments (
    experiment_id  BIGSERIAL PRIMARY KEY,
    name           TEXT NOT NULL,
    code_version   TEXT NOT NULL,
    config         JSONB NOT NULL,
    config_hash    TEXT NOT NULL,
    dataset_id     TEXT REFERENCES datasets(dataset_id),
    cost_model_id  TEXT REFERENCES cost_models(cost_model_id),
    feature_schema_version TEXT,
    status         TEXT NOT NULL DEFAULT 'created',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Pre-registration (§9.2): written BEFORE outcomes are computed.
CREATE TABLE pattern_definitions (
    pattern_id         TEXT NOT NULL,
    version            INT  NOT NULL,
    description        TEXT NOT NULL,
    expected_direction TEXT NOT NULL CHECK (expected_direction IN ('long','short','either')),
    horizon_bars       INT  NOT NULL,
    min_sample_dev     INT  NOT NULL DEFAULT 1000,
    min_sample_val     INT  NOT NULL DEFAULT 250,
    rule               JSONB NOT NULL,
    registered_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (pattern_id, version)
);

CREATE TABLE pattern_occurrences (
    occurrence_id  BIGSERIAL PRIMARY KEY,
    pattern_id     TEXT NOT NULL,
    version        INT  NOT NULL,
    dataset_id     TEXT NOT NULL REFERENCES datasets(dataset_id),
    event_ts       TIMESTAMP NOT NULL,
    available_at   TIMESTAMP NOT NULL CHECK (available_at >= event_ts),
    tier           TEXT NOT NULL CHECK (tier IN ('A','B','C')),
    features       JSONB,
    FOREIGN KEY (pattern_id, version) REFERENCES pattern_definitions(pattern_id, version)
);

CREATE TABLE strategies (
    strategy_id   TEXT NOT NULL,
    version       INT  NOT NULL,
    family        TEXT NOT NULL,
    rules         JSONB NOT NULL,
    status        TEXT NOT NULL DEFAULT 'research'
                  CHECK (status IN ('research','candidate','rejected','paper-test')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (strategy_id, version)
);

-- Trials accounting (§9.3): every backtest increments its family's count.
CREATE TABLE trial_counts (
    family      TEXT PRIMARY KEY,
    trials      BIGINT NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE backtest_runs (
    run_id         BIGSERIAL PRIMARY KEY,
    experiment_id  BIGINT REFERENCES experiments(experiment_id),
    strategy_id    TEXT NOT NULL,
    strategy_version INT NOT NULL,
    tier           TEXT NOT NULL CHECK (tier IN ('A','B','C')),
    cost_scenario  TEXT NOT NULL CHECK (cost_scenario IN ('optimistic','base','pessimistic')),
    ambiguity_policy TEXT NOT NULL DEFAULT 'pessimistic',
    ambiguity_rate DOUBLE PRECISION,
    trial_number   BIGINT NOT NULL,
    metrics        JSONB NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (strategy_id, strategy_version) REFERENCES strategies(strategy_id, version)
);

CREATE TABLE backtest_trades (
    trade_id     BIGSERIAL PRIMARY KEY,
    run_id       BIGINT NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
    side         TEXT NOT NULL CHECK (side IN ('long','short')),
    signal_ts    TIMESTAMP NOT NULL,
    entry_ts     TIMESTAMP NOT NULL,
    entry_price  DOUBLE PRECISION NOT NULL,
    exit_ts      TIMESTAMP NOT NULL,
    exit_price   DOUBLE PRECISION NOT NULL,
    exit_reason  TEXT NOT NULL,
    r_multiple   DOUBLE PRECISION NOT NULL,
    mfe_r        DOUBLE PRECISION,
    mae_r        DOUBLE PRECISION,
    ambiguous    BOOLEAN NOT NULL DEFAULT FALSE,
    spread_source TEXT CHECK (spread_source IN ('measured','modeled'))
);

-- Sealed holdout (§9.1). One access per strategy family.
CREATE TABLE holdout_access_log (
    access_id    BIGSERIAL PRIMARY KEY,
    family       TEXT NOT NULL,
    strategy_id  TEXT NOT NULL,
    reason       TEXT NOT NULL,
    accessed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX holdout_one_access_per_family ON holdout_access_log (family);

-- ---------------------------------------------------------------- models
CREATE TABLE models (
    model_id     TEXT PRIMARY KEY,
    experiment_id BIGINT REFERENCES experiments(experiment_id),
    algorithm    TEXT NOT NULL,
    artifact_uri TEXT NOT NULL,
    train_start  TIMESTAMP NOT NULL,
    train_end    TIMESTAMP NOT NULL,
    status       TEXT NOT NULL DEFAULT 'research'
                 CHECK (status IN ('research','candidate','rejected','paper-test')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE model_evaluations (
    evaluation_id BIGSERIAL PRIMARY KEY,
    model_id      TEXT NOT NULL REFERENCES models(model_id),
    tier          TEXT NOT NULL CHECK (tier IN ('A','B','C')),
    metrics       JSONB NOT NULL,
    evaluated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- paper trading
CREATE TABLE paper_signals (
    signal_id    BIGSERIAL PRIMARY KEY,
    strategy_id  TEXT NOT NULL,
    strategy_version INT NOT NULL,
    signal_ts    TIMESTAMP NOT NULL,
    side         TEXT NOT NULL CHECK (side IN ('long','short')),
    payload      JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE paper_trades (
    paper_trade_id BIGSERIAL PRIMARY KEY,
    signal_id    BIGINT NOT NULL REFERENCES paper_signals(signal_id),
    entry_ts     TIMESTAMP,
    entry_price  DOUBLE PRECISION,
    exit_ts      TIMESTAMP,
    exit_price   DOUBLE PRECISION,
    r_multiple   DOUBLE PRECISION,
    observed_spread DOUBLE PRECISION,
    simulated_slippage DOUBLE PRECISION
);

-- Threshold changes (§15) must be recorded here BEFORE the affected result is computed.
CREATE TABLE research_notes (
    note_id     BIGSERIAL PRIMARY KEY,
    author      TEXT NOT NULL,
    topic       TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
