"""AI Assistant API mode: what is sent, what is refused, and how a proposal is validated.
The model is mocked — tests never call the network."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from candle_intel.assistant import chat

SPEC_TEXT = """Yeh idea try karo:
```json
{"meta": {"name": "Sweep reclaim", "family": "sweep-idea", "created_by": "owner"},
 "entries": [{"side": "long", "conditions": [{"feature": "sweep_low", "op": "==", "value": true}]}],
 "exit": {"stop_atr": 1.5, "target_atr": 2.5, "time_exit_bars": 36}}
```"""


def test_proposal_is_validated_and_marked_as_assistant() -> None:
    p = chat.extract_spec(SPEC_TEXT)
    assert p["valid"] and len(p["spec_hash"]) == 16
    assert p["spec"]["meta"]["created_by"] == "assistant"
    bad = chat.extract_spec(SPEC_TEXT.replace("sweep_low", "no_such_feature"))
    assert bad["valid"] is False and bad["errors"]
    assert chat.extract_spec("no json here") is None


def test_tier_c_is_never_sent() -> None:
    with pytest.raises(chat.AssistantError):
        chat.summarise_run({"tier": "C", "results": {}})
    s = chat.summarise_run({"tier": "AB", "holdout_run": "bt_x", "results": {"pessimistic": {"equity": [1]}}})
    assert s["holdout_run"] == "withheld" and "equity" not in s["results"]["pessimistic"]


def test_messages_start_with_the_user_and_carry_context() -> None:
    msgs = chat.build_messages(
        [
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
        ],
        "q2",
        {"result": {"n": 5}},
    )
    assert msgs[0] == {"role": "user", "content": "q1"} and msgs[-1]["role"] == "user"
    assert '<context source="engine">' in msgs[-1]["content"]


def test_system_prompt_lists_every_conditionable_feature() -> None:
    sp = chat.system_prompt()
    assert "sweep_low [bool]" in sp and "Tier C" in sp and "hyg_no_entry [" not in sp


def test_ask_uses_the_router_and_returns_the_proposal(monkeypatch) -> None:
    sent = {}

    class Msgs:
        def create(self, **kw):
            sent.update(kw)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=SPEC_TEXT)],
                model=kw["model"],
                stop_reason="end_turn",
                usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0),
            )

    monkeypatch.setattr(chat, "_client", lambda: SimpleNamespace(messages=Msgs()))
    out = chat.ask("idea do", [], {"strategy_spec": {"x": 1}})
    assert out["proposal"]["valid"] and sent["model"]
    assert sent["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "api_key" not in str(sent["messages"]).lower()


def test_status_never_reveals_the_key(monkeypatch) -> None:
    from pydantic import SecretStr

    from candle_intel.config import Settings

    s = Settings(
        _env_file=None, llm_base_url="https://agentrouter.org", llm_api_key=SecretStr("sk-secret-123")
    )
    monkeypatch.setattr(chat, "get_settings", lambda: s)
    st = chat.status()
    assert st["configured"] and st["base_url_host"] == "agentrouter.org"
    assert "sk-secret" not in str(st)
