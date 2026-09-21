"""AI Assistant, API mode (owner decision 2026-09-21: hybrid assistant).

The dashboard chat sends the owner's question to a Claude model through the owner's
AgentRouter key (``.env``: ``CI_LLM_*``; AgentRouter speaks the Anthropic Messages API,
so the official ``anthropic`` SDK is used with its ``base_url``).

What is sent: the question, the recent chat turns, the feature catalogue, and — when the
owner attaches one — a strategy spec or a tier A / B result summary. What is never sent:
keys or credentials, account data, tier C (holdout) results, raw price files.

What comes back is text. If the model proposes a strategy it writes one JSON block; the
engine validates it as a ``strategy-spec/1`` (``created_by = "assistant"``) and the UI
offers "Open in Visual Builder". Nothing is saved, run or counted until the owner does
it — the assistant only proposes (MASTER_PROMPT §5).
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from candle_intel.config import get_settings
from candle_intel.strategy.spec import StrategySpec, catalogue

MAX_TURNS = 12
MAX_TURN_CHARS = 8000
MAX_CONTEXT_CHARS = 30_000
MAX_TOKENS = 16000

RULES = """\
You are the research assistant inside Candle Intelligence, a local XAUUSD-only (spot gold)
strategy research workbench. The owner writes Hinglish; answer in simple Hinglish with
technical terms in English, short sentences, like to a smart beginner.

Hard rules:
- Never invent or estimate a number. Only quote numbers that appear in the context you are
  given (they come from the engine). If you do not have a number, say which page or run
  would produce it.
- The platform does research and paper trading only. Never give personal financial advice
  or tell the owner to trade real money.
- Tier C (the newest ~20 % of data) is sealed; you never see it. Every backtest counts as a
  trial and raises the bar (Deflated Sharpe). Costs are always on; only pessimistic costs
  can promote a strategy. Most ideas fail — saying so honestly is useful.
- You only propose. The owner reviews, saves and runs.

