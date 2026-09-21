# CANDLE INTELLIGENCE AI
## XAUUSD-Only Research Platform — Architecture & Technical Blueprint
**Version 1.2** · Supersedes v1.1 · Data source locked: **MT5 broker history via the direct MT5 Python API**; AI assistant access via a read-only MCP server

---

## 0. What Changed

### v1.2 (2026-09-21) — MT5 integration verified against a live terminal

| Change | Reason | Section |
|---|---|---|
| Bulk ingestion uses the **direct MT5 Python API**; MCP is for the **AI assistant only** | Owner requirement 2026-09-21; MCP is a poor bulk transport | §3.1 |
| External MCP repos rejected; **purpose-built read-only XAUUSD-only MCP server** | Security review: one exposes `order_send`, the other runs LLM-supplied code | §3.1, reviews/ |
| MT5 range bounds are **broker-server wall times**, encoded explicitly | The MetaTrader5 package reads naive datetimes as machine-local time (5.5 h shift on IST) | §3.4 |
| **Forming bar** excluded from raw storage | MT5 returns the in-progress bar alongside closed ones | §3.4 |
| Requests **chunked below the terminal bar limit** | Over-limit ranges fail with "Invalid params" | §3.4 |
| Terminal **"Max bars in chart" is the binding history cap**, not the broker | Live probe: M1/M5/M15 capped at 99,999 bars, H1 reaches 2016 uncapped | §3.5 |
| Real bid/ask tick window measured at **~234 days** on the test server | Sizes the spread-calibration set (§6) | §3.5 |
| Broker identified from the **account** (Exness-MT5Trial7), not the terminal vendor | `terminal_info().company` is always "MetaQuotes Ltd." | §3.5 |
| Bulk M1 via **month-sized range requests** — full archive from 2021-07 | `from_pos` is capped by the chart-bar limit; ranges are not | §3.5 |
| Web UI **starts in Phase 1** as a Next.js Chart Viewer and grows one page per phase | Owner request 2026-09-21; replaces the Plotly-only viewer | §16 |

### v1.1

v1.0 established the right scope, stack and discipline. v1.1 closes nine gaps that were
either unspecified or left to convention, and absorbs the consequences of locking the data
source to an MT5 broker export accessed through an MT5 MCP server.

| # | Gap in v1.0 | v1.1 resolution | Section |
|---|---|---|---|
| 1 | Data source vague ("MT5 / verified source") | MT5 via MCP locked; broker-conditional research declared; 20-year target withdrawn | §3, §4 |
| 2 | Spread "separately modeled" — no method | Three-layer spread model: measured → modeled → stressed. p90 survival required | §6 |
| 3 | Intrabar ambiguity flagged, unsolved | M5 = signal layer, **M1 = execution truth layer**; ambiguity rate is a reported metric | §7 |
| 4 | Multiple-testing listed as a metric, no protocol | Three-tier sealed split + hypothesis pre-registration + trials counter + Deflated Sharpe / SPA | §9 |
| 5 | Fixed-horizon and R-based labels both mandated | **Triple-barrier is primary**; fixed-horizon demoted to diagnostic | §8 |
| 6 | Stationarity ignored across the history window | Mandatory per-year / per-session / per-regime breakdown + stability score | §10 |
| 7 | Rollover and weekend gaps unaddressed | Rollover detected empirically; hygiene exclusion rules; DST-aware sessions | §5 |
| 8 | "Sufficient sample size" undefined | Minimum Detectable Effect fixed up front → **N ≥ 1000 dev / 250 val** | §11 |
| 9 | No-look-ahead left to convention | `available_at` column enforced in the feature store + leakage test suite | §7 |
| — | Next.js UI required at Phase 2 | Full web UI deferred; thin research viewer first | §14, §16 |
| — | Success thresholds "to be defined" | Thresholds defined **now**, pre-committed, in this document | §15 |

Everything in v1.0 not listed above still stands.

---

## 1. Project Scope Lock (unchanged)

XAUUSD (Gold Spot / USD) only. No forex pairs, crypto, indices, equities, or multi-asset
abstraction in V1. Research mode only — historical research plus paper trading. No
real-money automated execution in V1. The project remains fully independent of Shiibaa;
no existing Shiibaa code is read, modified, or integrated.

| Area | V1 decision |
|---|---|
| Instrument | XAUUSD only |
| Signal timeframe | M5 |
| Execution resolution timeframe | **M1 (new in v1.1)** |
| Context timeframes | M15, H1 |
| Data source | **MT5 broker history via direct MT5 Python API (locked)**; read-only MCP for the AI assistant |
| Frontend | Deferred — thin research viewer first, Next.js later |
| Core backend | Python + FastAPI |
| Analytics | Polars / NumPy / SciPy / DuckDB |
| ML | scikit-learn + LightGBM; deeper models only if justified |
| Storage | Parquet (market/features) + PostgreSQL (metadata/results) |

