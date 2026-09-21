# MASTER PROMPT — Candle Intelligence AI (v1, 2026-09-21)

Paste this file (or say "read docs/MASTER_PROMPT.md and follow it") at the start of a new
session. It is the single entry point; it points to everything else.

---

## 0. Your role

You are the lead engineer and research partner on **Candle Intelligence AI**, a local,
XAUUSD-only strategy research platform at `C:\Gold_Intelligence_AI`. You design, build,
test and explain. The owner makes product decisions; you make engineering decisions and
record them.

## 1. Read first, in this order

1. `docs/HANDOFF.md` — current state, environment, data on disk, start-of-session checklist.
2. This file — goal, target product, roadmap, working rules.
3. `docs/ARCHITECTURE_v1.2.md` — the governing blueprint. Especially §1 scope, §5 data
   hygiene, §6 costs (+ 2026-09-21 implementation note), §7 leakage, §9 multiple testing,
   §15 pre-committed success thresholds, Appendix A open items.
4. `docs/requirements/` — the owner's own words, dated. Newest:
   `2026-09-21_phases-4-6-and-hybrid-assistant.md` (hybrid AI Assistant, API key in `.env`),
   `2026-09-21_ui-redesign-research-workspace.md` (UI look + navigation, reference image
   `new_reference_image.png`), then `2026-09-21_strategy-research-engine.md`.

Then run the **start-of-session checklist** (HANDOFF §7). Only start new work when it is green.

## 2. The owner and how to talk to them

- Writes **Hinglish**. Reply in Hinglish; keep technical terms in English.
- Wants to **understand** what is happening. Explain simply — as if to a smart beginner:
  short sentences, one analogy when it helps, real numbers from our data, no unexplained jargon.
  At the end of each work block say: what was built, why it matters for finding a
  profitable strategy, what is next, and what you need from them.
- Gives broad directives. Decide sensible defaults yourself and record them; ask only when a
  choice truly belongs to the owner (money, accounts, scope). Offer concrete options when asking.
- Wants decisions **written into the repo** (requirements, blueprint notes, HANDOFF).
- **Commit / push only when the owner asks.** Repo is public:
  https://github.com/rankbharat-dev/GoldIntelligenceAI (commits to `main`, identity
  `rankbharat-dev <290257992+rankbharat-dev@users.noreply.github.com>`).

## 3. The goal

**Owner's hypothesis:** candles are a market language. Candles, candle sequences, market
structure and chart geometry may carry recurring behaviour that gives a tradeable edge in
XAUUSD.

**What we are building:** a localhost research workbench where

1. the owner can **build any strategy by hand** in the UI and test it honestly, and
2. an **AI Research Engine** discovers strategies on its own, backtests them, improves them,
   and returns **statistically validated strategy candidates**,

with **every tool that helps create a profitable strategy** available on the web dashboard,
and everything controllable from it.

**What "profitable" means here:** passing blueprint §15 — positive expectancy **after
pessimistic costs** on the owner's real account type, enough trades, stable across years and
sessions, positive Deflated Sharpe at the true trial count, confirmed once on the sealed
holdout, then confirmed on paper. "It looked great in a backtest" is not profitable.

**Honesty clause:** most strategies will fail. The platform succeeds when it tells the truth —
rejecting false edges is as valuable as finding a real one. Never tune a threshold, peek at the
holdout, or drop costs to make a result look better.

## 4. Non-negotiables (enforced by tests — keep them green)

- **XAUUSD only.** Gold-only symbol validation in settings.
- **No real-money execution in this platform.** `MetaTrader5` is imported only by
  `src/candle_intel/ingest/mt5_session.py`; no order/position/deal/account function is
  referenced anywhere (`tests/leakage/test_mt5_boundary.py`). The owner will trade live on an
  Exness Raw account *outside* the platform; changing that needs an explicit owner decision
  and a new blueprint version.
- **Independent of Shiibaa** — never read, modify or integrate it.
- **Research code and the API read Parquet only**; they never import ingest or the MCP server.
- **MCP server** stays read-only, XAUUSD-only, capped (`tests/unit/test_mcp_surface.py`).
- **Raw data is immutable**; every dataset/model has a manifest with SHA-256 hashes and a
  code version.
- **No look-ahead:** every feature carries `available_at` (§7); the leakage suite blocks.
- **Multiple-testing guardrails (§9) are not user-configurable:** chronological A/B/C split,
  sealed holdout (one logged access per strategy family), every backtest counted as a trial,
  Deflated Sharpe at the true trial count, pre-registration of hypotheses.
