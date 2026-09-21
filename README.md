# Candle Intelligence AI

XAUUSD-only quantitative research platform: decode gold price behaviour from candles,
market structure and chart geometry, and test — honestly — whether any of it carries a
tradeable edge after realistic costs. Research and paper trading only; no real-money
execution. Independent of Shiibaa.

| Document | What it is |
|---|---|
| [docs/HANDOFF.md](docs/HANDOFF.md) | **Start here** — current state, rules, next phase |
| [docs/ARCHITECTURE_v1.2.md](docs/ARCHITECTURE_v1.2.md) | Current blueprint (supersedes v1.1, v1.0 .docx) |
| [docs/TECH_SELECTION.md](docs/TECH_SELECTION.md) | Library choices, backtesting decision, custom components |
| [docs/reviews/mt5-mcp-security-review.md](docs/reviews/mt5-mcp-security-review.md) | Why external MT5 MCP servers were rejected |
| [docs/requirements/](docs/requirements/) | Owner requirements, verbatim and dated |

## Status

**Phase 1 (data engine) — built and running on Exness-MT5Trial7 (demo).**

| Piece | State |
|---|---|
| Raw ingestion (`ci-ingest raw`) | M1 2021-07 → now (1.84 M bars), broker M5/M15/H1 reference, 223 days of ticks (70.8 M) |
| Data build (`ci-data build`) | Clock inferred (UTC+0), quality gate passed, M5/M15/H1 match broker bars 100 % |
| Research API (`ci-api`) | Candles with scroll-back paging, dataset summary |
| Web Chart Viewer (`apps/web`) | Candles, timeframe + time-zone switch, data-health panel |

Next: Phase 2 — spread / slippage / swap cost model from the tick archive.

## Setup (Windows)

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), MetaTrader 5 terminal,
Docker Desktop.

```powershell
python -m uv sync                      # core + dev tools
python -m uv sync --extra research     # + scikit-learn, arch, plotly   (Phase 4+)
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
.venv\Scripts\ci-api                               # research API on http://127.0.0.1:8000
npm --prefix apps/web run dev                       # Chart Viewer on http://localhost:3000
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
All times are on the **broker server clock**.

## Ground rules

- `MetaTrader5` is imported only by `src/candle_intel/ingest/mt5_session.py`.
- Research code reads Parquet snapshots only — never MT5, never the MCP.
- Raw data is read-only after write. Credentials live only in `.env`.
- The leakage suite (`tests/leakage/`) must pass before any research result counts.