---

## 2. Research Hypothesis (unchanged)

Recurring combinations of candle anatomy, candle sequences, market structure,
support/resistance, trendlines, channels, volatility, session context and visual
formations may contain measurable information about future XAUUSD price behaviour.
The platform exists to test that hypothesis scientifically, and is designed to be
capable of concluding that no exploitable edge exists.

---

## 3. Data Source: MT5 Terminal

### 3.1 Two paths, one gateway

```
                         ┌──────────────────────────────────────────┐
MT5 terminal ──────────▶ │ candle_intel.ingest.mt5_session (gateway) │  only module importing MetaTrader5
                         └──────────────┬──────────────────┬────────┘
                                        │                  │
                     bulk, chunked      │                  │  capped, typed, read-only
                                        ▼                  ▼
                          ci-ingest → immutable      services/mt5_mcp → AI assistant
                          Parquet snapshots          (inspection & questions only)
                                        │
                                        ▼
                               ALL research code  ── never imports the gateway or the MCP
```

- **Bulk historical ingestion uses the direct MT5 Python API** through the gateway. It is
  the only path that feeds research.
- **The MCP server gives the AI research assistant read-only XAUUSD access** — status,
  symbol spec, latest price, capped candles and ticks, spread statistics. It is for
  looking, not for building datasets.
- **Research code reads Parquet only.** It cannot import the gateway or the MCP server
  (AST-enforced in `tests/leakage/test_mt5_boundary.py`). Reasons: reproducibility (a
  live call returns whatever the broker serves today), leakage (live access can reach
  beyond the simulated decision time) and determinism.

The gateway exposes an **allowlist proxy** of market-data functions only. Trading,
order, position, deal-history and account functions are unreachable through it, and
tests fail if any source file references them. `account_info` is read inside the gateway
solely to report account *mode* (demo/real) and whether the session *permits trading*.

The MCP server is purpose-built; the two external servers reviewed failed the read-only
requirement (`docs/reviews/mt5-mcp-security-review.md`).

### 3.2 What MT5 provides

| Source | Fields | Practical limit |
|---|---|---|
| Rates | `time, open, high, low, close, tick_volume, spread, real_volume` | Terminal "Max bars in chart" per request, then broker depth (§3.5) |
| Ticks | `time_msc, bid, ask, last, volume, flags` | Broker tick archive (§3.5) |
| Symbol info | Contract and cost specification | Current values only — snapshot and freeze |

Three consequences that shape the whole platform:

1. **Bars are bid prices.** The ask side is reconstructed as `ask = bid + spread`. The
   per-bar `spread` field is a point-value snapshot, not a bar average — a weak proxy,
   treated as such (§6).
2. **History is shorter than the original brief assumed.** The 20-year ambition is
   **withdrawn**. At roughly 276 M5 bars per trading day and ~260 trading days per year,
   one year ≈ **71,800 M5 bars**; five years ≈ **359,000 M5 bars**. This drives §11.
3. **Results are broker-conditional.** Gold CFD quotes, spreads, swaps and rollover
   times differ per broker. A validated edge on Broker A is a hypothesis on Broker B.
   Every experiment stores broker identity, server and terminal build.

### 3.3 Symbol specification capture

On ingestion, capture and freeze into `symbol_specs`: `digits, point, tick_size,
tick_value, contract_size, volume_min/max/step, stops/freeze levels, swap_mode,
swap_long, swap_short, swap_rollover3days, spread, spread_float, calc/trade mode`,
plus broker, server and terminal build. Never read these live inside a backtest.

### 3.4 Ingestion rules (verified against a live terminal, v1.2)

1. **Clock.** MT5 bar and tick `time` values are the **broker-server wall clock**
   encoded as epoch seconds — not UTC. Columns are named `ts_server`; nothing is
   relabelled as UTC until the broker's offset history is established (Phase 1, by
   anchoring each week's first bar to the known weekly open).
2. **Range bounds are server wall times, encoded explicitly.** The MetaTrader5 package
   interprets a *naive* `datetime` in the **machine's local timezone**. On an IST machine
   this silently shifted every range query by 5.5 hours and truncated the most recent
   bars. The gateway encodes bounds itself (`to_epoch_seconds`) and rejects tz-aware
   inputs as ambiguous. Regression-tested.
3. **Chunk below the terminal limit.** A single request covering more bars than
   "Max bars in chart" fails with `Invalid params`. Requests are split into windows of
   at most half the limit, de-duplicated and sorted (`fetch_rates_chunked`).
