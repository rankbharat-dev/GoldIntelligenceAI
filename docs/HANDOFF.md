# Session Handoff — read this first

Last updated: 2026-09-21 (late) · End of Phase 10 · Owner communicates in Hinglish.

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
| PostgreSQL | Docker container `candle-intelligence-postgres` on **127.0.0.1:5434** (5433 belongs to another project, `staff-manager-pg`). Use `127.0.0.1`, not `localhost`: on this machine `localhost` tries IPv6 first and psycopg hangs |
| LLM (AI Assistant API mode) | AgentRouter key in `.env` (`CI_LLM_*`), git-ignored. Used by `candle_intel/assistant/chat.py` (official `anthropic` SDK, `base_url` = router). On 2026-09-21 the router returned **402 budget exhausted** (open item A9) |
| GitHub | https://github.com/rankbharat-dev/GoldIntelligenceAI — **public**; commits use `290257992+rankbharat-dev@users.noreply.github.com` |
| Git policy | Commit / push only when the owner asks |

## 4. What exists (Phases 0–10 complete)

| Component | Path | Command |
|---|---|---|
| MT5 gateway | `src/candle_intel/ingest/mt5_session.py` | — |
| Ingestion CLI | `src/candle_intel/ingest/cli.py`, `bulk.py` | `ci-ingest status \| probe \| snapshot \| raw --ticks --tick-days 260` |
| Data engine | `src/candle_intel/data/{clock,quality,aggregate,build}.py` | `ci-data build \| list` |
| Cost model | `src/candle_intel/costs/{ticks,volatility,spread,execution,validate,build,profiles}.py` — account profiles `demo_trial7` / `raw` | `ci-costs build [--profile raw --raw-ticks <id>] \| provisional-raw \| list` |
| Feature store | `src/candle_intel/features/{registry,compute,leakage,store,build}.py` | `ci-features build \| list \| show --time <UTC>` |
| Structure (Phase 7) | `src/candle_intel/structure/geometry.py` — swings, S/R, trendlines, channels, breaks, retests, sweeps; 38 feature columns + chart detections | via `ci-features build` / `/api/structure` |
| Strategy spec | `src/candle_intel/strategy/{spec,signals,drafts}.py` (drafts = Chart-Based Creator) | — |
| Backtester | `src/candle_intel/backtest/{market,split,engine,metrics}.py` | via API jobs |
| Research layer | `src/candle_intel/research/{ledger,runs,optimize,validate,checklist,jobs}.py`, `statistics/robust.py` | via API jobs |
| Behaviours + studies (Phase 7) | `research/{behaviours,events,studies}.py` — 18 pre-registered V1 behaviours in `ci.pattern_definitions`, triple-barrier event studies, BH-FDR screen | Behaviour Explorer |
| Research engine (Phase 8) | `research/discovery.py` — searches + hypotheses in `ci.research_searches` / `ci.research_hypotheses` | Research Pipeline |
| ML filter (Phase 10) | `src/candle_intel/ml/filter.py` (LightGBM; models in `storage/research/models/`) | ML Lab |
| AI Assistant (Phase 10) | API mode `src/candle_intel/assistant/chat.py`; no-API mode MCP `services/api/ci_api/research_mcp.py` (in `.mcp.json` as `candle-intelligence-research`) | AI Assistant page / Claude Code |
| Metadata DB | `src/candle_intel/db.py`, `infra/postgres/init/001_schema.sql`; research ledger tables (`research_specs/trials/runs/jobs`, `holdout_access_log`) created by `research/ledger.py` | `docker compose up -d` |
| Research API | `services/api/ci_api/main.py` + `research.py` (specs, preview, runs, trades, jobs, holdout, cost jobs) + `explore.py` (structure, distributions, behaviours, studies, chart drafts) + `pipeline.py` (searches, candidates) + `assistant.py` (chat, ML jobs) | `ci-api` → :8000 (restart after backend changes — no auto-reload) |
| MCP server | `services/mt5_mcp/ci_mt5_mcp/server.py`, `.mcp.json` | stdio |
| Web app | `apps/web` (Next.js 16, shadcn base-nova, Lightweight Charts 5): `/` Overview (structure overlays), `/costs` Data Center (cost profiles), `/explorer` Behaviour Explorer, `/strategy-lab` (Visual Builder, AI Discovery, Chart-Based Creator), `/backtest`, `/optimize`, `/validate`, `/pipeline` Research Pipeline, `/strategies` (+ candidates leaderboard), `/ml` ML Lab, `/assistant` AI Assistant; job tray in the header | `npm --prefix apps/web run dev` → :3000 |
| Preview pair | `.claude/launch.json` `api-preview` (:8001) + `web-preview` (`CI_NEXT_DIST=.next-preview`), and `api-dev` (:8002) + `web-dev` (`.next-dev2`, :3200) — lets a session test next to the owner's own :3000/:8000 servers (the preview tool allows 5 servers per folder across all chats) | preview tools |
| Tests | `tests/{unit,leakage,integration}`, shared synthetic gold-calendar history in `tests/conftest.py` | `pytest` (151 pass + 2 with `-m mt5`) |
| Extra deps | `lightgbm`, `scikit-learn` (extras `ml`, `research`), `anthropic` (extra `assistant`) | `python -m uv sync --extra research --extra ml --extra assistant` |

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
  (An earlier dirty-tree build `..._c20260921T074047Z` also exists.) Profile `demo_trial7`, validated.
