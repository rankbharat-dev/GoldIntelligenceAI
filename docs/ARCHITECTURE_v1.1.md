# CANDLE INTELLIGENCE AI
> **Superseded by [ARCHITECTURE_v1.2.md](ARCHITECTURE_v1.2.md)** (2026-09-21). Kept for history.
## XAUUSD-Only Research Platform — Architecture & Technical Blueprint
**Version 1.1** · Supersedes v1.0 · Data source locked: **MT5 broker export, via MT5 MCP server**

---

## 0. What Changed in v1.1

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
| Data source | **MT5 broker export via MT5 MCP server (locked)** |
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

## 3. Data Source: MT5 via MCP Server

### 3.1 Transport and boundary

Historical data is pulled from the MT5 terminal through an external **MT5 MCP server**
(existing repo, used as-is — not vendored into this project).

**Architectural rule — the MCP is an ingestion boundary, nothing more.**

```
MT5 terminal  →  MT5 MCP server  →  ingestion adapter  →  immutable Parquet  →  ALL research
                                    ^^^^^^^^^^^^^^^^^
                                    the only layer that
                                    may talk to the MCP
```

No feature, detector, backtest, model or report ever calls the MCP. They read Parquet
snapshots bound to a dataset version. Three reasons this is non-negotiable:

- **Reproducibility.** A live call returns whatever the broker serves today. An experiment
  must be re-runnable against byte-identical inputs months later.
- **Leakage.** A live call inside research code can trivially reach data beyond the
  simulated decision time. Removing the capability removes the class of bug.
- **Determinism and cost.** Research re-runs thousands of times; the MCP is an interactive
  transport with latency, payload limits and session state.

The adapter is deliberately thin, so that swapping the MCP for the direct `MetaTrader5`
Python package (or a different MT5 MCP) is a single-file change.

### 3.2 What the underlying MT5 data provides

Whatever surface the MCP exposes, it is backed by MT5's own structures, so the substance is:

| Source | Fields | Practical limit |
|---|---|---|
| Rates (M1) | `time, open, high, low, close, tick_volume, spread, real_volume` | Typically 2–6 years for XAUUSD, broker-dependent |
| Ticks | `time_msc, bid, ask, last, volume, flags` | Typically weeks to ~2 years of real bid/ask |
| Symbol info | Contract and cost specification | Current values only — snapshot and freeze |

Three consequences that shape the whole platform:

1. **Bars are bid prices.** MT5 OHLC for XAUUSD is the bid series. The ask side is
   reconstructed as `ask = bid + spread`. The per-bar `spread` field is a point-value
   snapshot, not a bar average — a weak proxy, treated as such (§6).
2. **History is short.** The 20-year ambition in the original brief is **withdrawn**.
   Plan for 3–6 years. At roughly 276 M5 bars per trading day and ~260 trading days per
   year, one year ≈ **71,800 M5 bars**; five years ≈ **359,000 M5 bars**. This number
   drives the sample-size rules in §11.
3. **Results are broker-conditional.** Gold CFD quotes, spreads, swaps and rollover times
   differ per broker. A validated edge on Broker A is a hypothesis, not a result, on
   Broker B. Every experiment record stores broker identity, server name and terminal
   build; every report carries this caveat.

### 3.3 Symbol specification capture (new)

On first ingestion, capture and freeze into `symbol_specs`, with a timestamp:

`digits, point, tick_size, tick_value, contract_size, volume_min/max/step,
trade_stops_level, freeze_level, swap_mode, swap_long, swap_short, swap_rollover3days,
margin settings, session quote/trade hours, broker name, server name, terminal build`

These change at the broker's discretion. Never read them live inside a backtest — always
read the frozen version bound to the dataset version.

### 3.4 Ingestion procedure

1. Pull M1 through the MCP in **monthly chunks**, with retry, resume-from-last-success, and
   a per-chunk request log. Chunking keeps payloads inside MCP limits and makes partial
   failures recoverable.
2. Pull the **full available tick window** early — this is the spread calibration set and
   the intrabar ground-truth set. Brokers roll tick history off; it cannot be recovered later.
3. Normalize all timestamps to UTC, preserving the broker's server offset as metadata.
   Broker server time is commonly UTC+2/+3 with its own DST rules — record it, do not assume.
4. Write raw M1 and ticks to partitioned Parquet, **read-only after write**, tagged with a
   dataset version and the ingestion log.
