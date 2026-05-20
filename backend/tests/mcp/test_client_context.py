"""Tests for `paperhub.mcp.client_context` — the outbound-headers contextvar
that mirrors the inbound `server_context.py` pattern.

The chat endpoint sets this contextvar around the LangGraph agent invocation
so that any downstream `MCPClient.call_tool` reads the live `session_id` /
`run_id` and forwards them as `X-Paperhub-Session-Id` / `X-Paperhub-Run-Id`
headers on the streamable-HTTP POST.

Coverage:
  * frozen dataclass shape;
  * set / reset / get round-trip;
  * `current_client_headers_context` returns ``None`` when unset (not raises
    — symmetric to the server-side `LookupError`, but the client path
    needs an inline "no extra headers" branch, so we expose ``None``);
  * contextvar isolation across concurrent `asyncio.gather` tasks
    (default Python copies the context per task — set in child must not
    leak into sibling).
"""
from __future__ import annotations

import asyncio
import dataclasses

import pytest

from paperhub.mcp.client_context import (
    ClientHeadersContext,
    current_client_headers_context,
    reset_client_headers_context,
    set_client_headers_context,
)


def test_client_headers_context_is_frozen_dataclass() -> None:
    """The context must be a frozen dataclass — concurrent reads must not
    see partial mutation."""
    ctx = ClientHeadersContext(session_id=42, run_id=99)
    assert dataclasses.is_dataclass(ctx)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.session_id = 7  # type: ignore[misc]


def test_client_headers_context_allows_none_run_id() -> None:
    """run_id is optional — chat endpoints may not have one allocated yet."""
    ctx = ClientHeadersContext(session_id=42, run_id=None)
    assert ctx.run_id is None


def test_current_returns_none_when_unset() -> None:
    """No leaked context from another test, and the unset case is
    explicitly representable as ``None`` (not a raised LookupError)."""
    assert current_client_headers_context() is None


def test_set_reset_round_trip() -> None:
    ctx = ClientHeadersContext(session_id=5, run_id=7)
    token = set_client_headers_context(ctx)
    try:
        got = current_client_headers_context()
        assert got is ctx
        assert got is not None
        assert got.session_id == 5
        assert got.run_id == 7
    finally:
        reset_client_headers_context(token)
    assert current_client_headers_context() is None


@pytest.mark.asyncio
async def test_contextvar_isolated_across_concurrent_tasks() -> None:
    """Two `asyncio.gather` siblings must observe their own context — a
    child setting the var must not leak into the sibling. Python's default
    `Task` constructor copies the running context; this is what makes
    contextvars composable with the chat endpoint's stream handler."""
    observed: dict[str, ClientHeadersContext | None] = {}

    async def runner(name: str, ctx: ClientHeadersContext) -> None:
        token = set_client_headers_context(ctx)
        try:
            await asyncio.sleep(0.01)  # yield so the other task interleaves
            observed[name] = current_client_headers_context()
        finally:
            reset_client_headers_context(token)

    a = ClientHeadersContext(session_id=1, run_id=10)
    b = ClientHeadersContext(session_id=2, run_id=20)
    await asyncio.gather(runner("a", a), runner("b", b))

    assert observed["a"] is a
    assert observed["b"] is b
    # Outer scope is unaffected.
    assert current_client_headers_context() is None
