from typing import Any

import litellm
import pytest

from paperhub.llm.adapter import LlmAdapter
from paperhub.llm.litellm_adapter import (
    LiteLlmAdapter,
    _extract_json_object,
)
from paperhub.llm.prompts.registry import PromptRegistry
from paperhub.models.domain import RoutingDecision

_VALID_DECISION = (
    '{"intent":"paper_search","model_tier":"small",'
    '"confidence":0.9,"reasoning":"asks to find papers"}'
)


class _FakeAcompletion:
    """Spy that records call kwargs and emulates a provider that rejects a
    Pydantic ``response_format`` (json_schema) but accepts json_object mode."""

    def __init__(self, content: str, *, reject_schema: bool = False) -> None:
        self.content = content
        self.reject_schema = reject_schema
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        rf = kwargs.get("response_format")
        # A Pydantic class (not a dict) is the json_schema request.
        if self.reject_schema and rf is not None and not isinstance(rf, dict):
            raise litellm.BadRequestError(
                message="json_schema not supported",
                model=kwargs.get("model", ""),
                llm_provider="deepseek",
            )
        return {"choices": [{"message": {"content": self.content}}]}


async def test_registry_loads_versioned_slot() -> None:
    reg = PromptRegistry()
    slot = reg.get("router/v1")
    assert slot.system.strip().startswith("You are PaperHub's intent router")
    assert "{user_message}" in slot.user_template


async def test_structured_output_parses_into_model() -> None:
    adapter: LlmAdapter = LiteLlmAdapter()
    decision = await adapter.structured(
        slot="router/v1",
        variables={"user_message": "Find recent papers on MoE routing",
                   "enabled_refs_count": 0, "slide_attached": False},
        response_model=RoutingDecision,
        model="gpt-4o-mini",
        mock_response='{"intent":"paper_search","model_tier":"small",'
                      '"confidence":0.91,"reasoning":"asks to find papers"}',
    )
    assert decision.intent == "paper_search"
    assert 0 <= decision.confidence <= 1


async def test_stream_yields_tokens() -> None:
    adapter: LlmAdapter = LiteLlmAdapter()
    chunks: list[str] = []
    async for token in adapter.stream(
        slot="chitchat/v1",
        variables={
            "user_message": "hi",
            "response_language": "English",
            "memory_context": "",
        },
        model="gpt-4o-mini",
        mock_response="Hello there!",
    ):
        chunks.append(token)
    assert "".join(chunks) == "Hello there!"


def _chunk(content: str) -> dict[str, Any]:
    return {"choices": [{"delta": {"content": content}}]}


async def _no_sleep(_seconds: float) -> None:
    """Skip the retry backoff in tests."""
    return None


_CHITCHAT_VARS = {"user_message": "hi", "response_language": "English", "memory_context": ""}


async def test_stream_emits_tokens_live_not_buffered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Streaming must reach the caller token-by-token, not buffered and flushed
    all-at-once at end-of-stream (the 'instant message, no streaming' bug).

    Detection: a fake upstream records each chunk as it is produced. After the
    caller pulls only the FIRST token, a live adapter has pulled exactly one
    chunk from upstream; a buffering adapter has already drained all of them.
    """
    produced: list[str] = []

    async def fake_acompletion(**kwargs: Any):  # noqa: ANN003
        async def gen():
            for c in ["A", "B", "C"]:
                produced.append(c)
                yield _chunk(c)
        return gen()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    adapter = LiteLlmAdapter()
    agen = adapter.stream(slot="chitchat/v1", variables=_CHITCHAT_VARS, model="gpt-4o-mini")
    first = await agen.__anext__()
    assert first == "A"
    assert produced == ["A"], (
        f"adapter buffered the whole stream before yielding the first token: {produced}"
    )
    rest = [t async for t in agen]
    assert "".join([first, *rest]) == "ABC"


async def test_stream_retries_transient_error_before_first_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resilience preserved: a transient failure BEFORE any token reaches the
    caller is still retried from scratch (restart is safe — nothing emitted)."""
    attempts = {"n": 0}

    async def fake_acompletion(**kwargs: Any):  # noqa: ANN003
        attempts["n"] += 1

        async def gen():
            if attempts["n"] == 1:
                raise litellm.APIConnectionError(
                    message="Connection error.", model="gpt-4o-mini", llm_provider="openai",
                )
                yield  # pragma: no cover - unreachable, makes gen an async generator
            for c in ["X", "Y"]:
                yield _chunk(c)
        return gen()

    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    adapter = LiteLlmAdapter()
    out = [t async for t in adapter.stream(
        slot="chitchat/v1", variables=_CHITCHAT_VARS, model="gpt-4o-mini",
    )]
    assert "".join(out) == "XY"
    assert attempts["n"] == 2, "transient pre-token error should have retried once"


