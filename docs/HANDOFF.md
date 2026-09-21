# Session Handoff — read this first

Last updated: 2026-09-21 · End of Phase 3 + new UI shell · Owner communicates in Hinglish.

> **Goal, target dashboard and the revised roadmap live in [MASTER_PROMPT.md](MASTER_PROMPT.md)**
> (owner decisions of 2026-09-21: strategy research workbench + AI Research Engine, 5 years
> of data now / 20 later, live trading on an Exness Raw Spread account). Its roadmap order
> replaces the "Next" list below.

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

## 4. What exists (Phases 0–3 complete)

| Component | Path | Command |
|---|---|---|
| MT5 gateway | `src/candle_intel/ingest/mt5_session.py` | — |
| Ingestion CLI | `src/candle_intel/ingest/cli.py`, `bulk.py` | `ci-ingest status \| probe \| snapshot \| raw --ticks --tick-days 260` |
| Data engine | `src/candle_intel/data/{clock,quality,aggregate,build}.py` | `ci-data build \| list` |
| Cost model | `src/candle_intel/costs/{ticks,volatility,spread,execution,validate,build}.py` | `ci-costs build \| list` |
| Feature store | `src/candle_intel/features/{registry,compute,leakage,store,build}.py` | `ci-features build \| list \| show --time <UTC>` |
| Metadata DB | `src/candle_intel/db.py`, `infra/postgres/init/001_schema.sql` | `docker compose up -d` |
| Research API | `services/api/ci_api/main.py` | `ci-api` → :8000 |
| MCP server | `services/mt5_mcp/ci_mt5_mcp/server.py`, `.mcp.json` | stdio |
| Web app | `apps/web` (Next.js 16, shadcn base-nova, Lightweight Charts 5): `/` Chart Viewer (click a candle → features panel), `/costs` Costs | `npm --prefix apps/web run dev` → :3000 |
| Tests | `tests/{unit,leakage,integration}`, shared synthetic gold-calendar history in `tests/conftest.py` | `pytest` (80 pass + 2 with `-m mt5`) |

Data on disk (git-ignored, in `storage/`):
- Raw `xauusd_exness-mt5trial7_20260921T071357Z`: M1 2021-07-01 → 2026-09-21 (1.84 M bars),
  broker M5/M15/H1 reference, **223 days of ticks (70.8 M, ~500 MB)** in `ticks/YYYY-MM-DD.parquet`.
- Derived `xauusd_exness-mt5trial7_d20260921T071531Z`: `M1/M5/M15/H1.parquet` with `ts_utc`
  and `ts_server`, `quality.json`, `clock_weekly.parquet`, `manifest.json`.
  Research window 2021-07-05 → present (5.2 y). M5/M15/H1 match broker bars 100 %.
- Cost model `exness-mt5trial7_c20260921T080957Z` (built from commit 53e442a, clean) in `<derived>/costs/`: `M1_costs` / `M5_costs`
  (per bar: `spread_level`, `spread_obs`, `spread_p25..p99`, `spread_current_p90`,
  `spread_source`, `spread_optimistic/base/pessimistic`, `atr_points`, `vol_bucket`,
  `in_rollover_window`, `abnormal_spread`, `level_imputed`), `spread_cells`,
  `measured_minutes`, `level_daily`, `validation.json`, `cost_model.json`; row in `ci.cost_models`.
  (An earlier dirty-tree build `..._c20260921T074047Z` also exists; the API serves the newest.)
- Feature set `exness-mt5trial7_f20260921T091144Z` in `<derived>/features/`: `features_M5.parquet`
  (369,659 rows × 97 columns: 7 meta + 90 features) + `feature_set.json` (schema, config hash
  `c0caee76c8d123b8`, leakage self-check **passed** at 5 cut points, summary, SHA-256
  `ee4c8554…`). Built from a dirty tree before the Phase-3 commit; rebuild after committing
  if a clean `code_version` is wanted (same inputs gave the same file hash).

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

## 6. Phase 2 — Cost Model (done 2026-09-21)