5. Run the quality gate (§5) before anything downstream is derived.
6. Incremental top-ups append new bars under a new dataset version. Existing versions are
   never mutated.

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
- Chunk-boundary continuity — MCP pulls must stitch without overlap or hole.
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
  reach the MCP adapter (§3.1).

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
| **MT5 ingestion adapter** | **External MT5 MCP server + thin Python adapter** | **Chunked pulls, spec freeze, Parquet snapshot. Only layer permitted to call the MCP** |
| Feature engine | Polars + NumPy | Candle, sequence, structure features |
| Geometry engine | NumPy + SciPy | Swings, levels, lines, channels |
| Cost model | Python | Spread calibration, slippage, swap |
| Research worker | Python | Behaviour detection and outcome studies |
| Backtest worker | Python | Event-driven simulation with M1 resolution |
| ML worker | scikit-learn + LightGBM | Training and evaluation |
| Analytical query | DuckDB | Fast queries over Parquet |
| Metadata DB | PostgreSQL | Experiments, results, registry |
| Job queue (later) | Redis + RQ/Celery | Long-running jobs when needed |

The MT5 MCP server is an **external dependency**, pinned by repo URL and commit in
`shared/config`. It is not vendored, not forked, and not modified from this project.

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
| **1 — MT5 Data Engine** | MCP adapter, chunked ingestion, spec freeze, quality gate, rollover detection, M1→M5/M15/H1 | Verified dataset version + coverage and quality report |
| **2 — Cost Model** | Spread calibration from ticks, slippage, swap, three scenarios | Cost model validated against tick window |
| **3 — Feature Store** | Candle/sequence/context features with `available_at` | **Leakage suite passes** — blocking gate |
| **4 — Research Viewer** | Thin local chart inspection of candles, features, detections | Any bar and any detection visually verifiable |
| **5 — Visual Structure** | Swings, S/R, trendlines, channels | Detections map to exact coordinates; regression tests pass |
| **6 — Behaviour Research** | First 5 behaviours, pre-registered, triple-barrier labelled | Occurrence and statistics reports with sample-size verdicts |
| **7 — Backtester** | Event-driven, M1 resolution, ambiguity reporting, walk-forward | Deterministic, reproducible, ambiguity rate reported |
| **8 — ML Research** | Baselines → LightGBM → registry, trials-aware statistics | Validation-tier comparison against rule-based baseline |
| **9 — Paper Trading** | Live MT5 feed, simulated execution, drift monitoring | Forward-test telemetry operational |
| **10 — Research Gate** | Candidate / reject decisions against §15 | Documented verdict per strategy; no real money in V1 |
| **11 — Full Web UI** | Next.js research application | Built only once there is validated content to explore |

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
candle-intelligence/
├── apps/
│   └── web/                  # Next.js research UI (Phase 11)
├── services/
│   └── api/                  # FastAPI
├── research/
│   ├── ingest/               # MT5 MCP adapter — sole MCP caller      [new]
│   ├── data/                 # validation, aggregation, dataset versions
│   ├── costs/                # spread calibration, slippage, swap     [new]
│   ├── features/             # candle/sequence features + available_at
│   ├── structure/            # swings, S/R, trendlines, channels
│   ├── patterns/             # behaviour definitions + registration
│   ├── labeling/             # triple-barrier, diagnostics            [new]
│   ├── statistics/           # outcome studies, DSR, SPA, bootstrap
│   ├── backtest/             # event-driven engine, M1 resolution
│   ├── ml/                   # training and evaluation
│   ├── paper/                # forward simulation
│   └── viewer/               # thin research chart viewer             [new]
├── shared/
│   ├── schemas/
│   └── config/               # incl. pinned MT5 MCP repo + commit
├── storage/
│   ├── raw/                  # read-only after write
│   ├── derived/
│   ├── features/
│   └── models/
├── tests/
│   ├── unit/
│   ├── regression/           # known historical pattern examples
│   └── leakage/              # blocking leakage suite                 [new]
└── docs/
```

---

## 19. Engineering Rules

- Secrets in environment variables or a secret manager. Broker credentials are never committed.
- The MT5 MCP server is pinned by repo and commit, used unmodified, and called only from
  `research/ingest`.
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
The MCP is an ingestion boundary, not a research dependency. Costs are a model, not a
parameter. Availability is enforced in code, not in convention. The holdout is sealed.
Thresholds are set before results, not after.

Every chart observation must be convertible into exact data, and every claimed edge must
survive realistic costs, an honest trial count, and forward validation before it is called
an edge at all.

---

## Appendix A — Open Items

| # | Item | Needed by |
|---|---|---|
| A1 | MT5 MCP server repo URL + commit to pin in `shared/config` | Phase 1 |
| A2 | Broker name and server (determines history depth, spread profile, rollover time) | Phase 1 |
| A3 | Confirm available M1 history depth and tick window depth via a coverage probe | Phase 1 |
| A4 | Confirm commission per lot and current swap values for the account type | Phase 2 |