async def test_structured_uses_json_mode_when_no_native_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #4: a provider without json_schema support is driven via json_object
    mode with the schema injected into the prompt, then validated client-side."""
    fake = _FakeAcompletion(_VALID_DECISION)
    monkeypatch.setattr(litellm, "supports_response_schema", lambda model: False)
    monkeypatch.setattr(litellm, "acompletion", fake)

    adapter: LlmAdapter = LiteLlmAdapter()
    decision = await adapter.structured(
        slot="router/v1",
        variables={"user_message": "find papers on MoE", "enabled_refs_count": 0,
                   "slide_attached": False},
        response_model=RoutingDecision,
        model="deepseek/deepseek-v4-flash",
    )

    assert decision.intent == "paper_search"
    assert len(fake.calls) == 1
    call = fake.calls[0]
    # json_object mode, NOT a Pydantic class.
    assert call["response_format"] == {"type": "json_object"}
    # The JSON Schema was appended to the final (user) message.
    last_msg = call["messages"][-1]
    assert last_msg["role"] == "user"
    assert "JSON Schema" in last_msg["content"]
    assert '"intent"' in last_msg["content"]


async def test_structured_falls_back_when_native_schema_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #4: even when the registry CLAIMS json_schema support, a provider
    that rejects it at request time falls back to json_object mode."""
    fake = _FakeAcompletion(_VALID_DECISION, reject_schema=True)
    monkeypatch.setattr(litellm, "supports_response_schema", lambda model: True)
    monkeypatch.setattr(litellm, "acompletion", fake)

    adapter: LlmAdapter = LiteLlmAdapter()
    decision = await adapter.structured(
        slot="router/v1",
        variables={"user_message": "find papers on MoE", "enabled_refs_count": 0,
                   "slide_attached": False},
        response_model=RoutingDecision,
        model="deepseek/deepseek-chat",
    )

    assert decision.intent == "paper_search"
    # Two calls: the rejected native attempt, then the json_object fallback.
    assert len(fake.calls) == 2
    assert fake.calls[0]["response_format"] is RoutingDecision
    assert fake.calls[1]["response_format"] == {"type": "json_object"}


def test_extract_json_object_strips_fences_and_prose() -> None:
    assert _extract_json_object('{"a":1}') == '{"a":1}'
    assert _extract_json_object('```json\n{"a":1}\n```') == '{"a":1}'
    assert _extract_json_object('```\n{"a":1}\n```') == '{"a":1}'
    assert _extract_json_object('Here you go: {"a":1} done.') == '{"a":1}'


async def test_structured_with_history_builds_correct_messages() -> None:
    """structured() with history produces a messages array of len 2 + len(history)."""
    history = [
        {"role": "user", "content": "1+1=?"},
        {"role": "assistant", "content": "1+1 is 2!"},
    ]
    adapter = LiteLlmAdapter()
    # Capture the messages that would be sent by patching _messages
    captured: list[list[dict[str, str]]] = []
    original_messages = adapter._messages  # noqa: SLF001

    def patched_messages(
        slot: str,
        variables: dict,
        hist: list | None = None,
    ) -> list[dict[str, str]]:
        result = original_messages(slot, variables, hist)
        captured.append(result)
        return result

    adapter._messages = patched_messages  # type: ignore[method-assign]  # noqa: SLF001

    await adapter.structured(
        slot="router/v1",
        variables={"user_message": "So what did I ask?", "enabled_refs_count": 0,
                   "slide_attached": False},
        response_model=RoutingDecision,
        model="gpt-4o-mini",
        history=history,
        mock_response='{"intent":"chitchat","model_tier":"small",'
                      '"confidence":0.9,"reasoning":"follow-up"}',
    )

    assert len(captured) == 1
    messages = captured[0]
    # system + 2 history turns + user = 4
    assert len(messages) == 2 + len(history)
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "1+1=?"
    assert messages[2]["role"] == "assistant"
    assert messages[3]["role"] == "user"