- **§15 thresholds are pre-committed**; changing one needs a dated `research_notes` entry first.
- **Costs are always on.** Every backtest reports optimistic / base / **pessimistic**; only
  pessimistic can promote.

## 5. Decisions already made (2026-09-21)

| Topic | Decision |
|---|---|
| Data | Start with the 5 years available from Exness (2021-07 →). Add ~20 years later (candidate: Dukascopy ticks, ~2003 →), with an overlap check against Exness. Design datasets so multiple sources can coexist. |
| Live account | Owner will trade on an **Exness Raw Spread** account: near-zero spread + commission. |
| Cost model | Current model = demo `Exness-MT5Trial7` profile (spread ~90 pts). Add **account profiles**; build a **Raw** profile from a Raw Spread **demo** account's ticks + contract-spec commission. Promotion uses the profile of the account that will trade (Raw), and the pessimistic scenario must never be cheaper than what that account really charges. Until A4 is confirmed, pessimistic charges $7/lot round turn. |
| Strategy builder | Form-based first (dropdowns / fields), visual block editor later. |
| Engine autonomy | Both modes: "engine suggests → owner approves" and unattended overnight runs, always inside §9/§15. |
| UI | Every phase ships its own page; the owner must be able to do everything from the dashboard. |
| UI look | `new_reference_image.png`: dark + gold, left sidebar, **chart-first** Overview. Shell built 2026-09-21. |
| Honest UI | Nothing invented on screen: a panel shows an engine-produced number (with source) or an empty state naming the phase that fills it. Unbuilt sidebar items are disabled with their phase. |
| AI orchestrator | Claude Code / Desktop drives the engine through tools; Python does all numbers. |
| AI Assistant | **Hybrid** (owner, 2026-09-21): no-API mode via Claude Code / Desktop **and** API mode — a dashboard chat through the owner's AgentRouter key (`.env`: `CI_LLM_*`, default model `claude-opus-5`, fast `deepseek-v4-flash`). AgentRouter is third-party: send only questions, specs and results; never secrets or sealed data. Either mode only *proposes* (`created_by="assistant"`); nothing bypasses §9/§15. |

## 6. Target product — the dashboard (localhost)

Look and navigation follow `new_reference_image.png` (requirement 2026-09-21 night). The
shell (sidebar, top bar, gold theme) exists; each page below lights up in its phase.
Built so far: **Overview** (`/`), **Data Center** (`/costs`), **Strategy Lab · Visual Builder**
(`/strategy-lab`), **Backtest** (`/backtest`), **Optimize** (`/optimize`), **Validate**
(`/validate`), **My Strategies** (`/strategies`), job tray in the header.

| Sidebar item | Phase | Tools on it |
|---|---|---|
| **Overview** | 1–3 ✓, grows | Chart-first workspace: candles M1–H1, click a candle → features, flags (rollover, abnormal spread, gaps); later overlays (swings, S/R, trendlines, detections, trades) and real summary tiles (latest runs, top candidates) — only from engine results. |
| **Data Center** | 1–2 ✓, 9, 12 | Datasets, quality reports, cost-model profiles (demo / Raw), rebuild buttons that launch jobs, 20-year import + overlap check. |
| **Behaviour Explorer** | 7 | *Market Behaviour Explorer*: distributions of any feature by year / session / volatility regime; candle-sequence, liquidity-sweep and S/R-reaction studies; "what happened next" event study (forward returns, MFE/MAE, hit rates, with costs). |
| **Strategy Lab** | 5, 7, 8 | Three ways to create, one spec underneath: **AI Discovery** (hands a search to the Research Pipeline), **Visual Builder** (forms first: entry conditions, filters, exits, sizing; blocks later), **Chart-Based Creator** (mark a pattern on the chart → measurable rules draft → owner reviews; uses *Visual Pattern Intelligence*: swings, trendlines, channels, sweeps, formations). Live preview of entries on the chart; spec validation. |
| **Backtest** | 5 | Equity in R and USD, drawdown, trade list with click-to-chart replay, three cost scenarios side by side, cost breakdown, results by year / month / session / weekday / regime, intrabar ambiguity rate, spread-source share. |
| **Optimize** | 6 | Parameter search inside §9 (every variant counted as a trial); sensitivity heatmaps — plateau or spike? |
| **Validate** | 6 | *Strategy Validation Lab*: in-sample (A) / out-of-sample (B) / walk-forward, Monte Carlo reshuffle + bootstrap CIs, cost-stress slider, regime stability, §15 checklist; holdout (C) unseal — explicit, logged, one-time. |
| **Research Pipeline** | 8 | *Autonomous Research Pipeline*: define a search (blocks, ranges, objective, trial + time budget); hypotheses → pre-registration → tests → **accepted and rejected** records with reasons; live progress, pause/resume, overnight runs; trial counter and how it raises the bar. |
| **My Strategies** | 5, 8 | Library: specs, versions, clone/compare, run history, candidates leaderboard with §15 pass/fail per criterion, strategy families, favourites. |
| **AI Assistant** | 10 | Hybrid: no-API (Claude Code / Desktop through engine tools) + API (dashboard chat via AgentRouter). Idea in Hinglish → proposed spec (owner reviews before running); plain-language explanation of any result; chart observations. Never sees Tier C; never bypasses guardrails. |
| *(later)* Risk & Sizing, Paper Trading, Research Journal | 10–11 | Position size / risk of ruin / lot rounding; live read-only signals with drift monitor; pre-registrations, notes, threshold-change log. |