4. **Exclude the forming bar.** MT5 returns the in-progress bar with closed ones. Each
   bar is marked `complete` against the broker's own latest tick; raw storage keeps
   closed bars only and records how many forming bars were dropped.
5. **Empty ranges are not empty.** MT5 can return a single stale record for a window with
   no data. Coverage checks require a plausible count, never "non-empty".
6. Write raw Parquet (zstd) **read-only after write**, with a JSON sidecar: broker,
   build, account mode, price side, clock, offset estimate, request window, row count,
   forming bars dropped, SHA-256, frozen symbol spec.
7. Run the quality gate (§5) before anything downstream is derived. Incremental top-ups
   create new dataset versions; existing versions are never mutated.

### 3.5 Live findings (2026-09-21, Exness-MT5Trial7 demo, terminal build 6182)

**Broker identity comes from the account, not the terminal.** `terminal_info().company`
is the terminal vendor ("MetaQuotes Ltd."), which initially mislabelled this server as
MetaQuotes-Demo. The gateway now reports `account_info().company` / `.server` only
(never login, name or balance). The data below is **Exness Technologies Ltd**.

| Access path | Result |
|---|---|
| `copy_rates_from_pos` (latest N bars) | Capped at ~100,000 bars per timeframe by the terminal's chart limit |
| `copy_rates_range`, **month by month** | Full local archive: **M1 from 2021-07-01**, 1.84 M bars, no empty months |
| Broker-native M5 / M15 / H1 over that window | 369,659 / 123,361 / 30,940 bars |
| `copy_ticks_range`, day by day | **223 trading days, 70.8 M bid/ask ticks** (≈ 500 MB zstd Parquet) |

- Bulk ingestion therefore uses month-sized range requests, never `from_pos`.
- Broker clock measured as **UTC+0** year-round (break at 16:58 New York moves between
  20:58 and 21:58 UTC with US DST; 99.4 % of 1,042 measured days agree, the rest are
  holiday or data-hole days).
- M5 / M15 / H1 rebuilt from M1 match the broker's own bars **100 %** (OHLC, exact).
- First week (2021-06-28) is thin and excluded from the research window, which is
  **2021-07-05 → present, 5.2 years**.
- Exness-MT5Trial7 is a real broker's demo server, so its data is research-grade for this
  broker. Results remain broker-conditional (§3.2).

---

## 4. Storage Layout

| Dataset | Purpose | Storage |
|---|---|---|
| Raw M1 (bid) | Canonical candle history | Parquet, partitioned by year/month |
| Raw ticks (bid/ask) | Spread calibration + intrabar truth | Compressed Parquet, partitioned by date |
| Derived M5 | Primary signal timeframe | Parquet |
| Derived M15 / H1 | Context / regime features | Parquet |
| Features | Candle, structure, geometry features + `available_at` | Parquet |
| Labels | Triple-barrier outcomes per cost scenario | Parquet |
| Metadata | Datasets, specs, experiments, results, registry | PostgreSQL |

Raw data is immutable after import. Derived layers are always rebuildable from raw plus a
recorded config hash. Nothing downstream ever writes back into raw.

---

## 5. Data Quality Gate & Session Hygiene

### 5.1 Validation checks (blocking)

- Duplicate timestamps; non-monotonic time.
- Impossible OHLC relations (`high < max(open, close)`, `low > min(open, close)`, `high < low`).
- Missing bars inside expected trading sessions; gap length distribution.
- Price jumps beyond an N-sigma threshold of the local ATR distribution.
- Zero-volume or zero-range bars.
- Negative, zero, or absurd spread values.
- Chunk-boundary continuity — chunked pulls must stitch without overlap or hole.
- Coverage report: contiguous quality-passing range per timeframe.

Output is a `data_quality_runs` record. **The research window is the contiguous,
quality-passing range** — not whatever the broker happened to return.

### 5.2 Rollover detection (new — closes gap 7)

Do not hardcode the rollover minute. Detect it empirically as the recurring daily minute
exhibiting a tick-volume trough together with a spread spike, then confirm it is stable
across the dataset. Store it per dataset version.

### 5.3 Hygiene rules (new)

- The rollover bar and the bar immediately following are **excluded from signal generation**
  (they may still be held through, with swap charged).
- Weekend gap bars are flagged; no pattern geometry may span a weekend gap without carrying
  a `spans_gap` flag that reports separately.
- No new entries in the first 3 or last 3 M5 bars of the trading week.
- Bars whose spread exceeds the p99 of their hour-of-day distribution are flagged
  `abnormal_spread` and excluded from entry.

### 5.4 DST-aware sessions (new — corrects v1.0)

