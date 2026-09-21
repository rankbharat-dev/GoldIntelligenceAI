# Requirement Update — 2026-09-21 (evening)
Source: project owner (chat). Owner's words saved verbatim, then the decisions they settle.

---

## Owner's words (verbatim)

> dekho mujhe UI poora controled chahiye taaki mai wha startegy create kar sakoo
> Tumhara goal sirf Gold ka chart dekhna, support-resistance identify karna ya candlestick
> patterns detect karna nahi hai.
>
> Tum chahte ho ki 20 saal ke XAUUSD historical data se ek AI Research Engine khud trading
> strategies discover kare, unhe backtest kare, improve kare aur tumhe statistically
> profitable strategy candidates de.
>
> Aur ye sab tum apne laptop par localhost ke interactive dashboard se control kar sako.

Answers to the follow-up questions:

> 1- abhi 5 saal se hi shuru karke baad mein add krnege.
> 2- commision - mai real time pe raw account use krunga jisme spread nahi hai but commision hai
> 3- jo bhi mere profitable startegy banane me help kare wo tool chaiye web page pe ..
> abhi new goal btane ka matlab ye nhi ki pichle wale me sab hta do ...tumko jo thik lage us
> hisaab se ek new master prompt banao ek md file me mai next new session me use krunga ....

---

## Decisions this settles

| # | Decision | Consequence |
|---|---|---|
| D1 | **Goal widened, nothing removed.** The platform becomes a strategy research workbench: an AI Research Engine discovers, backtests and improves strategies and returns statistically validated candidates; the owner can also build strategies by hand. Everything built so far (data engine, cost model, chart viewer, blueprint rules) stays. | Roadmap re-ordered so the strategy spec + backtester + builder UI come right after the feature store. See `docs/MASTER_PROMPT.md`. |
| D2 | **Fully controllable localhost dashboard.** Every tool that helps build a profitable strategy belongs on the web UI. | Each phase ships its UI page. |
| D3 | **Data: start with the 5 years available (2021-07 →), add ~20 years later** (candidate source: Dukascopy, ~2003 →). | 20-year import is a later phase; the design must allow multiple data sources per dataset. |
| D4 | **Live trading will be on an Exness *Raw Spread* account**: near-zero spread + commission per lot. | The cost model needs an account profile. The current model was calibrated on the demo `Exness-MT5Trial7` account (spread ~90 pts, account type unconfirmed). A Raw-account profile needs ticks from a **Raw Spread demo** and the commission from Exness's contract specification (to be confirmed by owner — Appendix A4). Until then the pessimistic scenario keeps charging the conservative $7/lot round turn. |
| D5 | **The platform itself stays research + paper trading** (blueprint §1). Owner's live trading on the Raw account happens outside this platform unless a later, explicit decision and blueprint version change that. | No order-sending code anywhere; AST test stays. |
| D6 | Builder style and engine autonomy were left to Claude ("jo thik lage"): **form-based builder first, visual blocks later; engine supports both "suggest → owner approves" and unattended overnight runs**, always inside the multiple-testing guardrails (blueprint §9, §15). | Guardrails are not user-configurable from the UI. |