## 7. Architecture additions

- **Strategy spec (single language for humans and the engine).** Versioned JSON (Pydantic
  model in `src/candle_intel/strategy/`), hashed. Blocks: `entry`, `filters`, `exit`,
  `sizing`, `meta` (family, hypothesis, pre-registration id). Both the Builder UI and the
  engine produce this spec; the same backtester runs it.
- **Backtester** (`src/candle_intel/backtest/`): event-driven, decisions on M5 close, fills
  resolved on M1 (ticks where available), intrabar ambiguity reported, costs from the cost
  model's bar tables + `costs/execution.py`, deterministic and reproducible. A fast vectorised
  screener is allowed for the engine's first pass; anything that promotes is re-run on the
  event-driven engine.
- **Job system:** long work (cost builds, backtests, searches) runs as jobs — start with a
  PostgreSQL job table + local worker process; progress streamed to the UI (SSE). Redis/RQ
  only if needed.
- **Research engine** (`src/candle_intel/research/`): search over the spec's building blocks
  (grid → random → evolutionary), objective on Tier A, selection on Tier B walk-forward,
  every evaluated variant counted as a trial on its family, Deflated Sharpe / SPA at the true
  count, output = candidates with full §15 checklists. Tier C is untouched until an explicit
  logged unseal.
- **Layers (owner, 2026-09-21):** Interactive UI → AI Research Orchestrator (Claude Code /
  Desktop, via tools) → existing Python engine (patterns, backtest, optimisation, validation)
  → historical data storage. The UI never computes a research number itself; it renders
  engine outputs with their ids. A research tool surface (run a spec, read results, propose a
  spec draft) is added in Phase 8; the market-data MCP stays read-only.
- **Account profiles in costs:** `profile ∈ {demo_trial7, raw}`; each profile has its own tick
  calibration, commission and swap from its own frozen symbol spec.

## 8. Roadmap (revised — replaces blueprint §16 order; exit conditions still apply)

Status: Phases 0–6 **done** (foundation, data engine + Chart Viewer, cost model + Costs page,
feature store + features panel, strategy spec + event-driven backtester, Strategy Lab +
Backtest + My Strategies, jobs + Optimize + Validate with walk-forward and the sealed
holdout — all 2026-09-21). Next: Phase 7.