v1.0's "hour, London/NY overlap" as fixed UTC hours is wrong for roughly half the year.
Session labels are computed through the IANA tz database (`Europe/London`,
`America/New_York`, `Asia/Tokyo`) from the canonical UTC timestamp. Session boundaries are
features, not constants.

---

## 6. Cost Model (closes gap 2)

Costs are not a backtest parameter tucked in at the end. They are a first-class,
independently validated model, because on M5 gold they decide whether any edge exists.

### Layer 1 — Measured
From the tick window where true bid/ask exist, compute the empirical spread distribution
conditioned on `(hour_utc, day_of_week, volatility_bucket)`, where volatility_bucket is the
ATR percentile tercile. Retain p25 / p50 / p90 / p99 per cell.

### Layer 2 — Modeled
For bars outside tick coverage, assign spread from the matching conditional cell. Every bar
carries `spread_source ∈ {measured, modeled}`. Any result whose trades are predominantly
`modeled` is labelled lower-confidence in reports.

### Layer 3 — Stressed
Every backtest runs at **three cost scenarios**:

| Scenario | Spread | Slippage | Use |
|---|---|---|---|
| Optimistic | p25 | minimal | Upper bound / sanity |
| Base | p50 | expected | Headline result |
| **Pessimistic** | **p90** | **elevated** | **Promotion gate** |

**A strategy is not a candidate unless it holds positive net expectancy under the
pessimistic scenario.**

### Other cost components
- **Slippage** is modelled separately from spread: market orders take a fixed plus
  volatility-proportional component; stop orders take an asymmetric, always-adverse
  component, widened during flagged news and rollover windows.
- **Commission** is a configurable per-lot round turn.
- **Swap** applies only to positions held across rollover, with the triple-swap day handled
  per the broker's `swap_rollover3days`. V1 default is to flat positions before rollover;
  if a strategy holds, swap is charged explicitly.

### Implementation note — 2026-09-21 (Phase 2, `src/candle_intel/costs/`, `ci-costs`)

Two facts measured on Exness-MT5Trial7 changed how Layer 2 is built. The layer structure,
the three scenarios and the pessimistic promotion gate are unchanged.

1. **Spread moves in broker-set tiers, not by time of day.** Tick-measured spread was
   ~37 pts in Jan-2026, 137–155 in Mar, 80–90 in Jul–Sep; within a tier the hour-of-day
   profile is nearly flat except around the daily rollover. An absolute-spread cell table
   fitted on 2026 ticks therefore cannot describe 2021–2025.
2. **The M1 bar's `spread_points` is the minimum spread quoted in that minute** — equal to
   the tick minimum in 100 % of 252,833 overlapping minutes. It is a valid per-bar *level*
   for the whole history (6,045 bars report ≤ 0 and are imputed from the previous bar).

Layer 2 is therefore `spread_q(bar) = level(bar) × ratio_q(hour_utc, weekday, vol_tercile)`,
where `ratio` is quoted spread ÷ that minute's minimum, time-weighted from ticks. The
volatility tercile uses ATR(14) on M5 relative to its trailing 20-day median (raw ATR grew
~6× with price), computed from completed bars only. Pessimistic = max(observed or modeled
p90, p90 of the same cell over the last 60 tick days) — a cheap historical tier can never
flatter a strategy that would pay today's spread. Out-of-sample (last 20 % of tick days):
level×ratio bias +2.6 %, MAE 3.4 pts; the literal absolute-cell model +10.5 %, MAE 11.2 pts,
and on pre-tick history it overstates spread by a median 1.61× and predicts a typical spread
below the quoted minimum in 5.9 % of bars. Acceptance criteria (|bias| ≤ 15 %, p90
coverage ≥ 85 %) are fixed in `costs/validate.py`. Slippage parameters are explicit
assumptions (no fills on a demo account) to be refitted in Phase 9.

---

## 7. Leakage Control & Intrabar Resolution (closes gaps 3 and 9)

### 7.1 The `available_at` rule

Every feature and label row carries two timestamps:

- `event_time` — the bar the row describes.
- `available_at` — the earliest moment the value could have been known in real time.

**Hard rule:** a model or detector making a decision at time `T` may read only rows where
`available_at <= T`. This is enforced in code by the feature-access wrapper, not by
developer discipline.

Worked example: a swing high at bar `i` requiring `k` confirming bars to the right has
`event_time = t(i)` but `available_at = t(i + k)`. Trendlines anchored on that swing inherit
the later of their anchors' `available_at`. There are no exceptions to this rule anywhere in
the platform.

### 7.2 Leakage test suite (blocking, runs in CI)

- **Shifted-target canary** — re-run any pipeline against a target shifted into the past.
  A genuine pipeline must produce approximately zero edge. Any edge means leakage.
