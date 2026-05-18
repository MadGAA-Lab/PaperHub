"""Integration test: `MCPClient` forwards the client_headers contextvar to
the outbound HTTP request as `X-Paperhub-Session-Id` / `X-Paperhub-Run-Id`
headers via `streamablehttp_client(url, headers=...)`.

Production-path bug this test guards against: before Task v2.5-7,
`MCPClient` called `streamablehttp_client(url)` with no headers, so the
loopback `papers.*` server's middleware rejected every agent-driven call
with a 400.

The test patches `streamablehttp_client` with a stub that captures the
``headers`` kwarg it was called with — we don't need a real HTTP round-trip
for this check; the end-to-end ASGI loopback proof lives in
`tests/api/test_chat_mcp_loopback.py`.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest

from paperhub.mcp.client import MCPClient
from paperhub.mcp.client_context import (
    ClientHeadersContext,
    reset_client_headers_context,
    set_client_headers_context,
)
from paperhub.mcp.config import MCPServerConfig

pytestmark = pytest.mark.asyncio


# --- reusable stub plumbing (mirrors `test_client.py`) -----------------------


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def initialize(self) -> None:
        return None

    async def list_tools(self) -> Any:  # not used here
        raise NotImplementedError

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        **_: Any,
    ) -> Any:
        # Mimic the structured-content shape MCPClient expects.
        class _Result:
            content = []
            structuredContent = {"name": name, "args": arguments}
            isError = False

        return _Result()


def _patch_streamable(
    monkeypatch: pytest.MonkeyPatch,
    captured: dict[str, Any],
) -> None:
    """Patch `streamablehttp_client` to capture the headers kwarg it
    receives. Returns nothing; mutates ``captured``."""
    from paperhub.mcp import client as client_mod

    @asynccontextmanager
    async def _factory(
        url: str,
        headers: dict[str, str] | None = None,
        **_: Any,
    ) -> Any:
        captured["url"] = url
        captured["headers"] = headers
        yield (MagicMock(), MagicMock(), lambda: None)

    def _session_ctor(read: Any, write: Any, *args: Any, **kwargs: Any) -> _FakeSession:
        return _FakeSession()

    monkeypatch.setattr(client_mod, "streamablehttp_client", _factory)
    monkeypatch.setattr(client_mod, "ClientSession", _session_ctor)


def _cfg() -> MCPServerConfig:
    return MCPServerConfig(
        name="papers",
        transport="streamable_http",
        url="http://localhost:8000/mcp",
        expose=["search_library"],
        aliases={},
        timeout_seconds=5.0,
    )


# --- tests -------------------------------------------------------------------


async def test_call_tool_forwards_session_and_run_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the client_headers contextvar set, `MCPClient.call_tool` must
    pass ``{"X-Paperhub-Session-Id": ..., "X-Paperhub-Run-Id": ...}`` to
    `streamablehttp_client`."""
    captured: dict[str, Any] = {}
    _patch_streamable(monkeypatch, captured)

    client = MCPClient(_cfg())
    token = set_client_headers_context(
        ClientHeadersContext(session_id=42, run_id=99),
    )
    try:
        await client.connect()
        await client.call_tool("search_library", {"query": "x"})
    finally:
        reset_client_headers_context(token)
        await client.disconnect()

    assert captured["url"] == "http://localhost:8000/mcp"
    headers = captured["headers"]
    assert headers is not None
    assert headers.get("X-Paperhub-Session-Id") == "42"
    assert headers.get("X-Paperhub-Run-Id") == "99"


async def test_call_tool_omits_run_id_header_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``run_id`` is None, only the session header is sent — we
    don't want to emit an empty / null run-id that the middleware would
    reject with a 400."""
    captured: dict[str, Any] = {}
    _patch_streamable(monkeypatch, captured)

    client = MCPClient(_cfg())
    token = set_client_headers_context(
        ClientHeadersContext(session_id=42, run_id=None),
    )
    try:
        await client.connect()
        await client.call_tool("search_library", {"query": "x"})
    finally:
        reset_client_headers_context(token)
        await client.disconnect()

    headers = captured["headers"]
    assert headers is not None
    assert headers.get("X-Paperhub-Session-Id") == "42"
    assert "X-Paperhub-Run-Id" not in headers


async def test_call_tool_no_context_sends_no_extra_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The no-context case (operator smoke script, standalone unit tests)
    must continue to work: `streamablehttp_client` is invoked with
    ``headers=None`` and the MCP server applies its own defaults."""
    captured: dict[str, Any] = {}
    _patch_streamable(monkeypatch, captured)

    # No set_client_headers_context here.
    client = MCPClient(_cfg())
    try:
        await client.connect()
        await client.call_tool("search_library", {"query": "x"})
    finally:
        await client.disconnect()

    assert captured["headers"] is None


