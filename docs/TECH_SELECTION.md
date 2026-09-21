# Technology Selection Report
**Candle Intelligence AI · XAUUSD-only** · 2026-09-21 · Companion to [ARCHITECTURE_v1.2.md](ARCHITECTURE_v1.2.md)

Scope: every library named in the 2026-09-21 requirement
([requirements/2026-09-21_tech-stack-and-mt5-mcp.md](requirements/2026-09-21_tech-stack-and-mt5-mcp.md)),
evaluated for fit, license, maintenance and Python 3.12 / Windows compatibility.
Versions, licenses and dates below were read from PyPI, npm and GitHub on 2026-09-21,
not recalled.

---

## 1. Verdict summary

| Library | Version checked | License | Decision | Role |
|---|---|---|---|---|
| **MetaTrader5** (Python) | 5.0.6180 (2026-09-05) | MIT (PyPI metadata) | **Use** | Bulk ingestion + backing for our MCP server. Windows-only |
| **Polars** | 1.44.2 | MIT | **Use — core** | All dataframe work |
| **NumPy** | 2.5.3 | BSD-3 | **Use — core** | Numerical kernels, geometry |
| **SciPy** | 1.18.1 | BSD-3 | **Use — core** | `find_peaks`, stats, FDR, KDE, optimisation |
| **DuckDB** | 1.5.5 | MIT | **Use — core** | SQL over Parquet |
| **Apache Parquet** (via pyarrow 25.0.1) | — | Apache-2.0 | **Use — core** | Raw / derived / feature storage, zstd |
| **PostgreSQL** | 17 (Docker) | PostgreSQL | **Use — core** | Metadata, lineage, experiments, registry |
| **FastAPI** | 0.141.1 | MIT | **Use** | Research API (Phase 4+) |
| **Plotly** | 7.1.0 | MIT | **Use** | Phase-4 research viewer (static HTML, no server) |
| **scikit-learn** | 1.9.1 | BSD-3 | **Use** | RANSAC trendlines, DBSCAN level clusters, baselines |
| **OpenCV** (headless) | 5.0.0.93 | Apache-2.0 | **Use — narrow** | Vision track only; headless build, no GUI deps |
| **scikit-image** | 0.26.0 | BSD-3 | **Use — narrow** | Vision track: Hough, morphology, image metrics |
| **LightGBM** | 4.7.0 | MIT | **Use — Phase 8** | Gradient boosting after baselines |
| **Optuna** | 5.0.0 | MIT | **Use — Phase 8, guarded** | Hyper-parameter search; every trial counted (§5) |
| **MLflow** | 3.16.1 | Apache-2.0 | **Use — Phase 8, optional** | Experiment tracking UI; PostgreSQL stays source of truth |
| **VectorBT** | 1.1.0 | **Apache-2.0 + Commons Clause** | **Optional, screening only** | Tier-A fast screening. Never the truth engine |
| **Backtrader** | 1.9.78.123 (**2023-04-19**) | **GPL-3.0** | **Reject** | Unmaintained; copyleft; bar-level fills |
| **Next.js** | 16.3.5 | MIT | **Use — Phase 11** | Full research web app |
| **TradingView Lightweight Charts** | 5.2.1 | Apache-2.0 (attribution required) | **Use — Phase 11** | Candlestick rendering + overlays |
| **shadcn/ui** | CLI 4.21.0 | MIT | **Use — Phase 11** | UI components (copied into repo, not a runtime dep) |
| **Recharts** | 3.10.1 | MIT | **Use — Phase 11** | Equity, drawdown, distribution charts |

Added (not in the requirement, each justified by a concrete gap):

| Library | License | Why it is needed |
|---|---|---|
| `mcp` 2.2 (official MCP SDK) | MIT | Build our own read-only MCP server (§4). Official SDK, not third-party |
| `tzdata` | Apache-2.0 | Windows Python has no IANA tz database; DST-aware sessions (§5.4) are impossible without it |
| `pydantic-settings` | MIT | Typed config; gold-only symbol validation; `SecretStr` keeps credentials out of logs |
| `arch` 8.0 | NCSA (permissive) | Hansen **SPA**, StepM and stationary bootstrap (§9.3) — maintained reference implementations; writing our own would be riskier |
| `SQLAlchemy` 2.0 + `psycopg` 3 | MIT / LGPL-3.0 | PostgreSQL access. psycopg is LGPL, used unmodified as a library — compatible |
| `pytest`, `ruff` (dev) | MIT | Tests (incl. the blocking leakage suite) and lint |
| `uv` (tool) | MIT/Apache-2.0 | Lockfile (`uv.lock`) → byte-reproducible environments |

