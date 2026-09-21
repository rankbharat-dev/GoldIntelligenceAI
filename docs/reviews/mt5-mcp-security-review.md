# MT5 MCP Server — Security Review
2026-09-21 · Reviewer: Claude (code-level review of cloned sources) · Decision owner: project owner

Requirement under test (from [../requirements/2026-09-21_tech-stack-and-mt5-mcp.md](../requirements/2026-09-21_tech-stack-and-mt5-mcp.md)):
read-only; XAUUSD only; historical OHLCV, ticks, current price, spread, symbol info;
no trading / order / account operations; credentials never exposed; verify security,
maintenance, licensing, compatibility.

---

## 1. amirkhonov/metatrader5-mcp

| Item | Finding |
|---|---|
| License | MIT |
| Activity | Last push 2026-06-23; 1 star; 14 open issues |
| Stack | `fastmcp` (unpinned `*`), `mcp>=0.9`, `MetaTrader5`, pydantic |
| Tool surface | 30 `@mcp.tool` functions across connection, market, positions, status, trading modules |
| **Trading** | `mt5_order_send` (`tools_trading.py:123`) calls `mt5.order_send(request)` directly. `mt5_order_check` also exposed |
| Account / portfolio | `mt5_account_info`, `mt5_positions_get/total`, `mt5_orders_get`, `mt5_history_orders_get`, `mt5_history_deals_get/total` |
| Symbol restriction | None |
| Read-only switch | None found |

**Verdict: Reject.** Placing orders is a first-class feature. Making it read-only means
deleting most of the codebase — at that point it is no longer this project.

## 2. Cloudmeru/MetaTrader-5-MCP-Server

| Item | Finding |
|---|---|
| License | MIT |
| Activity | Last push 2026-08-13; 3 stars; 0 open issues; has tests and CI |
| Stack | FastMCP v3 (`fastmcp-slim`), pandas, matplotlib, `ta`, optional plotly |
| Tool surface | `mt5_query`, `mt5_analyze`, `mt5_execute` — all annotated `readOnlyHint: True` |
| Good | `SafeMT5` proxy exposes an allowlist of MT5 functions without `order_send`; rate-limit middleware; HTTP binds 127.0.0.1 by default |
| **Code execution** | `mt5_execute` compiles and `exec()`s LLM-supplied Python (`executor.py:89`, `:200`). Protection is a **substring blocklist** (`mcp_tools.py:62`). `exec` is called with a namespace that has no `__builtins__` key, so Python injects the real builtins |
| Why the sandbox fails | Blocklists match literal text. Any runtime-built name defeats them: `getattr(__builtins__, "__imp" + "ort__")("MetaTrader5")` yields the unrestricted module and therefore `order_send`. `pd` and `np` are the full packages, which reach `os` and the filesystem through their own module attributes. Net effect: arbitrary code execution as the user, on the machine running the logged-in terminal |
| Account data | `account_info`, `positions_get`, `positions_total`, `history_deals_get`, `history_orders_get` are in the allowlist (positions are additionally blocklisted in `mt5_execute` only) |
| Symbol restriction | None |
| Annotation accuracy | `mt5_execute` is annotated read-only and non-destructive, which it cannot guarantee |

**Verdict: Reject as-is.** A fork removing `mt5_execute`, the account/position/history
functions, and adding symbol pinning would be viable, but would retain a larger
dependency tree (pandas, matplotlib, `ta`, FastMCP) than the requirement needs.

No exploit was executed against the terminal; findings are from source review.

## 3. Decision: purpose-built server

`services/mt5_mcp/ci_mt5_mcp/server.py`, on the official `mcp` SDK (MIT) and official
`MetaTrader5` package.

| Requirement | How it is met | Verified by |
|---|---|---|
| Read-only | Tools call only `candle_intel.ingest.mt5_session`, which exposes an allowlist proxy (`api`) with no trading/order/position/history functions | `tests/leakage/test_mt5_boundary.py::test_no_trading_surface_referenced` (AST scan of all source) |
| No code execution | Six fixed, typed tools. No eval/exec path | `tests/unit/test_mcp_surface.py::test_tool_set_is_exactly_the_allowlist` |
| XAUUSD only | No tool has a symbol parameter. The broker symbol comes from config and must match a spot-gold pattern | `test_no_tool_accepts_a_symbol`, `tests/unit/test_settings.py` |
| Research timeframes only | `timeframe` is an enum of M1/M5/M15/H1 | `test_rates_timeframes_are_research_timeframes_only` |
| No account identifiers | `account_info` is read inside the gateway only; only `trade_mode`, `trade_allowed`, broker `company` and `server` leave it — never login, name, balance or equity | `test_account_info_confined_to_gateway` |
| Credentials never exposed | Optional `SecretStr` settings from `.env` (git-ignored); `Settings.redacted()` for reports; nothing credential-bearing in any tool response | `test_redacted_never_contains_password` |
| Bounded output | Bars capped (default 5,000), ticks capped (20,000), tick windows ≤ 6 h, rate windows rejected above 2× cap | Code review |
| Annotations honest | All tools `readOnlyHint=True, destructiveHint=False` — true by construction | `test_every_tool_is_annotated_read_only` |
| Transport | stdio only; no network listener | Code review |

## 4. Defence in depth — operator actions (recommended, not enforceable in code)

1. **Log in with the account's investor (read-only) password.** The broker then rejects
   every trade request whatever software is running. `xauusd_status` and
   `ci-ingest status` report `account_trading_permitted`, which is `false` under an
   investor login.
2. **Switch off Algo Trading in the terminal** (toolbar button). The Python API cannot
   send orders while it is off. Reported as `terminal_algo_trading_enabled`.
3. Use a **demo** account for all research sessions. Reported as `account_mode`.

Status on 2026-09-21 (second check): demo ✔, Algo Trading OFF ✔, investor login ✘ (optional).

## 5. Live verification (2026-09-21, Exness-MT5Trial7 demo, terminal build 6182)

- Direct API: connected, XAUUSD spec captured, 30-day M5 snapshot written (5,575 closed bars).
- MCP over real stdio: `xauusd_status` + `xauusd_rates(M5, 500)` —
  `tests/integration/test_mcp_live.py` passed.
