# Candle Intelligence AI

XAUUSD-only quantitative research platform: decode gold price behaviour from candles,
market structure and chart geometry, and test — honestly — whether any of it carries a
tradeable edge after realistic costs. Research and paper trading only; no real-money
execution. Independent of Shiibaa.

| Document | What it is |
|---|---|
| [docs/MASTER_PROMPT.md](docs/MASTER_PROMPT.md) | **Session entry point** — goal, target dashboard, revised roadmap, working rules |
| [docs/HANDOFF.md](docs/HANDOFF.md) | **Start here** — current state, rules, next phase |
| [docs/ARCHITECTURE_v1.2.md](docs/ARCHITECTURE_v1.2.md) | Current blueprint (supersedes v1.1, v1.0 .docx) |
| [docs/TECH_SELECTION.md](docs/TECH_SELECTION.md) | Library choices, backtesting decision, custom components |
| [docs/reviews/mt5-mcp-security-review.md](docs/reviews/mt5-mcp-security-review.md) | Why external MT5 MCP servers were rejected |
| [docs/requirements/](docs/requirements/) | Owner requirements, verbatim and dated |

## Status

**Phases 1–10 (data engine, cost model + account profiles, feature store + market structure, strategy spec + backtester, Strategy Lab / Backtest / Optimize / Validate, Behaviour Explorer, research engine, ML Lab, AI Assistant) — built and running on Exness-MT5Trial7 (demo).**

| Piece | State |
|---|---|
| Raw ingestion (`ci-ingest raw`) | M1 2021-07 → now (1.84 M bars), broker M5/M15/H1 reference, 223 days of ticks (70.8 M) |
| Data build (`ci-data build`) | Clock inferred (UTC+0), quality gate passed, M5/M15/H1 match broker bars 100 % |
| Cost model (`ci-costs build`) | Spread per M1/M5 bar (measured / modeled), 3 scenarios, slippage, commission, swap; validated out-of-sample |
| Feature store (`ci-features build`) | features/3: M5 features per bar incl. market structure and previous-day sweeps (anatomy, sequence, volatility, DST-aware sessions, daily, M15/H1 context, spread, §5.3 hygiene), each row with `available_at`; build blocked unless the leakage self-check passes |
| Research API (`ci-api`) | Candles with scroll-back paging, dataset summary, cost model / heatmap / spread levels, feature set + one bar's features |
| Backtester | Strategy spec (`strategy-spec/1`), event-driven engine (M5 decisions, M1 fills, 3 cost scenarios), frozen A/B/C split with a sealed holdout, trial counting per family, Deflated Sharpe, bootstrap, Monte Carlo, cost stress, walk-forward, §15 checklist |
| Web app (`apps/web`) | Dark-gold research workspace: Overview (chart + features panel), Data Center (costs), Strategy Lab (visual builder), Backtest, Optimize, Validate, My Strategies, job tray |

**CEO Work Lab** (`/ceo-lab`, [docs/requirements/2026-09-21_ceo-work-lab.md](docs/requirements/2026-09-21_ceo-work-lab.md)):
the owner writes a research mission; a Research Director and four specialist agents
(Claude Code subagents, `.claude/agents/`) plan, study, write strategies and validate them
through the engine; the report, with every number linked to its run, lands on the page.
Run it with `/ceo-run` in Claude Code, or `Start_CEO_Bridge.bat` + the page's button.

Next: Phase 11 — paper trading (see [docs/MASTER_PROMPT.md](docs/MASTER_PROMPT.md) §8, §11). Owner items: Raw Spread demo ticks (A7), AgentRouter budget (A9).

## Setup (Windows)

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), MetaTrader 5 terminal,
Docker Desktop.

```powershell
python -m uv sync                      # core + dev tools
python -m uv sync --extra research     # + scikit-learn, arch, plotly   (Phase 4+)
python -m uv sync --extra research --extra ml --extra assistant   # + LightGBM (ML Lab), anthropic (AI Assistant API mode)
copy .env.example .env                 # then edit; never commit .env
docker compose up -d                   # PostgreSQL 17 on 127.0.0.1:5434
```

### MT5 terminal — once, before any session

1. Log in to a **demo** account, preferably with its **investor (read-only) password**.
2. Switch **Algo Trading off** (toolbar).
3. Tools → Options → Charts → **Max bars in chart = Unlimited**, then restart MT5.
   (At 100,000 the terminal, not the broker, caps M1/M5/M15 history.)

`ci-ingest status` reports all three as `safety_warnings` until they are done.

## Everyday commands

```powershell
.venv\Scripts\ci-ingest status                     # connection, safety posture, symbol spec
.venv\Scripts\ci-ingest raw --ticks --tick-days 260 # new raw dataset: all M1 + reference TFs + ticks
.venv\Scripts\ci-data build                        # newest raw -> validated UTC dataset (M1/M5/M15/H1)
.venv\Scripts\ci-data list
.venv\Scripts\ci-costs build                       # newest dataset -> validated cost model (~2.5 min)
.venv\Scripts\ci-costs list
.venv\Scripts\ci-features build                   # newest dataset -> leakage-checked M5 features (~20 s)
.venv\Scripts\ci-features list
.venv\Scripts\ci-features show --time 2026-09-18T14:05   # one bar's features (bar open, UTC)
.venv\Scripts\ci-api                               # research API on http://127.0.0.1:8000
npm --prefix apps/web run dev                       # web app on http://localhost:3000 (/ and /costs)
.venv\Scripts\python -m pytest                     # unit + leakage (no MT5 needed)
.venv\Scripts\python -m pytest -m mt5              # live MT5 integration
```

## AI assistant access (MCP)

`.mcp.json` registers `candle-intelligence-mt5`, a read-only, XAUUSD-only MCP server
(stdio). Claude Code asks for approval the first time the project is opened. Tools:

| Tool | Returns |
|---|---|
| `xauusd_status` | Connected?, demo/real, trading permitted?, Algo Trading on?, server offset & time |
| `xauusd_symbol_info` | Contract spec: digits, tick size/value, contract size, swaps, spread |
| `xauusd_latest_price` | Bid, ask, spread |
| `xauusd_rates` | M1/M5/M15/H1 candles (capped at 5,000; forming bar flagged) |
| `xauusd_ticks` | Bid/ask ticks, ≤ 6-hour windows |
| `xauusd_spread_stats` | Spread p25/p50/p90/p99/max over the last N minutes |

No tool accepts a symbol, executes code, trades, or returns account identifiers.

Two more servers drive research: `candle-intelligence-research` (propose / backtest / study,
tier C withheld) and `candle-intelligence-ceo` (CEO Work Lab missions: plans, task hand-ins,
reports, Director Room). Both are thin clients of `ci-api`; their tool lists are pinned by
tests.
All times are on the **broker server clock**.

## Ground rules

- `MetaTrader5` is imported only by `src/candle_intel/ingest/mt5_session.py`.
- Research code reads Parquet snapshots only — never MT5, never the MCP.
- Raw data is read-only after write. Credentials live only in `.env`.
- The leakage suite (`tests/leakage/`) must pass before any research result counts.
