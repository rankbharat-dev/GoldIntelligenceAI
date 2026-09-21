# Requirement Update — 2026-09-21 (night): new UI design direction
Source: project owner (chat). Reference image: [`new_reference_image.png`](../../new_reference_image.png)
(repo root). Owner's words saved in short, then the decisions they settle.

---

## Owner's words (condensed, Hinglish kept)

> **Naye design mein kya genuinely naya hai?**
> 1. **Chart-first workspace** — chart ab analysis output nahi, central workspace hai; market
>    ko visually explore karke directly research start karo.
> 2. **Three strategy creation methods** — AI Discovery, Visual Builder aur Chart-Based Creator
>    ek hi Strategy Lab mein, clear entry point ke saath.
> 3. **Research history and strategy library** — har research run, discovered strategy, uske
>    versions aur test results save; baad mein continue ya compare.
> 4. **AI Assistant inside the workspace** — Claude se hypotheses, chart observations aur
>    results par baat; Python engine actual numerical testing karega.
>
> **Missing cheezein jo zaroor include karni hain:**
> - **Market Behaviour Explorer** — candle sequences, volatility regimes, liquidity behaviour,
>   session patterns, S/R reactions explore karne ka visual workspace.
> - **Autonomous Research Pipeline** — AI hypotheses generate kare, Python engine test kare,
>   rejected aur promising hypotheses ka record rahe.
> - **Visual Pattern Intelligence** — trendlines, channels, swing structures, liquidity sweeps,
>   price-action formations ko measurable rules mein convert karna.
> - **Strategy Validation Lab** — in-sample, out-of-sample, walk-forward, cost sensitivity,
>   robustness tests, taaki overfitting pakdi ja sake.
>
> **Direction:** existing backend aur research engine replace mat karo; naya UI uske upar
> interactive research layer ho:
> `NEW INTERACTIVE UI → AI RESEARCH ORCHESTRATOR (Claude Code/Desktop) → EXISTING PYTHON
> ENGINE → HISTORICAL DATA STORAGE`.
> Naye image ka visual design aur navigation rakho, core = deep research + visual pattern
> intelligence + autonomous discovery.
>
> **Important:** image ke strategy metrics, research runs aur AI analysis illustrative hain —
> unhe actual Python engine ke verified results se connect karna hoga.

---

## Decisions this settles

| # | Decision | Consequence |
|---|---|---|
| U1 | The reference image sets the **look and navigation**: dark background, gold accent, left sidebar, chart-first Overview. | App shell rebuilt now (sidebar + top bar + gold theme); every future page slots into it. |
| U2 | **Nothing on screen is invented.** A panel either shows a number the Python engine produced (with its source) or an honest empty state saying which phase fills it. | No placeholder metrics, no fake "AI Insight", no fake research runs. Sidebar items not built yet are shown disabled with their phase number. |
| U3 | Sidebar = Overview · Data Center · Behaviour Explorer · Strategy Lab (AI Discovery / Visual Builder / Chart-Based Creator) · Backtest · Optimize · Validate · Research Pipeline · My Strategies · AI Assistant. | Mapped to roadmap phases in MASTER_PROMPT §6. |
| U4 | **Chart-Based Creator** = owner marks a pattern on the chart → system turns it into measurable rules (a strategy-spec draft) that the owner reviews. | Needs Phase 7 geometry (swings, trendlines, channels, sweeps) as spec building blocks; it never skips validation. |
| U5 | **Visual Builder** = the form builder (Phase 5) first, drag-and-drop blocks later — same spec underneath. | Consistent with the 2026-09-21 "form first" decision. |
| U6 | **Research Pipeline** keeps every hypothesis — accepted *and* rejected — with its pre-registration, trial count and failure reason. | Rejected ideas are a first-class record (§9 trials accounting), not deleted. |
| U7 | **AI orchestrator = Claude Code / Claude Desktop** talking to the engine through tools; the Python engine does all numbers. | A research MCP/API surface (run backtest, read results, propose spec) is added in Phase 8 alongside the read-only data MCP, which stays read-only. The in-page AI Assistant panel is decided in Phase 10 (see open question Q-UI1). |
| U8 | Image's "2004–2024 (20 years)" is the target, not today. | The header shows the **real** dataset range (currently 2021 →); 20-year data stays Phase 12. |

## Open question for the owner

| # | Question |
|---|---|
| Q-UI1 | In-page AI Assistant chat: (a) no API key — chat happens in Claude Code/Desktop and results appear in the UI, or (b) a chat box inside the dashboard using a Claude API key from `.env` (paid per use). The image says "No API required", so (a) is the default until you say otherwise. |
