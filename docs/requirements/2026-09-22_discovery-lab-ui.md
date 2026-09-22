# Requirement — Gold Strategy Discovery Lab UI (2026-09-22)

## Owner's words

> "abhi ek report banawaya but charts pe kaise verify krenge ki tumne trade mere according liya ki
> nahi koi chart preview nahi hai, indicator ka bhi kuch pta nahi chal rha hai"

Plus a written brief (with five reference screenshots: a trade journal with an entry/SL/TP chart,
ChartingPark replay, an R-box position tool, an MT5 strategy overlay) listing four gaps —
visual strategy experience, visual research results, interactive AI research, strategy
improvement journey — and six improvements: interactive Home, visual builder with a live
chart, conversational AI research, visual backtest results with trade replay, a strategy
journey, and navigation around **Explore Market · Create & Discover · Test & Analyze · My
Strategy Lab** with Expert mode kept. Improve, don't rebuild; keep the dark/gold identity,
backend, research integrity, costs, OOS and sealed holdout; never present an unvalidated
strategy as profitable.

## What was built

Nothing in the engine changed; two **read-only** endpoints were added.

| Piece | Where | What it does |
|---|---|---|
| `GET /api/indicators?start&end` | `services/api/ci_api/main.py` | The engine's stored M5 indicators as chart lines. EMA 9/21/50/200, Bollinger (50, 2.1) and session VWAP are rebuilt to price from the stored distances (`level = close − dist × ATR`, ATR = `atr_pts × point`); RSI 14, MACD hist, Stoch %K, ADX as stored. Nothing is recomputed, so the chart shows exactly what the rules read. Cross-checked against a direct EMA/BB computation. |
| `POST /api/strategy/explain {spec, time}` | `services/api/ci_api/research.py` | One decision bar checked against a spec: every entry condition and filter with the bar's actual value, evaluated with the engine's own `condition_expr` / `filter_expr`. Tier C bars → 403 (sealed). |
| Trade replay | `components/replay/` | A backtest's pessimistic trades on the real chart: signal candle, entry, SL/TP zones (R-box), exit, engine indicators (EMA / BB / VWAP / RSI pane), 1 / 5 / 15-min candles, bar-by-bar replay (1× 2× 5×), win/loss filter, and the rule check ("Aapke saare rules is candle pe sach the"). Indicator values are placed on the bar at which the engine could read them (M5 close), never earlier. |
| Result page | `/result?run=` | Adds: "Kyun kaam nahi kiya?" reasons (costs vs edge, years, sessions), "Paise ka safar" equity curve, **Chart pe verify karo** (replay), "Kab chali, kab nahi?" bars by year / session / market mood / side. A pass is always worded as "practice data only — final check baaki". |
| Test & Analyze hub | `/results` | Every test and final check, newest first, with plain status → result + chart. |
| Idea builder | `/idea` | Live panel: the strategy sentence updates as you answer, and a real XAUUSD chart shows where the rules fire (via `/api/strategy/preview`, tiers A+B only; not a backtest, no trial) with signal counts. |
| Chart-based creation | `/idea/chart` | The Expert Chart-Based Creator in Hinglish (`plain` prop): click the entry candle → keep 2–4 facts → pick stop/target → test. Family `chart-idea` (same as Expert), so trials stay honest. |
| AI Research chat | `components/ceo/chat.tsx` | Replaces the Director Room + activity log with one conversation per mission: CEO messages, the Director's plan and replies, each agent's finished work with its source runs, the final report; quick-reply chips; who is working now. Replies are asynchronous (Director reads messages on its next `/ceo-run`) — never simulated. Finished missions turn their recommendations into one-click follow-up missions. |
| Strategy journey | `/strategy?spec=` | Stage tracker, the spec in words, the next honest actions (chart replay, 1:3 version, AI improvement mission with plan approval), why the first test failed, final-check items in plain words, research history timeline, versions with "what changed". |
| Home | `/` (Simple) | "Wahin se aage badho" continue card (running test → active mission → a strategy's next step → first idea), what is running now (tests, missions, agents), latest results, the lab's honest numbers (tested, trials, final-check passes "still not profitable"), the four sections. |
| Navigation | `components/app-shell.tsx` | Both modes grouped under the four sections. Expert keeps every page (Overview, Data Center, Behaviour Explorer · CEO Work Lab, Strategy Lab, Pipeline, Assistant · Backtest, Optimize, Validate, ML Lab · My Strategies). The Expert Backtest page also gets the replay. |

Removed: `components/ceo/director-room.tsx` (its function lives in the research chat).

## Integrity notes

- Replay, explain and indicators read stored engine outputs; no numbers are computed in the UI
  except display thinning of the equity curve (≤ 300 real points; totals use all trades).
- Preview and explain add no trials. Every test / new version still counts as a family trial.
- Tier C stays sealed: explain refuses it, preview excludes it, the builder chart opens before it.
- Verdict wording still uses the §15 lines; only the Validate checklist judges a candidate.