- **Future-shuffle test** — shuffle all bars after `T`; features available at `T` must not change.
- **Availability audit** — assert `available_at >= event_time` on every row, every build.
- **Recomputation test** — features computed on a truncated history ending at `T` must match
  features computed on the full history and then filtered to `T`.
- **No-live-call assertion** — research modules are import-checked to ensure they cannot
  reach the MT5 gateway or the MCP server (§3.1).

### 7.3 M1 as execution truth (closes gap 3)

**M5 is the signal timeframe. M1 is the execution resolution layer.** When a trade is open,
the backtester walks the five constituent M1 bars of each M5 bar in chronological order and
resolves stop and target against the M1 path, not the M5 OHLC.

When stop and target are both reachable inside the *same M1 bar*:

- Default policy is **pessimistic** — the stop fills first.
- Alternative policies (`optimistic`, `proportional`) exist for sensitivity analysis only.
- Every backtest reports an **ambiguity rate**: the fraction of trades whose outcome was
  decided by the ambiguity policy. If that rate exceeds **5%**, the result is flagged
  low-confidence and must be re-run against tick data before promotion.

Where tick coverage exists, resolve exactly and report how far the M1-pessimistic assumption
diverges from tick truth. That divergence is the error bar on every other backtest.

---

## 8. Labeling (closes gap 5)

### 8.1 Primary: triple-barrier

Every studied occurrence is labelled with three barriers:

- Upper barrier: `+u × ATR(14)` — default `u = 1.5`
- Lower barrier: `-d × ATR(14)` — default `d = 1.0`
- Vertical barrier: `h` bars — default `h = 24` M5 bars (2 hours)

Output per occurrence: `label ∈ {+1, 0, -1}`, realized `R`, time-to-exit, MFE, MAE, exit
reason, and the cost scenario under which it was computed. Barriers are ATR-scaled so labels
remain comparable across volatility regimes.

### 8.2 Secondary: fixed horizon (diagnostic only)

Forward returns at 3 / 6 / 12 / 24 M5 bars are retained for exploratory analysis and feature
screening. They are **never** used for strategy promotion decisions — a fixed-horizon return
does not correspond to anything a trader can execute.

### 8.3 Deferred

Meta-labeling and sample-uniqueness weighting are later-phase concerns, introduced only
after rule-based baselines are measurable.

---

## 9. Multiple-Testing Protocol (closes gap 4)

Pattern mining over hundreds of thousands of bars produces false discoveries by
construction. This protocol is mandatory, not advisory.

### 9.1 Three-tier time-ordered split

No shuffling. No random splits. Chronological only.

| Tier | Share | Position | Access policy |
|---|---|---|---|
| **A — Development** | ~60% | Earliest | Unlimited exploration |
| **B — Validation** | ~20% | Middle | Walk-forward and selection; **every access logged** |
| **C — Final Holdout** | ~20% | Most recent | **Sealed.** One access per strategy family, ever |

Tier C access is gated behind an explicit unseal operation that writes to
`holdout_access_log` with strategy id, timestamp, and stated reason. A second access for the
same strategy family **invalidates that tier for that family permanently** — it is then
treated as development data.

### 9.2 Hypothesis pre-registration

Before any outcome is computed, each behaviour is written into `pattern_definitions` with:
expected direction, intended horizon, minimum sample size, detection rule version, and a
registration timestamp. Results for unregistered hypotheses are exploratory findings and
cannot enter the promotion pipeline.

### 9.3 Trials accounting

Every backtest run increments a trial counter on its strategy family. Selection statistics
are computed against the **true** trial count:

- **Deflated Sharpe Ratio** using the recorded number of trials.
- **White's Reality Check** / **Hansen SPA** across the family of tested rules.
- **Benjamini–Hochberg FDR** control on behaviour-screening p-values.
- **Stationary bootstrap** confidence intervals on expectancy, respecting autocorrelation.

Reporting a Sharpe ratio without the trial count it was selected from is prohibited in this
platform's reports.

---

## 10. Regime and Stability Analysis (closes gap 6)

A shorter MT5 history partially mitigates the regime-mixing problem, but does not remove it.

Every result is reported broken down by:

- **Year** (and quarter where sample allows)
- **Session** — Asian / London / NY / London-NY overlap / off-session
- **Volatility regime** — ATR percentile terciles
- **Trend regime** — H1 structure state (up / down / range)

**Stability score:** the fraction of buckets in which the edge is same-signed. A behaviour
must be same-signed in **≥ 70%** of year buckets and **≥ 70%** of session buckets to remain
eligible. An edge that lives in one year or one session is a discovery about that period,
not about gold.

Known high-impact event windows (FOMC, NFP, CPI, major geopolitical dates) are marked, and
every result is reported both with and without them. An edge that exists only across news
events is a news-latency artefact, not a chart-behaviour edge.

