# Requirement — Simple mode UI (2026-09-22)

## Owner's words

> "features to sare 1 number hai but as a user its confusing very much … user frendly ui kaise
> kar skte hai" — then, after the explanation and the clickable mockup:
> "haa problem sahi pakdi hai ekdum perfect, mock up banao phle" → "tum implement karo sab
> complete karo phir commit and push rebuild if needed".

## What was wrong (agreed diagnosis)

1. The app grew one page per roadmap phase, not per user goal — 12 equal sidebar items.
2. Engine vocabulary on screen (Deflated Sharpe, §15, tier A∪B, SR0, FDR q, p90 …).
3. Results show many numbers at once; the answer ("does it work, and why?") is never one line.
4. No guided path — the order Strategy Lab → Backtest → Optimize → Validate must be known.
5. Four doors to "make a strategy"; mixed Hinglish / English.

## Decision

A **Simple mode**, default, beside the unchanged **Expert mode** (sidebar switch; stored per
browser). Nothing is removed; every research guardrail (§9 trials, sealed tier C, pessimistic
costs, §15) is untouched — Simple mode only words and routes the engine's own numbers.

| Simple page | Route | What it does |
|---|---|---|
| Home | `/` | "Aaj kya karna hai?" — 3 goals (idea test / AI research / market samjho), Meri strategies with journey + next step, 1-minute glossary chips. Expert mode shows the chart Overview here (also at `/chart`). |
| Idea test karo | `/idea` | 5 plain questions (idea, session, side, stop/target, check) → a real `strategy-spec/1` → saved (`created_by: owner`, family per idea) → backtest on tier A → result. "Chart pe khud dikhaunga" opens the Chart-Based Creator. |
| Result | `/result?run=` | Answer first: verdict card (pass / weak / costs ate it / no edge / too few trades / no trades), 3 numbers with "?" help, "Paisa kahan gaya" (before costs − costs = left), "Ab kya karein?" (one-click 1:3 re-test, AI filter, final check, drop), Expert details table with plain names + run id. |
| AI Research | `/ceo-lab` | The CEO Work Lab, retitled. |
| Market samjho | `/learn` | Latest tier-A behaviour screen in plain words per pattern (works after costs / edge but costs eat it / no effect / too little data); starts a screen if none exists. |
| Meri strategies | `/my` | Every saved strategy as a journey — Banaya → Pehla test → Sudhaaro → Final check → Paper trade — plain status and one next step (run the test, see result, final check). |

Wizard mapping (`src/lib/plain.ts`): sweep = `pdl_sweep` long / `pdh_sweep` short (family
`prev-day-sweep`); reversal = the Three-candle template (`three-candle-reversal`); momentum =
the London-open template (`london-momentum`, London only). Sessions: Asian / London (+overlap)
/ New York (+overlap) / all. Exits: small 1×/1.5× 24 bars, balanced 1.5×/3× 48 bars, big 2×/6×
96 bars. Sizing 1 % of USD 10,000. Variants of one idea share its family, so the trial count
stays honest.

Verdict wording thresholds are the §15 lines (+0.10 R, PF 1.15) plus a 100-trade floor for
"too few to judge"; the Validate checklist remains the only judge of a candidate.

Mockup reviewed first: https://claude.ai/artifact/RzxVhU5hmVQadZUYhLj4aa (private to the owner).
