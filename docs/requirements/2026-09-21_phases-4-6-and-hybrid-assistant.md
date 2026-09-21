# Requirement Update — 2026-09-21 (late night): build Phases 4–6, hybrid AI Assistant
Source: project owner (chat). Owner's words verbatim, then the decisions they settle.

---

## Owner's words (verbatim)

> commit aur push kar do, phir Phase 4 ,5 ,6 teeno step by step finish karo phir update karna
> aur AI Assistant mujhe hubrid model chahiye  with api and without api

> upar api key hai ise env file me store kar lena aur models screenshot me hai

The screenshot shows an **AgentRouter** (https://agentrouter.org) account whose model list
contains: `claude-opus-4-8`, `claude-opus-5`, `deepseek-v4-flash`, `gpt-5.6-sol`, `gpt-6-astra`.
(The key itself is in `.env` only — never in git, docs or chat summaries.)

---

## Decisions this settles

| # | Decision | Consequence |
|---|---|---|
| H1 | Phases 4, 5 and 6 are built in one go (spec + backtester → Builder + Backtest + Library → jobs + Optimize + Validate). | Done 2026-09-21; see HANDOFF §6d. |
| H2 | **AI Assistant = hybrid** (answers Q-UI1): **(a) no-API mode** — Claude Code / Claude Desktop drives the engine through tools and results appear in the dashboard; **(b) API mode** — a chat panel inside the dashboard calls an LLM through the owner's AgentRouter key. Both modes use the same engine tools and the same guardrails. | Built in Phase 10. The dashboard shows which mode is active; API mode is optional and switches off cleanly when no key is set. |
| H3 | API credentials live in `.env` as `CI_LLM_PROVIDER`, `CI_LLM_BASE_URL`, `CI_LLM_API_KEY`, `CI_LLM_MODEL` (default `claude-opus-5`), `CI_LLM_FAST_MODEL` (default `deepseek-v4-flash`). `.env` is git-ignored; `.env.example` documents the names only. | The key is never logged, never sent to the browser, never written to run files. Calls go server-side from the API. |
| H4 | AgentRouter is a **third-party router**, not Anthropic directly. What is sent to it is limited to: the owner's question, strategy specs, and engine results. Never MT5 credentials, never `.env` content, never tier-C data before an unseal. | Recorded here so Phase 10 designs the payload to this rule. |
| H5 | Either mode may only **propose**; a proposed spec is saved with `created_by = "assistant"` and runs through the same backtester, trial counter and §15 checklist. No mode can unseal a holdout. | Assistant cannot bypass §9/§15. |