Design and numbers: blueprint §6 "Implementation note — 2026-09-21". In short:
modeled spread = bar level × time-weighted ratio quantile per (hour_utc, weekday, M5
vol tercile); measured bars use the tick time-weighted mean; scenarios per bar are
optimistic ≤ base ≤ pessimistic, pessimistic floored at the last-60-day cell p90.
Validation (last 20 % of tick days, unseen): bias +2.6 %, MAE 3.4 pts → **passed**.
Execution costs live in `costs/execution.py` (scalar functions the backtester will call):
`slippage_points(order, atr_points, scenario, in_window)`, `Commission.usd`,
`swap_usd(side, lots, entry_utc, exit_utc, spec)` (17:00 NY rollovers, triple Wednesday).

Open items: A4 Raw-account commission, A5 news calendar, A6 slippage refit, A7 Raw Spread
demo account for a Raw cost profile (blueprint Appendix A).

## 6b. Phase 3 — Feature Store (done 2026-09-21) and what comes next

Design: blueprint §7 "Implementation note — 2026-09-21 (Phase 3)" and §5.3 "As built".
In short: one row per M5 bar, `event_time` = open, `available_at` = close; 90 features
(anatomy, sequence, volatility, DST-aware sessions, NY-17:00 trading day, M15/H1 from the
last *closed* bar, spread, §5.3 hygiene incl. `hyg_no_entry`). Nothing is fitted on the
whole history: volatility regime and abnormal spread are recomputed causally (the cost
table's versions use the full history and are **not** features). Research code must read
features through `FeatureStore` (`as_of(T)` / `bar(t, decision_time)` → `LookAheadError`).

Leakage gate: `tests/leakage/test_feature_leakage.py` (recomputation on truncated history,
future perturbation, availability audit, 5 planted leaks caught by name, access wrapper);
`ci-features build` repeats recomputation + perturbation on the real history and writes
nothing on any mismatch. API: `GET /api/features/{dataset}` (schema, self-check, summary),
`GET /api/features/{dataset}/bar?time=<epoch>&tf=<M1|M5|M15|H1>` (M1 → containing M5 bar;
M15/H1 → the M5 bar that closes with it; includes the bar's cost-model spreads, labelled
"not a feature"). UI verified desktop + 375 px phone, no console errors.

Real-data facts: 4,416 M5 bars abnormal-spread (1.2 %), 11,771 in the rollover window,
15,957 `hyg_no_entry` (4.3 %); sessions: asian 32 %, london 22 %, new_york 21 %,
overlap 18 %, off 7 %. Holiday early closes are not flagged by `hyg_week_last3` (A8).

**Next: Phase 4 — Strategy spec + Backtester** ([MASTER_PROMPT.md](MASTER_PROMPT.md) §8):
Pydantic spec in `src/candle_intel/strategy/` (entry conditions over these feature names,
filters incl. `hyg_no_entry`, exits, sizing, meta), event-driven engine in
`src/candle_intel/backtest/` (decide on M5 close via `FeatureStore`, fill at next M5 open,
resolve on M1, three cost scenarios from `M5_costs` + `costs/execution.py`, ambiguity rate),
chronological A/B/C split + trial counting in PostgreSQL, the shifted-target canary.

## 6c. New UI direction + app shell (2026-09-21 night)

Owner supplied `new_reference_image.png` (dark + gold, sidebar, chart-first) and four must-have
workspaces (Behaviour Explorer, Research Pipeline, Visual Pattern Intelligence, Validation Lab).
Recorded in `requirements/2026-09-21_ui-redesign-research-workspace.md`; page ↔ phase map in
MASTER_PROMPT §6. Built: gold theme tokens (`globals.css` `.dark`), `components/app-shell.tsx`
(sidebar with every future page disabled + its phase, phone drawer, real dataset range and
engine status), Overview = old Chart page + Strategy Lab entry cards (no invented numbers),
Costs page renamed "Data Center · Costs" (`app-nav.tsx` removed). No backend change.
**Rule for every new page: show engine-produced numbers or an honest empty state — never
illustrative metrics.** Open owner question Q-UI1 (in-page AI chat with or without API key).

## 7. Start-of-session checklist

```powershell
docker compose up -d                          # Postgres
.venv\Scripts\ci-ingest status                # MT5 connected? safety warnings?
.venv\Scripts\python -m pytest                # must be green before new work
.venv\Scripts\ci-api                          # then: npm --prefix apps/web run dev
```
