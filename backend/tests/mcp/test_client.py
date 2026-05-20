"""Tests for `paperhub.mcp.client.MCPClient`."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest

from paperhub.mcp.client import MCPClient
from paperhub.mcp.config import MCPServerConfig
from paperhub.mcp.errors import MCPToolError, MCPUnavailableError

pytestmark = pytest.mark.asyncio


# --- fake mcp SDK plumbing ---------------------------------------------------


class _FakeTool:
    def __init__(self, name: str, description: str, input_schema: dict[str, Any]) -> None:
        self.name = name
        self.description = description
        self.inputSchema = input_schema  # noqa: N815 — matches SDK shape


class _FakeListToolsResult:
    def __init__(self, tools: list[_FakeTool]) -> None:
        self.tools = tools


class _FakeContentBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeCallToolResult:
    def __init__(
        self,
        *,
        content: list[_FakeContentBlock] | None = None,
        structured: dict[str, Any] | None = None,
        is_error: bool = False,
    ) -> None:
        self.content = content or []
        self.structuredContent = structured  # noqa: N815
        self.isError = is_error  # noqa: N815


class _FakeSession:
    def __init__(
        self,
        *,
        tools: list[_FakeTool] | None = None,
        call_result: _FakeCallToolResult | None = None,
        call_exc: BaseException | None = None,
        call_delay: float = 0.0,
    ) -> None:
        self._tools = tools or []
        self._call_result = call_result
        self._call_exc = call_exc
        self._call_delay = call_delay
        self.initialize_called = 0
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def initialize(self) -> None:
        self.initialize_called += 1

    async def list_tools(self) -> _FakeListToolsResult:
        return _FakeListToolsResult(self._tools)

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        **_: Any,
    ) -> _FakeCallToolResult:
        self.calls.append((name, arguments or {}))
        if self._call_delay:
            await asyncio.sleep(self._call_delay)
        if self._call_exc is not None:
            raise self._call_exc
        assert self._call_result is not None
        return self._call_result


def _make_streamable_factory(
    session: _FakeSession,
    *,
    transport_exc: BaseException | None = None,
) -> Any:
    """Build a stub for `streamablehttp_client(url, ...)` as an async ctx manager."""

    @asynccontextmanager
    async def _factory(url: str, **_: Any) -> Any:
        if transport_exc is not None:
            raise transport_exc
        # The real SDK yields (read, write, get_session_id_cb).
        yield (MagicMock(), MagicMock(), lambda: None)

    return _factory


def _patch_client(
    monkeypatch: pytest.MonkeyPatch,
    session: _FakeSession,
    *,
    transport_exc: BaseException | None = None,
    session_factory_calls: list[int] | None = None,
) -> None:
    """Patch `streamablehttp_client` + `ClientSession` inside the client module."""
    from paperhub.mcp import client as client_mod

    factory = _make_streamable_factory(session, transport_exc=transport_exc)
    monkeypatch.setattr(client_mod, "streamablehttp_client", factory)

    def _session_ctor(read: Any, write: Any, *args: Any, **kwargs: Any) -> _FakeSession:
        if session_factory_calls is not None:
            session_factory_calls.append(1)
        return session

    monkeypatch.setattr(client_mod, "ClientSession", _session_ctor)


# --- tests -------------------------------------------------------------------


def _cfg(**overrides: Any) -> MCPServerConfig:
    defaults: dict[str, Any] = dict(
        name="web",
        transport="streamable_http",
        url="http://localhost:3000/mcp",
        expose=["search", "fetchWebContent"],
        aliases={"fetchWebContent": "fetch"},
        timeout_seconds=5.0,
    )
    defaults.update(overrides)
    return MCPServerConfig(**defaults)


async def test_connect_then_list_tools_returns_litellm_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(
        tools=[
            _FakeTool(
                "search",
                "multi-engine web search",
                {"type": "object", "properties": {"q": {"type": "string"}}},
            ),
            _FakeTool(
                "fetchWebContent",
                "fetch a URL",
                {"type": "object", "properties": {"url": {"type": "string"}}},
            ),
        ],
    )
    _patch_client(monkeypatch, session)

    client = MCPClient(_cfg())
    await client.connect()
    schemas = await client.list_tools()

    assert session.initialize_called == 1
    assert len(schemas) == 2
    by_name = {s["function"]["name"]: s for s in schemas}
    assert "web.search" in by_name
    # alias applied: upstream "fetchWebContent" -> "fetch" -> namespaced "web.fetch"
    assert "web.fetch" in by_name
    # LiteLLM shape
    s = by_name["web.search"]
    assert s["type"] == "function"
    assert s["function"]["description"] == "multi-engine web search"
    assert s["function"]["parameters"] == {
        "type": "object",
        "properties": {"q": {"type": "string"}},
    }

    await client.disconnect()


async def test_list_tools_drops_non_exposed(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession(
        tools=[
            _FakeTool("search", "ok", {"type": "object"}),
            _FakeTool("secret_admin_tool", "no", {"type": "object"}),
        ],
    )
    _patch_client(monkeypatch, session)
    client = MCPClient(_cfg(expose=["search"], aliases={}))
    await client.connect()
    schemas = await client.list_tools()
    assert [s["function"]["name"] for s in schemas] == ["web.search"]


async def test_connect_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession(tools=[_FakeTool("search", "", {"type": "object"})])
    calls: list[int] = []
    _patch_client(monkeypatch, session, session_factory_calls=calls)
    client = MCPClient(_cfg())

    await client.connect()
    await client.connect()
    await client.connect()

    # Underlying ClientSession constructor invoked exactly once.
    assert len(calls) == 1
    assert session.initialize_called == 1


async def test_call_tool_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession(
        tools=[_FakeTool("search", "", {"type": "object"})],
        call_result=_FakeCallToolResult(
            structured={"hits": [{"title": "foo"}]},
        ),
    )
    _patch_client(monkeypatch, session)
    client = MCPClient(_cfg())
    await client.connect()
    result = await client.call_tool("search", {"q": "diffusion"})

    assert session.calls == [("search", {"q": "diffusion"})]
    assert result == {"hits": [{"title": "foo"}]}


async def test_call_tool_falls_back_to_text_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(
        tools=[_FakeTool("search", "", {"type": "object"})],
        call_result=_FakeCallToolResult(
            content=[_FakeContentBlock("hello"), _FakeContentBlock("world")],
            structured=None,
        ),
    )
    _patch_client(monkeypatch, session)
    client = MCPClient(_cfg())
    await client.connect()
    result = await client.call_tool("search", {"q": "x"})

    # When no structuredContent, returns the joined text.
    assert isinstance(result, str)
    assert "hello" in result and "world" in result


async def test_call_tool_accepts_aliased_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Caller may pass the aliased name; client translates back to upstream."""
    session = _FakeSession(
        tools=[
            _FakeTool("fetchWebContent", "", {"type": "object"}),
        ],
        call_result=_FakeCallToolResult(structured={"ok": True}),
    )
    _patch_client(monkeypatch, session)
    client = MCPClient(_cfg(expose=["fetchWebContent"], aliases={"fetchWebContent": "fetch"}))
    await client.connect()

    # caller passes the aliased name
    await client.call_tool("fetch", {"url": "https://x"})

    # ...but upstream sees the original tool name
    assert session.calls == [("fetchWebContent", {"url": "https://x"})]