When you propose a strategy, write exactly one fenced ```json block holding a complete
strategy-spec/1 object:
{"meta": {"name": "...", "family": "lowercase-slug", "hypothesis": "...", "created_by": "assistant"},
 "entries": [{"side": "long"|"short", "conditions": [{"feature": "<name>", "op": ">|>=|<|<=|==|!=|between|in|not_in", "value": ...}]}],
 "filters": {"sessions": [...]|null, "vol_regimes": [...]|null, "hours_utc": [...]|null, "weekdays": [...]|null, "max_spread_rel": number|null},
 "exit": {"stop_atr": number, "target_atr": number|null, "time_exit_bars": int|null, "trail_atr": number|null, "flat_before_weekend": true},
 "sizing": {"risk_pct": 1, "initial_equity_usd": 10000}}
Conditions are checked at the close of each M5 bar; entries fill at the next M1 open.
Distances are multiples of ATR(14). Use only the feature names listed below.
"""


def system_prompt() -> str:
    cat = catalogue()
    lines = [f"{f['name']} [{f['unit']}] — {f['description']}" for f in cat["features"]]
    return (
        RULES
        + f"\nSessions: {', '.join(cat['sessions'])}. Volatility regimes: {', '.join(cat['vol_regimes'])}. "
        + f"Always enforced: {cat['always_on']}.\n\nFeatures ({len(lines)}):\n"
        + "\n".join(lines)
    )


class AssistantError(RuntimeError):
    pass


def status() -> dict[str, Any]:
    s = get_settings()
    key = s.llm_api_key.get_secret_value() if s.llm_api_key else ""
    return {
        "configured": bool(key and s.llm_base_url),
        "provider": s.llm_provider,
        "base_url_host": re.sub(r"^https?://", "", s.llm_base_url or "").split("/")[0] or None,
        "model": s.llm_model,
        "fast_model": s.llm_fast_model,
    }


def _client():
    import anthropic

    s = get_settings()
    key = s.llm_api_key.get_secret_value() if s.llm_api_key else ""
    if not key or not s.llm_base_url:
        raise AssistantError("API mode is not configured (CI_LLM_BASE_URL / CI_LLM_API_KEY in .env)")
    return anthropic.Anthropic(api_key=key, base_url=s.llm_base_url, timeout=180.0, max_retries=2)


def summarise_run(run: dict[str, Any]) -> dict[str, Any]:
    """A result the model may read: tier A / B only, heavy series removed."""
    if run.get("tier") == "C":
        raise AssistantError("tier C (holdout) results are never sent to the assistant")
    drop = {"equity", "markers", "by_month", "spec_hash_history"}
    out = {k: v for k, v in run.items() if k not in drop}
    for s in (out.get("results") or {}).values():
        if isinstance(s, dict):
            for k in ("equity", "by_month"):
                s.pop(k, None)
    if "holdout_run" in out:
        out["holdout_run"] = "withheld"
    return out


def extract_spec(text: str) -> dict[str, Any] | None:
    """The first fenced JSON block that looks like a spec, validated by the engine."""
    for block in re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL):
        try:
            raw = json.loads(block)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict) or "entries" not in raw:
            continue
        raw.setdefault("meta", {})["created_by"] = "assistant"
        try:
            spec = StrategySpec.model_validate(raw)
        except ValidationError as e:
            return {
                "spec": raw,
                "valid": False,
                "errors": [{"loc": ".".join(map(str, er["loc"])), "msg": er["msg"]} for er in e.errors()],
            }
        return {
            "spec": spec.model_dump(mode="json"),
            "valid": True,
            "spec_hash": spec.spec_hash,
            "errors": [],
        }
    return None


def build_messages(
    history: list[dict[str, str]], question: str, context: dict[str, Any] | None
) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = []
    for h in history[-MAX_TURNS:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": str(h["content"])[:MAX_TURN_CHARS]})
    while msgs and msgs[0]["role"] != "user":  # the first message must be the user's
        msgs.pop(0)
    text = question.strip()
    if context:
        blob = json.dumps(context, default=str)[:MAX_CONTEXT_CHARS]
        text += f'\n\n<context source="engine">\n{blob}\n</context>'
    msgs.append({"role": "user", "content": text})
    return msgs


def ask(
    question: str,
    history: list[dict[str, str]] | None = None,
    context: dict[str, Any] | None = None,
    fast: bool = False,
) -> dict[str, Any]:
    import anthropic

    s = get_settings()
    model = (s.llm_fast_model if fast and s.llm_fast_model else s.llm_model) or "claude-opus-5"
    client = _client()
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}],
            messages=build_messages(history or [], question, context),
        )
    except anthropic.AuthenticationError as e:
        raise AssistantError("the router rejected the API key (CI_LLM_API_KEY)") from e
    except anthropic.RateLimitError as e:
        raise AssistantError("rate limited by the router — try again in a minute") from e
    except anthropic.APIStatusError as e:
        if e.status_code == 402:
            raise AssistantError(
                "AgentRouter says the budget / quota is exhausted (402) — top it up, then ask again"
            ) from e
        raise AssistantError(f"router error {e.status_code}: {str(e.message)[:300]}") from e
    except anthropic.APIConnectionError as e:
        raise AssistantError(f"cannot reach {s.llm_base_url}: {e}") from e
    if resp.stop_reason == "refusal":
        return {
            "reply": "The model declined this request.",
            "proposal": None,
            "model": resp.model,
            "usage": None,
        }
    text = "\n".join(b.text for b in resp.content if b.type == "text").strip()
    usage = getattr(resp, "usage", None)
    return {
        "reply": text,
        "proposal": extract_spec(text),
        "model": resp.model,
        "stop_reason": resp.stop_reason,
        "usage": {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
        }
        if usage
        else None,
    }