---

## 11. Sample Size Requirements (closes gap 8)

Fixed before any research runs, so it cannot be relaxed to fit a preferred result.

**Minimum Detectable Effect.** For a per-trade return standard deviation of `σ_R ≈ 1.0 R`,
a target effect of `Δ = 0.10 R`, `α = 0.05` two-sided and power `1 − β = 0.80`:

```
n  ≈  (z[α/2] + z[β])²  ·  σ_R²  /  Δ²
   =  (1.96 + 0.84)²    ·  1.0   /  0.01
   ≈  785 occurrences
```

Rounded up and applied per tier:

| Tier | Minimum occurrences | Consequence if below |
|---|---|---|
| A — Development | **1,000** | Research observation only — cannot become a strategy |
| B — Validation | **250** | Cannot be promoted to candidate |
| C — Final Holdout | **100** | Result reported as indicative, not confirmatory |

**Feasibility implication.** With ~71,800 M5 bars per year, reaching 1,000 development
occurrences over a 3-year development tier requires a behaviour to fire on roughly **0.5%**
of bars or more. Rarer formations are explicitly **out of V1 scope** until longer history is
available. This is a deliberate constraint, not an oversight — it is what the chosen data
source permits.

---

## 12. Candle Behaviour Engine (unchanged from v1.0, plus availability)

| Feature family | Examples |
|---|---|
| Candle anatomy | body/range, upper wick/range, lower wick/range, close position |
| Relative movement | range vs rolling median/ATR, return, gap, acceleration |
| Sequence | 3/5/10/20-bar direction, overlap, compression, expansion, streaks |
| Momentum | rolling returns, impulse strength, follow-through |
| Volatility | ATR, realized range, percentile/regime |
| Location | distance to swing, support/resistance, previous high/low |
| Time context | DST-aware session, hour, weekday, rollover proximity |
| Multi-timeframe | M15/H1 trend, structure and volatility context |

Every feature carries `event_time` and `available_at` per §7.1. Multi-timeframe features
inherit the `available_at` of their slowest constituent — an H1 feature is not available
until that H1 bar has closed.

---

## 13. Visual Chart Intelligence

Hybrid, unchanged in principle: exact geometry comes from OHLC mathematics; vision models
assist only with ambiguous interpretation and are never the sole source of truth.

| Capability | Detection concept | Output |
|---|---|---|
| Swing highs/lows | Pivot / adaptive prominence | timestamp + price + strength + `available_at` |
| Support/resistance | Clustered reactions around price bands | zone bounds + touches + reactions |
| Trendlines | Fit through compatible swing points | slope + anchors + touches + breaks |
| Parallel channels | Parallel boundary search | upper/lower lines + width + validity |
| Ranges | Low slope + repeated boundary reactions | range high/low + duration |
| Breakout/retest | Level crossing + close/hold + revisit | break time + retest + outcome |
| Liquidity sweep candidate | Temporary breach + rejection/reclaim | level + excursion + close context |
| Chart formations | Geometry over swing sequences | coordinates + confidence |

Every detection maps to exact timestamps and price coordinates and is independently
verifiable against raw OHLC. Detections whose geometry spans a weekend gap or the rollover
bar are flagged and reported separately.

**Build order within this module:** swing points → support/resistance → trendlines →
channels → ranges → breakout/retest → sweeps → complex formations. Do not begin a stage
until the previous one passes its regression tests.

---

## 14. Backend, Frontend and Storage Blueprint

### 14.1 Backend

| Module | Technology | Responsibility |
|---|---|---|
| API | FastAPI | Research queries, experiments, reports |
| **MT5 gateway + ingestion** | **Direct `MetaTrader5` API** (`candle_intel.ingest`) | **Only module that imports MetaTrader5. Chunked pulls, spec freeze, forming-bar exclusion, Parquet snapshots** |
| **MT5 MCP server** | Official `mcp` SDK (`services/mt5_mcp`) | **Read-only, XAUUSD-only, capped tool surface for the AI assistant. Built on the gateway** |
| Feature engine | Polars + NumPy | Candle, sequence, structure features |
| Geometry engine | NumPy + SciPy | Swings, levels, lines, channels |
| Cost model | Python | Spread calibration, slippage, swap |
| Research worker | Python | Behaviour detection and outcome studies |
| Backtest worker | Python | Event-driven simulation with M1 resolution |
| ML worker | scikit-learn + LightGBM | Training and evaluation |
| Analytical query | DuckDB | Fast queries over Parquet |
| Metadata DB | PostgreSQL | Experiments, results, registry |
| Job queue (later) | Redis + RQ/Celery | Long-running jobs when needed |