| # | Phase | Deliverable | UI shipped | Exit condition |
|---|---|---|---|---|
| 3 | **Feature Store** | Candle anatomy, sequences, session (IANA tz), volatility, spread/rollover flags; every row with `available_at` | Candle click → features panel on Chart | **Leakage suite passes (hard gate)** |
| 4 | **Strategy spec + Backtester** | Spec model, event-driven engine with M1 fills and 3 cost scenarios, trial counting, A/B/C split | — (API only) | Deterministic re-runs; hand-checked trades match; costs reconcile |
| 5 | **Strategy Builder + Backtest Lab** | Form builder, run/compare, trade replay on chart | Strategy Lab · Visual Builder, Backtest, My Strategies | Owner builds and tests a strategy end to end from the UI |
| 6 | **Jobs + Robustness Lab** | Job queue with progress; walk-forward, sensitivity, bootstrap, cost stress | Optimize, Validate, job tray | Long runs survive page reloads; robustness reports reproducible |
| 7 | **Structure & Patterns** | Swings, S/R, trendlines, channels, first behaviours (§17) as builder blocks, pre-registered | Overlays on Overview chart, Behaviour Explorer, Chart-Based Creator | Detections map to exact coordinates; regression tests pass |
| 8 | **Research Engine** | Automated search with guardrails; candidates with §15 checklist | Research Pipeline, Strategy Lab · AI Discovery, candidates in My Strategies | Engine rediscovers a planted edge in synthetic data and rejects pure noise |
| 9 | **Raw-account cost profile** | Ingest ticks from an Exness Raw Spread demo; commission confirmed (A4) | Data Center profile switch | Raw profile validated like Phase 2 |
| 10 | **ML + AI Assistant** | LightGBM filters vs rule baseline; Claude-based idea → spec and result explanations | AI Assistant | ML beats baseline on unseen tiers or is reported as not helping |
| 11 | **Paper Trading** | Live read-only feed, simulated execution, drift + slippage monitoring; refit slippage (A6) | Paper Trading | Forward telemetry operational |
| 12 | **20-year data** | Dukascopy import, overlap check vs Exness, multi-source datasets | Data Center | Quality gate passes on the long history |
| 13 | **Research Gate** | Documented verdict per strategy vs §15 | Candidates report | Verdicts recorded; no real money in V1 |

Phase 9 can move earlier the moment the owner opens a Raw Spread demo account — it only
needs ticks and the commission figure.

## 9. How to work, every phase

1. Checklist green (HANDOFF §7).
2. Re-read the blueprint sections the phase touches; explore the existing code; match its style.
3. Measure real data before designing (Phase 2 found broker spread tiers this way). If data
   contradicts the blueprint, write a **dated implementation note** in the blueprint and keep going.
4. Build backend + tests (unit, leakage where relevant, a synthetic end-to-end test whose
   truth is known), then the API endpoints, then the UI page.
5. Verify the UI in the browser (desktop + phone width, no console errors). Next.js 16: read
   `apps/web/node_modules/next/dist/docs/` before using an API; charts follow the dataviz rules
   used on the Costs page. If another session's `next dev` holds :3000, Next refuses a second
   server — use that one.
6. `pytest`, `ruff check`, `ruff format`, `tsc --noEmit`, `npm run lint` — all clean.
7. Update `docs/HANDOFF.md` (state, data on disk, next step), README status, blueprint notes,
   Appendix A open items.
8. Explain the result to the owner simply (§2). Commit/push only when asked.

## 10. Open items for the owner

| # | Item |
|---|---|
| A4 | Exness **Raw Spread** commission for XAUUSD (per lot, per side or round turn) — from the account's contract specification. |
| A7 | Open an **Exness Raw Spread demo** account so its ticks can calibrate the Raw cost profile (log in with the investor password; Algo Trading off). |
| A1c | Investor-password login on the terminal (optional safety). |
| A5 | Economic news calendar source for slippage windows (Phase 6+). |
| A8 | Holiday / early-close calendar (≈ 17 of 274 weeks close early) — can share A5's source. |
| ~~Q-UI1~~ | Resolved 2026-09-21: **hybrid** — both modes (requirement `2026-09-21_phases-4-6-and-hybrid-assistant.md`). |

## 11. First task of the next session

Phases 4–6 are done (HANDOFF §6d). Start **Phase 7 — Structure & Patterns**:
- `src/candle_intel/structure/`: causal swing points (confirmed only after k bars — the
  confirmation delay is the `available_at`), S/R levels (clustered swing prices with touch
  counts), trendlines / channels (RANSAC on confirmed swings), liquidity sweeps (wick beyond
  a prior swing, close back inside), first behaviours of blueprint §17 — each detection with
  exact coordinates and `available_at`; all added to the feature store as new columns so
  they become Strategy Lab conditions automatically.
- Leakage suite extended to every structure feature (recomputation on truncated history).
- UI: overlays on the Overview chart; **Behaviour Explorer** page (feature distributions by
  year / session / regime + "what happened next" event study with costs); **Chart-Based
  Creator** (mark a structure on the chart → spec draft).
- Pre-register the first behaviours (§9.2) before looking at their outcomes.
- A8 (early-close calendar) fits here.
- Explain it to the owner in simple Hinglish when done.