Deliberately **not** added: pandas (Polars covers it; MT5 returns NumPy arrays directly),
TA-Lib / `ta` (indicators are a few lines of Polars and must carry `available_at`),
`statsmodels` (SciPy ≥ 1.11 has `false_discovery_control`), Numba (only if a profiled
kernel needs it), `kaleido` (vision track renders with OpenCV, see §3).

---

## 2. Backtesting architecture decision

The blueprint's non-negotiables (§6, §7.3) are: M1 path resolution for M5 signals,
bid/ask reconstruction from a conditional spread model, three cost scenarios, an
ambiguity-rate metric, deterministic order priority, and per-trade audit rows tied to
a trial counter. Evaluated against those:

| Requirement | VectorBT 1.1 | Backtrader | Custom engine |
|---|---|---|---|
| M5 signal, **M1 intrabar path** resolution | No — stops are evaluated on the same series' bar OHLC, not a finer path | Partial via data replay; awkward | **Yes** |
| Same-bar SL/TP **ambiguity policy + rate** | Resolved by an internal rule; no ambiguity metric exposed | No | **Yes** |
| Time/volatility-**conditional spread**, stress scenarios | Scalar or array fees only | Commission schemes, no conditional spread | **Yes** |
| Deterministic, auditable per-trade reason codes | Partial | Yes | **Yes** |
| Trial accounting / holdout gate integration | No | No | **Yes** |
| Speed for large parameter sweeps | **Excellent** (vectorised, Numba) | Slow | Adequate (NumPy, event loop) |
| License | Apache-2.0 **+ Commons Clause** — cannot sell a product deriving from it | **GPL-3.0** | Ours |
| Maintenance | Active (pushed 2026-09-17) | **No release since 2023-04** | Ours |

**Decision.**

1. **Custom event-driven engine is the execution truth** (`candle_intel.backtest`). It is
   the only option that satisfies §7.3, and its core is small: an event loop over M5
   signals, an M1 walker for open positions, a cost model lookup, and an audit writer.
2. **VectorBT is optional, Tier-A screening only**, installed via the `screening` extra.
   Use: prune thousands of rule variants cheaply before the real engine sees them.
   Constraints: its results never appear in promotion decisions, and every VectorBT run
   still increments the trial counter — a screen is a test.
3. **Backtrader is rejected** — unmaintained, GPL-3.0, and no advantage the custom engine
   lacks.
4. Also reviewed: `backtesting.py` (AGPL-3.0 — incompatible with a possible future
   closed product) and NautilusTrader (LGPL-3.0, excellent, but a full trading platform
   with order-book/live-execution scope far beyond a research backtester). Neither adopted.

---

## 3. Visual Intelligence Engine — hybrid design and library roles

Numerical truth first, vision second (blueprint §13). Concretely:

| Stage | Numerical (primary) | Vision (secondary) |
|---|---|---|
| Swing points | SciPy `find_peaks` with prominence, **wrapped** so each pivot's `available_at = t(i + k)` — raw `find_peaks` looks both ways and would leak | — |
| Support / resistance | scikit-learn DBSCAN / SciPy KDE over swing prices, ATR-scaled bandwidth | — |
| Trendlines | scikit-learn `RANSACRegressor` over compatible swing sets; touch/break counting in NumPy | OpenCV `HoughLinesP` / scikit-image `probabilistic_hough_line` on a rendered chart as an **independent cross-check** |
| Channels, ranges, formations | Geometry over swing sequences (NumPy) | Vision LLM on rendered crops, only for ambiguous cases |
| Similarity search | Normalised numerical shape vectors (NumPy/DuckDB) | scikit-image SSIM on rendered crops as a secondary signal |

