# Requirement — CEO Work Lab: five AI agents that research on the owner's behalf (2026-09-21, night)

## Owner's words (summary, Hinglish)

> Existing ko disturb kiye bina ek "CEO WORK LAB" page banana hai. Multiple AI agents banne hain jo
> mere behalf pe kaam kar sakein … Option A — Claude Code + localhost dashboard, alag Anthropic API
> billing nahi.
>
> (next message) Haan doc mein save kar do … abhi ka UI/UX bahut complicated lag raha hai … Phase 1
> se 4 is session mein karo, baaki new session mein.

The owner's full "GOLD INTELLIGENCE AI — MULTI-AGENT RESEARCH SYSTEM" master prompt is the source
of the goals below (CEO → Research Director → four specialists → Director → CEO; reproducible
numbers only; research-only, no live trading).

## Decisions recorded

| Topic | Decision |
|---|---|
| Where | One new page **CEO Work Lab** (`/ceo-lab`) + one nav item. Every existing page, API route, table and MCP tool stays as it is. |
| Simplicity | The owner finds the current UI complicated. The CEO page is the **simple front door**: one command box, plain-Hinglish status per agent, one report per mission. The existing pages stay as the "deep-dive" rooms and are linked from results; the CEO never has to open them. |
| How agents run (Option A) | **Claude Code on the owner's own login** (Pro). The dashboard *records* a mission; the owner opens Claude Code in this folder and runs `/ceo-run`. The Research Director (main session) delegates to four subagents in `.claude/agents/`; all of them act only through MCP tools; progress is written back to the ledger and shows live on the page. No separate API billing. |
| Not done | No subscription-token extraction, no unofficial automation. A dashboard button that starts Claude Code itself (headless `claude -p`) is **Phase 7, optional**, and only after checking Claude Code's terms and the Pro usage limits. |
| Numbers | Every number an agent reports must carry the `run_id` / `job_id` that produced it (read-only statistics that make no run: `dataset_id` + the exact tool call); the mission store rejects metric claims without one, and checks that cited runs / jobs / specs exist in the ledger. Tier C stays sealed (only the owner unseals). |
| Permissions | Agents get **no Bash, no file writes, no MT5**. Each agent's `tools:` list names only the MCP tools of its role (table below). Destructive actions, unsealing, approving searches and anything live stay with the owner. |
| Store | New tables `ceo_missions`, `ceo_tasks`, `ceo_events` in the same ledger database (created alongside the existing tables; nothing existing is altered). `infra/postgres/init/002_ceo.sql` documents them. |
| Limits | Per mission: `max_tasks` (default 12), `max_attempts` per task (default 2), `max_revisions` (default 2), deadline (default 6 h, counted from when work starts — a draft never expires). A task whose heartbeat is older than 30 min is marked failed ("stale") so a restart never leaves a mission stuck. Pro usage windows are the real limit — keep missions small. |
| Existing assistant | The AI Assistant page (AgentRouter API mode) is untouched and not needed by the CEO Work Lab. |

## The five agents

| Agent | Role | Tools (MCP) | Not allowed |
|---|---|---|---|
| Research Director | Plans, delegates, reviews, writes the report | ceo: all mission tools · research: `research_status`, `list_candidates`, `get_result`, `job_status` · `Agent` (to call the four) | backtests, spec edits, Bash, files |
| Data Scientist | Data health, sessions, volatility, regimes | ceo: task tools, `data_health`, `feature_distribution` · research: `research_status`, `feature_catalogue` | strategy tools |
| Pattern Analyst | Measurable patterns → events → statistics | ceo: task tools, `pattern_catalogue`, `run_pattern_study`, `wait_job` · research: `behaviour_library`, `run_event_study`, `feature_catalogue`, `job_status`, `get_result` | `run_backtest`, `propose_strategy` |
| Strategy Architect | Hypothesis → exact rules → `strategy-spec/1` | ceo: task tools · research: `feature_catalogue`, `propose_strategy`, `propose_search` (owner approves) | `run_backtest`, validation results |
| Validation & Risk Analyst | Independent backtests and robustness | ceo: task tools, `run_validation`, `wait_job` · research: `run_backtest`, `job_status`, `get_result`, `list_candidates` | `propose_strategy` |

Task states: `pending → queued → running → completed | failed | cancelled`, plus `waiting_deps`
(automatic, from `depends_on`) and `waiting_ceo` (owner must approve). Mission states:
`draft → (awaiting_approval, if the CEO asked to see plans) → running ⇄ paused → completed | failed | cancelled`.

## Phases