async def test_call_tool_reconnects_when_contextvar_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single registry-cached :class:`MCPClient` serving two chat
    requests in sequence must re-open its session when the per-request
    contextvar changes — the streamable-HTTP transport binds headers
    at construction time, so reusing the live session would silently
    leak the previous request's session header into the new request.

    This is THE production-path scenario v2.5-7 was opened to fix.
    """
    captures: list[dict[str, str] | None] = []

    from paperhub.mcp import client as client_mod

    @asynccontextmanager
    async def _factory(
        url: str,
        headers: dict[str, str] | None = None,
        **_: Any,
    ) -> Any:
        captures.append(dict(headers) if headers else None)
        yield (MagicMock(), MagicMock(), lambda: None)

    def _session_ctor(read: Any, write: Any, *args: Any, **kwargs: Any) -> _FakeSession:
        return _FakeSession()

    monkeypatch.setattr(client_mod, "streamablehttp_client", _factory)
    monkeypatch.setattr(client_mod, "ClientSession", _session_ctor)

    client = MCPClient(_cfg())

    # First chat request: session 1, run 10.
    token = set_client_headers_context(
        ClientHeadersContext(session_id=1, run_id=10),
    )
    try:
        await client.connect()
        await client.call_tool("search_library", {"query": "x"})
    finally:
        reset_client_headers_context(token)

    # Second chat request: session 2, run 20 — must trigger reconnect.
    token = set_client_headers_context(
        ClientHeadersContext(session_id=2, run_id=20),
    )
    try:
        await client.call_tool("search_library", {"query": "y"})
    finally:
        reset_client_headers_context(token)
        await client.disconnect()

    # Two distinct `streamablehttp_client` invocations: once at the
    # initial connect, once when call_tool noticed the drift.
    assert len(captures) == 2, captures
    assert captures[0] == {
        "X-Paperhub-Session-Id": "1",
        "X-Paperhub-Run-Id": "10",
    }
    assert captures[1] == {
        "X-Paperhub-Session-Id": "2",
        "X-Paperhub-Run-Id": "20",
    }


async def test_call_tool_does_not_reconnect_within_same_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two ``call_tool`` invocations under the same
    :class:`ClientHeadersContext` reuse the live session — we don't want
    to pay reconnect cost on every tool call in a single agent turn.
    """
    captures: list[dict[str, str] | None] = []

    from paperhub.mcp import client as client_mod

    @asynccontextmanager
    async def _factory(
        url: str,
        headers: dict[str, str] | None = None,
        **_: Any,
    ) -> Any:
        captures.append(dict(headers) if headers else None)
        yield (MagicMock(), MagicMock(), lambda: None)

    def _session_ctor(read: Any, write: Any, *args: Any, **kwargs: Any) -> _FakeSession:
        return _FakeSession()

    monkeypatch.setattr(client_mod, "streamablehttp_client", _factory)
    monkeypatch.setattr(client_mod, "ClientSession", _session_ctor)

    client = MCPClient(_cfg())

    token = set_client_headers_context(
        ClientHeadersContext(session_id=42, run_id=99),
    )
    try:
        await client.connect()
        await client.call_tool("search_library", {"query": "a"})
        await client.call_tool("search_library", {"query": "b"})
        await client.call_tool("search_library", {"query": "c"})
    finally:
        reset_client_headers_context(token)
        await client.disconnect()

    # Exactly one connect — the three call_tools reused it.
    assert len(captures) == 1, captures


async def test_concurrent_clients_see_isolated_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two `asyncio.gather` siblings, each setting a different
    `ClientHeadersContext`, must each see their own headers on the
    outbound POST. Proves the contextvar composes with the asyncio
    task scheduler — critical for the chat endpoint, which serves
    multiple concurrent requests on one process."""

    # We need to capture per-task; the stub overwrites a single dict, so
    # serialize the captures via a list + barrier.
    captures: list[dict[str, Any]] = []
    barrier = asyncio.Event()

    from paperhub.mcp import client as client_mod

    @asynccontextmanager
    async def _factory(
        url: str,
        headers: dict[str, str] | None = None,
        **_: Any,
    ) -> Any:
        captures.append({"headers": dict(headers) if headers else None})
        yield (MagicMock(), MagicMock(), lambda: None)

    def _session_ctor(read: Any, write: Any, *args: Any, **kwargs: Any) -> _FakeSession:
        return _FakeSession()

    monkeypatch.setattr(client_mod, "streamablehttp_client", _factory)
    monkeypatch.setattr(client_mod, "ClientSession", _session_ctor)

    async def runner(session_id: int, run_id: int) -> None:
        client = MCPClient(_cfg())
        token = set_client_headers_context(
            ClientHeadersContext(session_id=session_id, run_id=run_id),
        )
        try:
            await client.connect()
            await asyncio.sleep(0)  # yield to sibling
            await client.call_tool("search_library", {"query": "x"})
        finally:
            reset_client_headers_context(token)
            await client.disconnect()

    barrier.set()
    await asyncio.gather(runner(1, 10), runner(2, 20))

    headers_seen = sorted(
        (c["headers"]["X-Paperhub-Session-Id"], c["headers"]["X-Paperhub-Run-Id"])
        for c in captures
    )
    assert headers_seen == [("1", "10"), ("2", "20")]