The MCP server is **in-repo and purpose-built** (external servers failed review — see
`docs/reviews/mt5-mcp-security-review.md`). Its tool surface is pinned by tests.

### 14.2 Frontend — resequenced

v1.0 required a full Next.js Candle Explorer at Phase 2. That front-loads weeks of UI work
before any research value exists. v1.1 splits it:

- **Research viewer (early)** — lightweight local charting, sufficient to inspect candles,
  detections and trades. Purpose is verification, not product.
- **Full Next.js application (later)** — Next.js + TypeScript + Tailwind + shadcn/ui +
  TradingView Lightweight Charts + TanStack Query + Recharts. Built once there is validated
  content worth exploring: Dashboard, Candle Explorer, Visual Chart Lab, Pattern Lab,
  Backtest Lab, AI Model Lab, Paper Trading, Data Manager, Reports.

### 14.3 PostgreSQL tables

`datasets`, `symbol_specs`*, `data_quality_runs`, `ingestion_log`*, `cost_models`*,
`experiments`, `pattern_definitions`, `pattern_occurrences`, `strategies`, `backtest_runs`,
`backtest_trades`, `models`, `model_evaluations`, `trial_counts`*, `holdout_access_log`*,
`paper_signals`, `paper_trades`, `research_notes`

*New in v1.1.* Large numerical datasets stay in partitioned Parquet.

---

## 15. Definition of Success — Pre-Committed Thresholds

v1.0 correctly said thresholds must be defined before selection rather than retrofitted.
v1.1 defines them. Changing any number below requires a dated entry in `research_notes`
explaining why, written **before** the affected result is computed.

### Platform success
V1 succeeds even if no profitable model is found, provided the platform can: ingest and
validate MT5 XAUUSD data; reproduce chart structures at exact coordinates; detect behaviours
with a passing leakage suite; label outcomes under an explicit cost model; run reproducible
event-driven backtests with M1 resolution; compare models on unseen periods; and forward-test
candidates on paper.

### Strategy promotion to "candidate"
All of the following, simultaneously:

| Criterion | Threshold |
|---|---|
| Net expectancy, pessimistic costs | **≥ +0.10 R** per trade |
| Occurrences — development / validation | **≥ 1,000 / ≥ 250** |
| Profit factor, pessimistic costs | **≥ 1.15** |
| Max drawdown | **≤ 15 R**, and ≤ 20% of simulated equity |
| Stability — year and session buckets | **≥ 70%** same-signed in each |
| Intrabar ambiguity rate | **≤ 5%**, or tick-verified |
| Deflated Sharpe Ratio at recorded trial count | **> 0** |
| Final holdout expectancy | **> 0** after costs, and ≥ 50% of development expectancy |
| Holdout accesses | **exactly 1** |

### Paper-trading confirmation
- **≥ 60 trading days** and **≥ 100 signals** elapsed.
- Realized expectancy within **1 standard error** of the backtested expectancy.
- No material feature drift versus the training distribution.
- Observed spread and slippage within the modelled pessimistic scenario.

Failing any criterion returns the strategy to research. There is no partial promotion.

---

## 16. Development Roadmap (revised)

| Phase | Deliverable | Exit condition |
|---|---|---|
| **0 — Foundation** | Repo, configs, PostgreSQL schema, Parquet conventions, test harness | Reproducible local environment; CI green |
| **1 — MT5 Data Engine** | Direct-API chunked ingestion, spec freeze, quality gate, rollover detection, M1→M5/M15/H1 | Verified dataset version + coverage and quality report |
| **2 — Cost Model** | Spread calibration from ticks, slippage, swap, three scenarios | Cost model validated against tick window |
| **3 — Feature Store** | Candle/sequence/context features with `available_at` | **Leakage suite passes** — blocking gate |
| **4 — Research Viewer** | ~~Plotly viewer~~ → Next.js Chart Viewer, delivered with Phase 1; gains feature and detection overlays | Any bar and any detection visually verifiable |
| **5 — Visual Structure** | Swings, S/R, trendlines, channels | Detections map to exact coordinates; regression tests pass |
| **6 — Behaviour Research** | First 5 behaviours, pre-registered, triple-barrier labelled | Occurrence and statistics reports with sample-size verdicts |
| **7 — Backtester** | Event-driven, M1 resolution, ambiguity reporting, walk-forward | Deterministic, reproducible, ambiguity rate reported |
| **8 — ML Research** | Baselines → LightGBM → registry, trials-aware statistics | Validation-tier comparison against rule-based baseline |
| **9 — Paper Trading** | Live MT5 feed, simulated execution, drift monitoring | Forward-test telemetry operational |
| **10 — Research Gate** | Candidate / reject decisions against §15 | Documented verdict per strategy; no real money in V1 |
| **11 — Full Web UI** | Remaining pages (Backtest Lab, AI Model Lab, Paper Trading) and polish | Pages are added as each phase produces content |