**Rendering for vision is done with OpenCV, not Plotly.** We draw candles ourselves onto
a pixel canvas with a known affine transform, so every pixel coordinate a vision
detector returns maps back to an exact `(timestamp, price)`. Screenshot-based charts
lose that mapping. Plotly remains the *human* research viewer.

Every vision output is re-verified against OHLC before it is stored. A vision detection
with no numerical confirmation is logged as a disagreement, not as a pattern.

---

## 4. MT5 MCP integration decision

Full evidence: [reviews/mt5-mcp-security-review.md](reviews/mt5-mcp-security-review.md).

| Repository | Verdict | Blocking reasons |
|---|---|---|
| amirkhonov/metatrader5-mcp | **Reject** | Exposes `mt5_order_send`, `mt5_order_check`, positions, orders, deal history, account info. No symbol restriction |
| Cloudmeru/MetaTrader-5-MCP-Server | **Reject as-is** | `mt5_execute` runs LLM-supplied Python via `exec()` behind a substring blocklist; full `__builtins__` and full `pandas`/`numpy` modules in scope → arbitrary code execution and a reachable `order_send`. Exposes `account_info`, `positions_get`. No symbol restriction |

**Built instead:** `services/mt5_mcp` — ~200 lines on the official `mcp` SDK and the
official `MetaTrader5` package. Six fixed, typed, read-only tools; none accepts a symbol;
no code execution; outputs capped; no account identifiers. Both reviewed repos were
used as references for MT5 edge cases, not copied.

**Split of responsibilities (per requirement):**

- **Bulk historical ingestion → direct MT5 Python API** (`candle_intel.ingest`) → Parquet.
- **AI assistant access → MCP** (read-only, capped, for inspection and questions).
- Research code reaches neither; it reads Parquet only (enforced by tests).

---

## 5. Guard rails on the libraries themselves

- **Optuna** makes over-fitting cheap. Every Optuna trial is a trial in `trial_counts`;
  studies run on Tier A/B only; Deflated Sharpe uses the true count.
- **MLflow** is a viewer, not a source of truth. Lineage lives in PostgreSQL; MLflow
  is optional and can be dropped without losing anything.
- **SciPy `find_peaks`** and any centred rolling window look into the future. They are
  only used through wrappers that set `available_at`; the leakage suite's recomputation
  test catches violations.
- **Lightweight Charts** requires TradingView attribution (Apache-2.0 NOTICE); keep the
  default attribution link enabled in Phase 11.
- **MetaTrader5** is Windows-only. Only `candle_intel.ingest` and the MCP server depend
  on it; everything else runs on any OS from Parquet.

---

## 6. What requires custom development

| Component | Why no library fits |
|---|---|
| MT5 read-only gateway + MCP server | Reviewed MCP servers fail the read-only / XAUUSD-only requirement |
| Chunked, resumable MT5 ingestion + forming-bar exclusion | MT5 fails over-limit ranges; returns a forming bar; needs lineage |
| Broker-clock → UTC conversion | Broker DST rules are broker-specific; must be inferred from data (weekly-open anchoring) |
| Data-quality gate + empirical rollover detection | Gold/broker-specific rules (§5) |
| Conditional spread / slippage / swap cost model | No library models time-and-volatility-conditional CFD spreads |
| `available_at` feature store + leakage suite | Core research integrity; no library enforces it |
| Leakage-safe swing/level/trendline wrappers | Library primitives are look-ahead by default |
| Triple-barrier labelling with M1 resolution | Must share the backtester's intrabar logic |
| Event-driven backtester | §2 above |
| Trials accounting, sealed holdout, DSR | Process controls specific to this protocol (SPA/bootstrap come from `arch`) |
| Chart renderer with exact pixel↔price mapping | Required to verify vision output against OHLC |

---

## 7. Environment

- Python **3.12** (NumPy 2.5 / SciPy 1.18 require ≥ 3.12; MetaTrader5 ships cp312 wheels).
- `uv` with committed `uv.lock`. Core install is lean; heavy stacks are extras:
  `research`, `vision`, `ml`, `screening`.
- PostgreSQL 17 in Docker on `127.0.0.1:5434`.
- Node 24 for Phase 11.