| # | Phase | Session |
|---|---|---|
| 1 | Mission store (tables, state machine, limits, stale recovery, audit events) + `/api/ceo/*` + tests | **done** |
| 2 | `candle-intelligence-ceo` MCP server + five agent definitions + `/ceo-run` command + tests | **done** |
| 3 | CEO Work Lab page (command box, workforce cards, mission monitor, report), nav item | **done** |
| 4 | `patterns/` module: previous-day high/low sweep detector with explicit rules, tests, and a pattern study job | **done** |
| 5 | First end-to-end mission (PDH/PDL sweep, London + NY, M5) with real run ids and an honest report | **done** |
| 6 | Director Room chat + plan editor (approve / modify) + strategy version compare | **done** |
| 7 | Optional headless bridge (`claude -p`) after a terms/limits check | **done** (needs the CLI) |
| 8 | Hardening: SSE live stream, usage accounting, docs, regression pass | **done** |

## Honest limits

- Option A needs the owner to type `/ceo-run` in Claude Code; the page cannot start agents by itself.
- One research job runs at a time (existing `JobRunner`); "parallel" agents queue their heavy work.
- A mission uses many tokens; Pro's usage windows can run out mid-mission. The mission store keeps
  state, so `/ceo-run` resumes where it stopped.
- Previous-day high/low features are not in the feature store yet; Phase 4 adds them as a separate
  pattern module (no feature-set rebuild). Making them strategy conditions needs a feature-set
  rebuild — owner decision in Phase 5.

## Status after this session (2026-09-21)

Phases 1–4 built and verified; 177 tests green (151 existing + 26 new), ruff and
TypeScript/ESLint clean. The page was checked in the browser against a scratch ledger: create
mission → plan → task claim/log/hand-in → CEO task approval → report, desktop and phone width.
A hand-in claiming "profit factor 2.5" without a source was rejected (HTTP 422). Not committed.

What was built (all additive):

| Piece | Where |
|---|---|
| Mission store + rules | `src/candle_intel/ceo/store.py` (tables `ceo_missions`, `ceo_tasks`, `ceo_events`; `infra/postgres/init/002_ceo.sql`) |
| API | `services/api/ci_api/ceo.py` (`/api/ceo/*`), `services/api/ci_api/patterns.py` (`/api/patterns/catalogue`, `/api/jobs/pattern-study`) |
| Agent tools (MCP) | `services/api/ci_api/ceo_mcp.py` → server `candle-intelligence-ceo` in `.mcp.json` |
| Agents | `.claude/agents/{data-scientist,pattern-analyst,strategy-architect,validation-analyst}.md`; the Research Director is `.claude/commands/ceo-run.md` (it runs in the main Claude Code session because only the main session can call other agents) |
| Pattern detector | `src/candle_intel/patterns/prev_day.py` (PDH/PDL sweeps, rule v1) + `patterns/__init__.py` (study runner) |
| Page | `apps/web/src/app/ceo-lab/page.tsx`, `apps/web/src/components/ceo/*`, `apps/web/src/lib/ceo.ts`; nav item "CEO Work Lab" (first in the sidebar) |
| Existing code touched | `main.py` (2 routers included), `app-shell.tsx` (1 nav item), `.mcp.json` (1 server), `research/events.py` (study summary split into `summarise_signals`, behaviour unchanged) |

## How the owner uses it

1. Restart the app once so the API loads the new routes: `Stop_Candle_Intelligence.bat`, then
   `Start_Candle_Intelligence.bat`.
2. Open **CEO Work Lab** → write the mission → *Mission do*.
3. Open Claude Code in `C:\Gold_Intelligence_AI` (approve the new `candle-intelligence-ceo`
   MCP server the first time) → type `/ceo-run`.
4. Watch the page; approve plans / tasks if asked; read the report.

## Phases 5–8 (2026-09-21, same night)

Owner: "ab Phase 5 se phase 8 complete karo phir commit and push karna".

### Phase 5 — first real mission, and PDH/PDL sweeps in the feature store

Owner decision taken as part of "complete Phase 5": the sweeps became strategy conditions.
Feature set **features/3** (`exness-mt5trial7_f20260921T161851Z`) adds eight `daily` features —
`pdh_sweep`, `pdl_sweep`, `*_sweep_depth_atr`, `*_sweeps_today`, `*_accepted_before` — built from
the same previous-trading-day levels as `dist_prev_high_atr`; the build's leakage self-check
passed and `tests/unit/test_patterns.py` checks that the columns select exactly the detector's
events. The older feature sets are untouched; old runs keep their lineage.