- Cost model `exness-mt5trial7_raw_c20260921T121723Z`: profile `raw`, status **provisional** — demo spread
  tables copied as an upper bound + USD 10 / lot round turn (owner). Active profile for new runs:
  `storage/research/cost_profile.json` (default `demo_trial7`; switch in Data Center).
- Feature set **`exness-mt5trial7_f20260921T114037Z`** (`features/2`, 135 columns = 7 meta + 128 features incl.
  38 structure columns; leakage self-check passed at 5 cut points; config hash `cce2f35d203d1f34`) — the
  one every run uses now. Older: feature set `exness-mt5trial7_f20260921T091144Z` in `<derived>/features/`: `features_M5.parquet`
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

*(Done — see §6d.)* The Phase 4 plan as it was written:
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

## 6d. Phases 4–6 — spec, backtester, Strategy Lab, Backtest, Optimize, Validate (done 2026-09-21)

Design: blueprint §9 "Implementation note — 2026-09-21 (Phases 4–6)". Owner decisions:
`requirements/2026-09-21_phases-4-6-and-hybrid-assistant.md`.

- **Spec** (`strategy-spec/1`): entry rules over the 89 conditionable features, filters, ATR
  exits (stop / target / time / trailing / flat before weekend), fixed-fractional sizing,
  family. `spec_hash` identifies the rules.
- **Engine**: decide at M5 close → fill at the next M1 open → stops/targets on the M1 path;
  3 cost scenarios per run; pessimistic intrabar policy; ~4 s for 5 years of tier A.
- **Split frozen** in `storage/research/split.json` (tracked in git): A 2021-07-05 → 2024-08-21,
  B → 2025-09-06, C from 2025-09-06, sealed. Unseal = `POST /api/holdout/unseal` (typed family
  name + reason; one per family, enforced by a unique index).
- **Ledger** in PostgreSQL `ci`: every distinct spec per family = one trial; runs indexed;
  jobs survive page reloads (not API restarts — interrupted jobs are marked failed at start).
  Run files: `storage/research/runs/<run_id>/run.json` (+ `trades.parquet`), git-ignored.
- **Pages**: Strategy Lab (Visual Builder with live validation, signal counts per tier,
  signals on the chart, templates; AI Discovery / Chart-Based Creator show their phase),
  Backtest (3 scenarios, equity, cost breakdown, bootstrap / Monte Carlo / cost stress,
  breakdowns, month strip, paginated trades with M1 replay), Optimize (≤ 3 params, ≤ 400
  variants, heatmap, plateau/spike, Deflated Sharpe of the winner), Validate (§15 checklist
  with reasons, tiers, walk-forward, ambiguity sensitivity, stability, holdout unseal),
  My Strategies (library, favourites, families with trial counts and holdout status).
- **First real results** (honest, not promising): the "three-candle reversal" example on
  tier A: −0.005 R before costs, **−0.288 R** after pessimistic costs over 23,132 trades;
  rejected on 7 criteria; 0 of 13 walk-forward windows positive. A 25-variant stop/target
  grid shows wider stops lose less (costs are a smaller share of 1 R) — no variant positive.
  Costs (spread + slippage + $7 unconfirmed commission ≈ 0.28 R/trade at 1-ATR stops)
  dominate short-horizon M5 ideas; this is the main lesson to carry into Phase 7–8.
- A research note (id 1) in `ci.research_notes` records the checklist readings (positive-
  bucket stability, literal DSR gate, A-and-B rule) before any promotion decision.

**The owner's :8000 API was started before Phases 4–6** — restart it (`ci-api`) so the new
pages work on :3000.

## 6e. Phases 7–10 (done 2026-09-21 late) — requirement `requirements/2026-09-21_phases-7-10.md`

Design notes: blueprint "Implementation note — 2026-09-21 (Phases 7–10)" (after §13).

