# Session Handoff — read this first

Last updated: 2026-09-21 · End of Phase 2 · Owner communicates in Hinglish.

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

## 4. What exists (Phases 0–2 complete)

| Component | Path | Command |
|---|---|---|
| MT5 gateway | `src/candle_intel/ingest/mt5_session.py` | — |
| Ingestion CLI | `src/candle_intel/ingest/cli.py`, `bulk.py` | `ci-ingest status \| probe \| snapshot \| raw --ticks --tick-days 260` |
| Data engine | `src/candle_intel/data/{clock,quality,aggregate,build}.py` | `ci-data build \| list` |
| Cost model | `src/candle_intel/costs/{ticks,volatility,spread,execution,validate,build}.py` | `ci-costs build \| list` |
| Metadata DB | `src/candle_intel/db.py`, `infra/postgres/init/001_schema.sql` | `docker compose up -d` |
| Research API | `services/api/ci_api/main.py` | `ci-api` → :8000 |
| MCP server | `services/mt5_mcp/ci_mt5_mcp/server.py`, `.mcp.json` | stdio |
| Web app | `apps/web` (Next.js 16, shadcn base-nova, Lightweight Charts 5): `/` Chart Viewer, `/costs` Costs | `npm --prefix apps/web run dev` → :3000 |
| Tests | `tests/{unit,leakage,integration}` | `pytest` (50 pass + 2 with `-m mt5`) |

Data on disk (git-ignored, in `storage/`):
- Raw `xauusd_exness-mt5trial7_20260921T071357Z`: M1 2021-07-01 → 2026-09-21 (1.84 M bars),
  broker M5/M15/H1 reference, **223 days of ticks (70.8 M, ~500 MB)** in `ticks/YYYY-MM-DD.parquet`.
- Derived `xauusd_exness-mt5trial7_d20260921T071531Z`: `M1/M5/M15/H1.parquet` with `ts_utc`
  and `ts_server`, `quality.json`, `clock_weekly.parquet`, `manifest.json`.
  Research window 2021-07-05 → present (5.2 y). M5/M15/H1 match broker bars 100 %.
- Cost model `exness-mt5trial7_c20260921T074047Z` in `<derived>/costs/`: `M1_costs` / `M5_costs`
  (per bar: `spread_level`, `spread_obs`, `spread_p25..p99`, `spread_current_p90`,
  `spread_source`, `spread_optimistic/base/pessimistic`, `atr_points`, `vol_bucket`,
  `in_rollover_window`, `abnormal_spread`, `level_imputed`), `spread_cells`,
  `measured_minutes`, `level_daily`, `validation.json`, `cost_model.json`; row in `ci.cost_models`.
  Built from a dirty tree — rebuild after the Phase 2 commit so `code_version` is clean.

## 5. Known data facts to carry forward

- Prices are **bid**. Ask = bid + scenario spread × point (cost tables, Phase 2).
- Per-bar `spread_points` = the **minimum** spread quoted in that minute (100 % match with
  ticks). ~6,000 M1 bars report ≤ 0 → imputed (`level_imputed`). It is the spread *level*
  for pre-tick history, not the spread paid — use the cost tables.
- **Spread moves in broker-set tiers** (monthly median bar level): ~112 pts (Jul–Aug 2021),
  ~62 (Sep 2021 – Jun 2024), ~50 (Jul–Aug 2024), ~37 (Sep 2024 – Jan 2026), 77–124
  (Feb–May 2026), 80–90 (Jun–Sep 2026). Time-of-day shape is flat except the rollover
  (≈ 16:45–18:30 NY). Pessimistic spread is floored at the last-60-day tier, so 2024–25
  results will look much worse under pessimistic than base — that is intended.
- Swap (frozen spec, points mode): long −549.3 pts/night = **$54.93 per lot per night**,
  short 0; triple on Wednesday. Commission unknown (A4): pessimistic charges $7/lot RT.
- 500 price-spike bars flagged (not removed); 96 holiday/long closures.
- Daily break: 16:58 New York, ~63 min. Gaps are classified in `quality.json`.
- MT5 quirks handled in the gateway: naive datetimes are read as machine-local time
  (bounds are encoded explicitly); over-limit ranges fail with "Invalid params" (chunked);
  the forming bar is returned (marked/excluded); empty windows can return one stale bar.
- Clock inference wraps offsets to ±12 h so "New York + 7" brokers (break at 00:00 server
  time, next calendar day) work; covered by a synthetic UTC+2/+3 DST test.

## 6. Phase 2 — Cost Model (done 2026-09-21) and what comes next

Design and numbers: blueprint §6 "Implementation note — 2026-09-21". In short:
modeled spread = bar level × time-weighted ratio quantile per (hour_utc, weekday, M5
vol tercile); measured bars use the tick time-weighted mean; scenarios per bar are
optimistic ≤ base ≤ pessimistic, pessimistic floored at the last-60-day cell p90.
Validation (last 20 % of tick days, unseen): bias +2.6 %, MAE 3.4 pts → **passed**.
Execution costs live in `costs/execution.py` (scalar functions the backtester will call):
`slippage_points(order, atr_points, scenario, in_window)`, `Commission.usd`,
`swap_usd(side, lots, entry_utc, exit_utc, spec)` (17:00 NY rollovers, triple Wednesday).

Open items: A4 commission, A5 news calendar, A6 slippage refit (blueprint Appendix A).

**Next: Phase 3 — Feature Store (blueprint §7, hard gate).** Candle/sequence/context
features in `src/candle_intel/features/`, every row carrying `available_at`; leakage suite
in `tests/leakage/` must pass before any behaviour research. Useful inputs already in the
cost tables: `atr_points` / `vol_ratio` (known at bar open), `abnormal_spread`,
`in_rollover_window` (§5.3 hygiene exclusions). Then Phase 4 (candle click → feature
details in the viewer), Phase 5 (swings, S/R, trendlines).

## 7. Start-of-session checklist

```powershell
docker compose up -d                          # Postgres
.venv\Scripts\ci-ingest status                # MT5 connected? safety warnings?
.venv\Scripts\python -m pytest                # must be green before new work
.venv\Scripts\ci-api                          # then: npm --prefix apps/web run dev
```
