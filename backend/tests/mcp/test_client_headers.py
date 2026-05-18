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


async def test_concurrent_drift_refresh_serializes_under_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent ``call_tool`` invocations on **one shared** `MCPClient`
    (the registry-cached production scenario) with different
    `ClientHeadersContext` values must NOT interleave their
    `_close_stack_silently` + `_open_session` sequences.

    The race the lock prevents:
      1. Task A enters `_refresh_session_headers_if_drifted`, sees drift,
         calls `_close_stack_silently` → stack is None.
      2. Task B enters the same method, sees drift (it's also still
         drifted from `_session_headers`), starts its own close/open.
      3. Task A calls `_open_session`, installs stack_A + session_A.
      4. Task B's `_close_stack_silently` runs **after** A's open and
         tears down stack_A; B then opens stack_B.
      5. Task A's `session.call_tool` runs on session_A whose underlying
         transport (stack_A) was just torn down by B → silent failure.

    Detection: we instrument `_open_session` and `_close_stack_silently`
    so they each record a (task_id, phase) entry. Under serialization we
    see one task's full ``[open, close, open]`` block before the other's;
    under the race we see interleaving like ``[open_A, close_A, open_B,
    close_B (which tears A down!), open_B again]`` — i.e. more than the
    expected number of operations, or an open immediately followed by a
    sibling's close.

    With the lock: exactly 3 operations total (1 initial connect + 1
    close + 1 open for the second context). Without the lock: 5
    operations (1 initial connect + 2 closes + 2 opens — both tasks
    independently refresh).
    """
    from paperhub.mcp import client as client_mod

    # Record (op, task_name) for every transport-level operation on the
    # shared client. We watch the SEQUENCE to detect interleaving.
    ops: list[tuple[str, str]] = []

    @asynccontextmanager
    async def _factory(
        url: str,
        headers: dict[str, str] | None = None,
        **_: Any,
    ) -> Any:
        # Yield to maximize the chance a sibling task interleaves.
        await asyncio.sleep(0)
        yield (MagicMock(), MagicMock(), lambda: None)

    def _session_ctor(read: Any, write: Any, *args: Any, **kwargs: Any) -> _FakeSession:
        return _FakeSession()

    monkeypatch.setattr(client_mod, "streamablehttp_client", _factory)
    monkeypatch.setattr(client_mod, "ClientSession", _session_ctor)

    # Instrument the two transport-level methods to record ordering.
    real_open = client_mod.MCPClient._open_session
    real_close = client_mod.MCPClient._close_stack_silently

    async def _trace_open(self: MCPClient, url: str) -> None:
        task = asyncio.current_task()
        name = task.get_name() if task else "?"
        ops.append(("open_start", name))
        await real_open(self, url)
        ops.append(("open_end", name))

    async def _trace_close(self: MCPClient) -> None:
        task = asyncio.current_task()
        name = task.get_name() if task else "?"
        ops.append(("close_start", name))
        await real_close(self)
        ops.append(("close_end", name))

    monkeypatch.setattr(client_mod.MCPClient, "_open_session", _trace_open)
    monkeypatch.setattr(
        client_mod.MCPClient, "_close_stack_silently", _trace_close,
    )

    # ONE shared client across both tasks — this is the registry scenario.
    client = MCPClient(_cfg())

    # Establish an initial session under a *third* context so both
    # gathered tasks' drift-refresh paths are exercised concurrently.
    # (Without this pre-connect, the two tasks would race inside
    # `connect()` itself, which is a separate concern outside this
    # test's scope — `connect()` is called once at registry startup
    # in production, not from request-handling tasks.)
    bootstrap_token = set_client_headers_context(
        ClientHeadersContext(session_id=999, run_id=None),
    )
    try:
        await client.connect()
    finally:
        reset_client_headers_context(bootstrap_token)

    # Clear the bootstrap trace so we only inspect the concurrent
    # drift-refresh activity.
    ops.clear()

    async def call_with_context(session_id: int) -> None:
        ctx = ClientHeadersContext(session_id=session_id, run_id=None)
        token = set_client_headers_context(ctx)
        try:
            await client.call_tool("search_library", {"query": "x"})
        finally:
            reset_client_headers_context(token)

    t1 = asyncio.create_task(call_with_context(session_id=1), name="task-1")
    t2 = asyncio.create_task(call_with_context(session_id=2), name="task-2")
    await asyncio.gather(t1, t2)
    await client.disconnect()

    # Filter to drift-refresh ops only (skip the disconnect's close at
    # the end and the initial connect's open). Across both tasks we
    # expect: zero, one, or two refreshes — but never an interleaved
    # close from one task between another task's open_start and
    # open_end (or vice versa). The lock guarantees that within a
    # close-open sequence, no sibling task's close or open appears.
    in_progress: dict[str, str] = {}  # task_name -> current op
    for op, name in ops:
        if op.endswith("_start"):
            kind = op[: -len("_start")]
            # No other task can have a transport op in flight when we
            # start one.
            other_in_progress = {n: k for n, k in in_progress.items() if n != name}
            assert not other_in_progress, (
                f"transport op {op} by {name} interleaved with "
                f"{other_in_progress} — drift-refresh race"
            )
            in_progress[name] = kind
        elif op.endswith("_end"):
            kind = op[: -len("_end")]
            assert in_progress.get(name) == kind, (
                f"unbalanced trace: {op} by {name}, in_progress={in_progress}"
            )
            del in_progress[name]

    # Final sanity: both call_tools completed without raising — gather
    # would have re-raised otherwise. And the final state is connected.
    assert client.connected is False  # disconnect ran at the end


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