- **Phase 7 — structure & patterns.** `structure/geometry.py` (swings K=5 confirmed 5 bars
  later, S/R clusters, trendlines/channels, breakout/retest/failed, sweeps, H1 swing state) →
  38 new conditionable features (`features/2`); overlays on the Overview chart (toggle Swings /
  S/R / Trendlines / Events); **Behaviour Explorer** `/explorer` (pre-registered library with
  tier A/B studies, BH-FDR screen, ad-hoc event study on tier A, feature distributions by
  year/session/regime/tier); **Chart-Based Creator** (Strategy Lab → mark a bar before tier C
  → tick measurable facts → Visual Builder). 18 V1 behaviours registered in
  `ci.pattern_definitions` (research note 2: 6 were looked at on tier A before registration).
  **Result:** tier-A screen — 0 of 18 behaviours survive FDR, before or after costs.
- **Phase 8 — research engine.** `research/discovery.py` + **Research Pipeline** `/pipeline`,
  Strategy Lab → AI Discovery, candidates leaderboard in My Strategies. Approve-first or
  unattended; pause/resume; trial counter and the SR0 "luck bar". Exit test passes (planted edge
  found, noise rejected). **Result:** first search, 120 hypotheses (16 behaviours × sessions ×
  H1 alignment × exits): all rejected at the tier-A screen; best +0.03 R with only 147 trades;
  SR0 at 120 trials = 0.117.
- **Phase 9 — Raw account costs.** Profiles in `costs/profiles.py`; Data Center card with the
  switch, "Rebuild provisional Raw" and "Calibrate Raw" (needs A7 ticks, ingested with
  `--account-label raw`). Calibration tested on synthetic Raw ticks (ratio to the demo level,
  zero spreads kept, validation passes). §15 checklist gained a "cost profile" item (research
  note 3): pending until the calibrated Raw profile is used, and the holdout cannot be unsealed
  before that.
- **Phase 10 — ML + AI Assistant.** ML Lab `/ml` (LightGBM filter trained on tier A, judged on
  tier B; exit test passes). **Result:** three-candle reversal + filter: +0.042 R on B
  (−0.197 → −0.155 R, AUC 0.52) — better, still losing. AI Assistant `/assistant`: API chat
  (router budget exhausted — A9) and no-API mode via the `candle-intelligence-research` MCP
  server (pinned tool list; cannot unseal, approve or see tier C).

**Restart the owner's API (`ci-api`, :8000)** — it predates Phases 7–10 (new routers, new
feature set, profiles). The web app on :3000 hot-reloads.

## 6f. Simple mode UI (done 2026-09-22) — requirement `requirements/2026-09-22_simple-mode-ui.md`

The owner found the 12-page research UI confusing. New **Simple mode** (default; sidebar
switch Simple / Expert, stored in the browser as `ci-mode`): Home `/` (3 goals + my strategies
+ glossary chips), **Idea test** `/idea` (5 plain questions → real spec → tier-A backtest),
**Result** `/result?run=` (answer first, 3 numbers with "?" help, before-costs − costs = left,
next steps incl. one-click 1:3 re-test, Expert details), **Market samjho** `/learn`
(behaviour screen in plain words), **Meri strategies** `/my` (journey Banaya → Pehla test →
Sudhaaro → Final check → Paper trade + one next step), AI Research = `/ceo-lab`. Expert mode
is unchanged; the chart Overview moved to `components/overview.tsx` and is shown at `/` in
Expert mode and at `/chart` always. Plain wording, verdict and wizard → spec mapping live in
`apps/web/src/lib/plain.ts`. Job polling now continues in background tabs.

Owner guides (Hinglish): `docs/guides/FEATURE_GUIDE_HINGLISH.md` + the 27-slide
`Candle_Intelligence_Feature_Guide.pptx` (explains the Expert pages; Simple mode is summarised
at the top of the guide).

Browser checks without touching the real ledger: launch.json `api-scratch` (:8003, throwaway sqlite
ledger `storage/scratch/ledger.db` via `CI_RESEARCH_DB_URL`, git-ignored) + `web-scratch` (:3300). Verified:
wizard → backtest → auto-open result (reversal: 13,102 trades, −0.19 R, "no edge"; London
momentum buy small: 699 trades, +0.06 R before costs → −0.17 R after, "costs ate it"; 1:3
re-test −0.12 R), Meri strategies journeys, Market samjho (18 behaviours, 0 pass after costs),
Expert switch, phone width.

## 7. Start-of-session checklist

```powershell
docker compose up -d                          # Postgres
.venv\Scripts\ci-ingest status                # MT5 connected? safety warnings?
.venv\Scripts\python -m pytest                # must be green before new work
.venv\Scripts\ci-api                          # then: npm --prefix apps/web run dev
# research ledger reachable? (creates its tables on first use)
.venv\Scripts\python -c "from candle_intel.research.ledger import default_ledger; print(default_ledger().families())"
```