Mission `m_20260921T161937_583681` (the master prompt's §8 objective) ran on the real ledger:
this session played the Director and the four agents **through the same MCP tool functions and
contracts** (the new `candle-intelligence-ceo` server was not yet loaded in this session). Every
number below is from a stored run:

| Step | Result | Run |
|---|---|---|
| Data Scientist | 369,659 M5 bars, quality passed; PDH/PDL sweeps on ~1–2 % of London / overlap / NY bars | dataset + `feature_distribution` queries |
| Pattern Analyst | PDH first sweep, 1:3 barriers, tier A: 70 events, −0.32 R net (pessimistic); PDL: 77 events, +0.11 R gross, −0.12 R net | `st_20260921T162015_4dedcfb2_A_e87f`, `st_20260921T162018_20ed6d6f_A_67f1` (+2 all-sweep variants) |
| Strategy Architect | `8ba6e655c0e2b2e8` PDL first-sweep long, `273de18a9bf36227` PDH first-sweep short (family `pd-sweep`) | specs |
| Validation Analyst | PDL long: 59 trades, +0.025 R, PF 1.03, max DD 12 R (bootstrap CI spans 0); PDH short: 57 trades, −0.33 R, PF 0.61. Tier B not run (< 100 trades) | `ba_20260921T162141_8ba6e655_A_696d`, `ba_20260921T162144_273de18a_A_f28f` |
| Director report | verdict **inconclusive** — no proven edge; PDL long worth re-testing on 20 years of data | mission report |

### Phase 6 — Director Room, plan editor, version compare
Director Room = an asynchronous thread (`ceo_events` kind `message`): the CEO writes on the
page, the Director reads it with `read_messages` and answers with `post_message` each time
`/ceo-run` plans or finishes a round. The CEO can edit or remove a task that has not started,
and send a plan back with feedback (open tasks cancelled, mission back to `draft`, cancelled
tasks do not use up the task limit). "Strategies compare" shows every version of the mission's
strategy families side by side: rules, sessions, exits, trials and the latest tier A / B / A∪B
backtest headline.

### Phase 7 — optional headless bridge
`Start_CEO_Bridge.bat` (or `python -m ci_api.ceo_bridge`) runs a small local process: it posts
a heartbeat, and when the CEO presses **Agents ko abhi chalao** it starts Claude Code's official
headless mode (`claude -p --output-format json --mcp-config .mcp.json --strict-mcp-config
--allowedTools <the Director's + agents' MCP tools>`) with the Director's instructions on stdin.
It stops the run when the mission is paused / cancelled or after 3 h, and stores the turns,
tokens and notional cost Claude Code reports (`ceo_runs`). Nothing starts it automatically; no
credentials pass through the app. **Not verified end to end with the real CLI:** the Claude Code
CLI is not installed on this PC (`npm install -g @anthropic-ai/claude-code`, then `claude` once
to sign in). The bridge was tested with a fake CLI (tests/unit/test_ceo_bridge.py) and a live
heartbeat against the API. Runs use the owner's Pro usage limits.

### Phase 8 — hardening
Server-Sent Events (`GET /api/ceo/missions/{id}/stream`, works through the Next.js proxy): the
page refetches only when the mission's fingerprint changes and falls back to polling when the
stream drops. Usage per mission: tasks, attempts, engine runs / jobs cited, strategies, minutes,
and for bridge runs the reported tokens and cost ("measure nahi" for manual `/ceo-run`, which
reports nothing to the app). 185 tests green, ruff / TypeScript / ESLint clean.

New tables since Phase 1: `ceo_runs`, `ceo_bridge` (created on API start; `002_ceo.sql` updated).

## Indicators (2026-09-21, late) — features/4

Owner: "BB features jod do aur kuch indicator ema and volume ya jo bhi famous hai wo add kar do"
(for the mission "indicator bhi use karna hai bollinger band 50 deviation 2.1"). New group
`indicators` (27 features), all from the bar's own close and earlier bars, prices as ATR
distances: Bollinger **50 / 2.1** (%B, width, mid distance, close / touch outside), EMA
9/21/50/200 distances, EMA 50/200 slopes, EMA 9×21 cross, EMA stack, RSI 14 (Wilder), MACD
12/26/9 (+ signal, histogram, cross), Stochastic 14/3, ADX 14 with ±DI, daily VWAP distance
(typical price × tick volume, resets at 17:00 NY), OBV flow over 20 bars (tick volume — spot
gold has no exchange volume). Feature set `exness-mt5trial7_f20260921T170249Z`, leakage
self-check passed; `tests/unit/test_indicators.py` checks them against step-by-step formulas.
Warm-up: EMA 200 / BB 50 are empty for the first bars of the history (before tier A).


- Paper trading (roadmap Phase 11) and 20 years of data (Phase 12) — the demo's PDL-long idea
  needs the longer history before tier B.
- Install the Claude Code CLI if the one-button start is wanted; first real bridge run should be
  a small mission to see its usage.