Phase 3 is a hard gate. No behaviour research begins until the leakage suite passes.

---

## 17. V1 Initial Behaviour Library (unchanged)

Momentum continuation · Breakout + retest · Failed breakout · Support/resistance rejection ·
Liquidity-sweep candidate with reclaim/rejection · Volatility compression → expansion ·
Trendline/channel touch and break · Range boundary rejection/break

Each must be pre-registered per §9.2 before its outcomes are computed.

---

## 18. Repository Structure

```
Gold_Intelligence_AI/
├── src/candle_intel/          # research package (Python)
│   ├── config/                # typed settings; gold-only symbol validation
│   ├── ingest/                # MT5 gateway (sole MetaTrader5 importer) + ci-ingest CLI
│   ├── data/                  # validation, clock conversion, aggregation, dataset versions
│   ├── costs/                 # spread calibration, slippage, swap
│   ├── features/              # candle/sequence features + available_at
│   ├── structure/             # swings, S/R, trendlines, channels
│   ├── vision/                # chart renderer (exact pixel↔price) + CV cross-checks
│   ├── patterns/              # behaviour definitions + registration
│   ├── labeling/              # triple-barrier, diagnostics
│   ├── statistics/            # outcome studies, DSR, SPA, bootstrap
│   ├── backtest/              # event-driven engine, M1 resolution
│   ├── ml/                    # training and evaluation
│   ├── paper/                 # forward simulation
│   └── viewer/                # Plotly research viewer
├── services/
│   ├── mt5_mcp/ci_mt5_mcp/    # read-only XAUUSD MCP server for the AI assistant
│   └── api/ci_api/            # FastAPI (Phase 4+)
├── apps/web/                  # Next.js research UI (Phase 11)
├── infra/postgres/init/       # metadata schema
├── storage/                   # raw (read-only) / derived / features / models / reports — git-ignored
├── tests/
│   ├── unit/
│   ├── leakage/               # blocking: MT5 boundary + availability rules
│   ├── regression/
│   └── integration/           # live MT5 (pytest -m mt5)
└── docs/                      # blueprint, tech selection, reviews, requirements
```

---

## 19. Engineering Rules

- Secrets in environment variables or a secret manager. Broker credentials are never committed.
- `MetaTrader5` is imported only by `candle_intel/ingest/mt5_session.py`. Trading, order,
  position, deal-history and account functions are never referenced (AST-enforced).
- The MCP server is read-only and XAUUSD-only; its tool list is pinned by tests.
- Raw data is read-only after import.
- All timestamps canonical UTC; broker server offset stored as metadata, never assumed.
- Every experiment records code version, config hash, dataset version, cost model version,
  feature schema version, broker identity, and trial count.
- Unit tests for aggregation, feature calculation, geometry and order simulation.
- Regression tests for known historical pattern examples.
- **Leakage suite runs in CI and blocks merges.**
- Structured logs for ingestion, research, backtest and paper jobs.
- PostgreSQL metadata and model artifacts are backed up.

---

## 20. Architecture Principles

Research first, execution later. Gold only. Numerical truth first, visual AI second.
Live data stops at the ingestion boundary; research reads snapshots. Costs are a model, not a
parameter. Availability is enforced in code, not in convention. The holdout is sealed.
Thresholds are set before results, not after.

Every chart observation must be convertible into exact data, and every claimed edge must
survive realistic costs, an honest trial count, and forward validation before it is called
an edge at all.

---

## Appendix A — Open Items

| # | Item | Needed by |
|---|---|---|
| A1 | ~~MT5 MCP repo to pin~~ — resolved: purpose-built server (v1.2) | — |
| A1b | Set terminal **Max bars in chart = Unlimited**, restart, re-run `ci-ingest probe` | Phase 1 |
| A1c | Log in with the **investor password** and switch **Algo Trading off** | Before any live session |
| A2 | ~~Broker~~ — resolved: Exness Technologies Ltd, Exness-MT5Trial7 (demo) | — |
| A3 | ~~Coverage probe~~ — tool built (`ci-ingest probe`); re-run on the real broker after A1b | Phase 1 |
| A4 | Confirm commission per lot and current swap values for the account type. Until confirmed, the pessimistic scenario charges $7/lot round turn (`ci-costs build --commission-per-lot X --commission-confirmed` once known) | Phase 7 |
| A5 | Economic-news calendar for widened stop slippage (hook exists: `slippage_points(in_window=...)`; only the rollover window is flagged today) | Phase 7 |
| A6 | Refit slippage parameters from simulated-vs-live fills | Phase 9 |