async def test_call_tool_unknown_name_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession(
        tools=[_FakeTool("search", "", {"type": "object"})],
        call_result=_FakeCallToolResult(structured={}),
    )
    _patch_client(monkeypatch, session)
    client = MCPClient(_cfg())
    await client.connect()
    with pytest.raises(MCPToolError, match=r"unknown"):
        await client.call_tool("does_not_exist", {})


async def test_call_tool_propagates_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession(
        tools=[_FakeTool("search", "", {"type": "object"})],
        call_result=_FakeCallToolResult(
            content=[_FakeContentBlock("boom")],
            is_error=True,
        ),
    )
    _patch_client(monkeypatch, session)
    client = MCPClient(_cfg())
    await client.connect()
    with pytest.raises(MCPToolError, match=r"boom"):
        await client.call_tool("search", {"q": "x"})


async def test_call_tool_timeout_raises_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(
        tools=[_FakeTool("search", "", {"type": "object"})],
        call_result=_FakeCallToolResult(structured={"ok": True}),
        call_delay=0.5,
    )
    _patch_client(monkeypatch, session)
    client = MCPClient(_cfg(timeout_seconds=0.01))
    await client.connect()
    with pytest.raises(MCPUnavailableError, match=r"timeout|timed out"):
        await client.call_tool("search", {"q": "x"})


async def test_connect_transport_failure_raises_after_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(tools=[])
    _patch_client(
        monkeypatch,
        session,
        transport_exc=ConnectionError("daemon down"),
    )
    # Use zero backoff via a monkeypatched sleep so the test is fast.
    from paperhub.mcp import client as client_mod

    sleep_calls: list[float] = []

    async def _fake_sleep(s: float) -> None:
        sleep_calls.append(s)

    monkeypatch.setattr(client_mod.asyncio, "sleep", _fake_sleep)

    client = MCPClient(_cfg())
    with pytest.raises(MCPUnavailableError, match=r"daemon down|connect"):
        await client.connect()

    # 4 attempts max → 3 backoff sleeps between them.
    assert len(sleep_calls) == 3


async def test_disconnect_after_failed_connect_is_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(tools=[])
    _patch_client(
        monkeypatch,
        session,
        transport_exc=ConnectionError("nope"),
    )
    from paperhub.mcp import client as client_mod

    async def _fake_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(client_mod.asyncio, "sleep", _fake_sleep)

    client = MCPClient(_cfg())
    with pytest.raises(MCPUnavailableError):
        await client.connect()
    # Should not raise.
    await client.disconnect()
