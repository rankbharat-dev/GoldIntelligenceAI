# Session Handoff — read this first

Last updated: 2026-09-21 · End of Phase 1 · Owner communicates in Hinglish.

## 1. What this project is

Candle Intelligence AI: an **XAUUSD-only** research platform that tests whether candle
behaviour, market structure and chart geometry carry a tradeable edge **after realistic
costs**. Research + paper trading only — **no real-money execution**. Must stay
**independent of Shiibaa** (never read, modify or integrate Shiibaa code).

Governing spec: [ARCHITECTURE_v1.2.md](ARCHITECTURE_v1.2.md). Library choices:
[TECH_SELECTION.md](TECH_SELECTION.md). Owner requirements (verbatim):
[requirements/](requirements/).

## 2. Non-negotiable rules (enforced by tests)

- `MetaTrader5` is imported **only** by `src/candle_intel/ingest/mt5_session.py`, which
  exposes an allowlist of market-data functions. No trading, order, position, deal-history
  or account function may be referenced anywhere (AST test).
- Research code (`candle_intel.data/costs/features/...`) and the API (`services/api`) read
  **Parquet only** — they may not import the ingest layer or the MCP server.
- MCP server (`services/mt5_mcp`) is read-only, XAUUSD-only, no symbol parameter, no code
  execution, capped output. Its tool list is pinned by `tests/unit/test_mcp_surface.py`.
- Raw data is read-only after write; every dataset has a manifest with SHA-256 hashes.
- `available_at` / no-look-ahead rule (blueprint §7) applies to every feature from Phase 3.
- Success thresholds in blueprint §15 are pre-committed; change only with a dated note first.

## 3. Environment facts

| Item | Value |
|---|---|
| OS / shells | Windows 11; Python 3.12 venv at `.venv` (managed with `python -m uv`) |
| MT5 broker | **Exness Technologies Ltd, server Exness-MT5Trial7, demo account** |
| Broker identity | From `account_info().company/.server` — `terminal_info().company` is the vendor ("MetaQuotes Ltd."), never the broker |
| Broker clock | UTC+0 (measured) |
| Terminal safety | Algo Trading OFF; investor-password login not used (optional) |
| Other terminal data | The MT5 data dir also holds Exness **real** account servers — never touch them |
| PostgreSQL | Docker container `candle-intelligence-postgres` on **127.0.0.1:5434** (5433 belongs to another project, `staff-manager-pg`) |
| GitHub | https://github.com/rankbharat-dev/GoldIntelligenceAI — **public**; commits use `290257992+rankbharat-dev@users.noreply.github.com` |
| Git policy | Commit / push only when the owner asks |

## 4. What exists (Phases 0–1 complete)

| Component | Path | Command |
|---|---|---|
| MT5 gateway | `src/candle_intel/ingest/mt5_session.py` | — |
| Ingestion CLI | `src/candle_intel/ingest/cli.py`, `bulk.py` | `ci-ingest status \| probe \| snapshot \| raw --ticks --tick-days 260` |
| Data engine | `src/candle_intel/data/{clock,quality,aggregate,build}.py` | `ci-data build \| list` |
| Metadata DB | `src/candle_intel/db.py`, `infra/postgres/init/001_schema.sql` | `docker compose up -d` |
| Research API | `services/api/ci_api/main.py` | `ci-api` → :8000 |
| MCP server | `services/mt5_mcp/ci_mt5_mcp/server.py`, `.mcp.json` | stdio |
| Web Chart Viewer | `apps/web` (Next.js 16, shadcn base-nova, Lightweight Charts 5) | `npm --prefix apps/web run dev` → :3000 |
| Tests | `tests/{unit,leakage,integration}` | `pytest` (35 pass incl. `-m mt5`) |

Data on disk (git-ignored, in `storage/`):
- Raw `xauusd_exness-mt5trial7_20260921T071357Z`: M1 2021-07-01 → 2026-09-21 (1.84 M bars),
  broker M5/M15/H1 reference, **223 days of ticks (70.8 M, ~500 MB)** in `ticks/YYYY-MM-DD.parquet`.
- Derived `xauusd_exness-mt5trial7_d20260921T071531Z`: `M1/M5/M15/H1.parquet` with `ts_utc`
  and `ts_server`, `quality.json`, `clock_weekly.parquet`, `manifest.json`.
  Research window 2021-07-05 → present (5.2 y). M5/M15/H1 match broker bars 100 %.

## 5. Known data facts to carry forward

- Prices are **bid**. Ask must be reconstructed from the spread model (Phase 2).
- Per-bar `spread_points` is a snapshot; ~6,100 M1 bars report spread ≤ 0 — do not trust it
  for costs. Use the tick archive.
- 500 price-spike bars flagged (not removed); 96 holiday/long closures.
- Daily break: 16:58 New York, ~63 min. Gaps are classified in `quality.json`.
- MT5 quirks handled in the gateway: naive datetimes are read as machine-local time
  (bounds are encoded explicitly); over-limit ranges fail with "Invalid params" (chunked);
  the forming bar is returned (marked/excluded); empty windows can return one stale bar.
- Clock inference wraps offsets to ±12 h so "New York + 7" brokers (break at 00:00 server
  time, next calendar day) work; covered by a synthetic UTC+2/+3 DST test.

## 6. Next: Phase 2 — Cost Model (blueprint §6)

Goal: a validated, versioned cost model in `src/candle_intel/costs/`, built from the tick
archive only.

1. Load ticks (`storage/raw/xauusd/<raw>/ticks/*.parquet`, `ts_server`, bid, ask); convert
   to UTC with the clock model from the derived dataset (`clock_weekly.parquet`).
2. Spread = ask − bid. Build the conditional distribution by
   (hour_utc, day_of_week, volatility tercile from M5 ATR) → p25 / p50 / p90 / p99 per cell.
3. Assign spread to every M1/M5 bar: `measured` where ticks exist, `modeled` (from the
   matching cell) elsewhere; carry `spread_source`.
4. Three scenarios — optimistic p25, base p50, **pessimistic p90** (promotion gate).
5. Slippage (market: fixed + volatility-proportional; stops: always adverse, wider around
   rollover/news), commission per lot, swap from the frozen symbol spec
   (`swap_long`, `swap_short`, `swap_rollover3days`).
6. Validate: compare modeled spread with measured on held-out tick days; report error.
7. Persist to `storage/derived/.../costs/` + `ci.cost_models`; add tests.
8. Web: a "Costs" panel or page (spread heatmap by hour × weekday).

Then Phase 3 (feature store with `available_at` + leakage suite as a hard gate), Phase 4
(candle click → feature details in the viewer), Phase 5 (swings, S/R, trendlines).

## 7. Start-of-session checklist

```powershell
docker compose up -d                          # Postgres
.venv\Scripts\ci-ingest status                # MT5 connected? safety warnings?
.venv\Scripts\python -m pytest                # must be green before new work
.venv\Scripts\ci-api                          # then: npm --prefix apps/web run dev
```
