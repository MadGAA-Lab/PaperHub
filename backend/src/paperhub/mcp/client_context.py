"""Outbound per-call headers for MCP client requests (SRS v2.6, Task v2.5-7).

Symmetric to :mod:`paperhub.mcp.server_context` but on the *client* side:
the chat endpoint sets a :class:`ClientHeadersContext` around the LangGraph
paper_search subgraph invocation, and :class:`paperhub.mcp.client.MCPClient`
reads it inside ``_open_session`` to populate the
``X-Paperhub-Session-Id`` / ``X-Paperhub-Run-Id`` HTTP headers that the
FastMCP middleware (:class:`PaperhubPapersRequestContextMiddleware`)
requires on every ``POST /mcp`` request.

**Why ContextVar and not an explicit parameter:**

* Threading ``extra_headers: dict[str, str]`` through
  :meth:`MCPRegistry.call` and every agent call site touches a lot of code
  for what is fundamentally request-scoped state.
* A ``headers_provider`` callback on :class:`MCPClient` has to be wired at
  registry-startup time — *before* the chat endpoint knows the
  ``session_id`` — so it can't see the live request.
* ContextVars compose with ``asyncio.gather`` cleanly (each ``Task``
  inherits a copy of its parent's context), don't widen the registry
  surface, and the symmetric inbound shape already exists.

**Difference from `server_context`:** the server side raises
:class:`LookupError` for unset context because a missing inbound header
is a misconfiguration the operator should see immediately. The client
side returns ``None`` instead: operator smoke scripts (``smoke_chat.ps1``)
and standalone agent tests construct an :class:`MCPClient` directly
without a chat request scope, and we want those paths to keep working
with no extra headers attached.
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass

__all__ = [
    "ClientHeadersContext",
    "current_client_headers_context",
    "reset_client_headers_context",
    "set_client_headers_context",
]


@dataclass(frozen=True)
class ClientHeadersContext:
    """Per-request session / run identity for outbound MCP HTTP headers.

    Frozen so concurrent reads inside one chat request (the agent may fan
    out tool calls via ``asyncio.gather``) can't see partial mutation.

    Fields:
        session_id: the chat session that owns this request scope — emitted
            as ``X-Paperhub-Session-Id`` on every outbound MCP call.
        run_id: the run inside that session, if one has been allocated by
            the chat endpoint. ``None`` is valid and means "don't send the
            ``X-Paperhub-Run-Id`` header" — the FastMCP middleware then
            auto-creates a fresh runs row, which is acceptable but loses
            the link back to the parent run.
    """

    session_id: int
    run_id: int | None


_CLIENT_HEADERS_CONTEXT: ContextVar[ClientHeadersContext | None] = ContextVar(
    "paperhub_mcp_client_headers_context",
    default=None,
)


def set_client_headers_context(
    ctx: ClientHeadersContext,
) -> Token[ClientHeadersContext | None]:
    """Set the per-request client headers context.

    Returns a :class:`Token` the caller must pass back to
    :func:`reset_client_headers_context` (typically in a ``finally`` block)
    so the contextvar doesn't leak across requests sharing the same task.
    """
    return _CLIENT_HEADERS_CONTEXT.set(ctx)


def reset_client_headers_context(
    token: Token[ClientHeadersContext | None],
) -> None:
    """Clear the client headers context. Counterpart to
    :func:`set_client_headers_context`."""
    _CLIENT_HEADERS_CONTEXT.reset(token)


def current_client_headers_context() -> ClientHeadersContext | None:
    """Return the active client headers context, or ``None`` if unset.

    Unlike :func:`paperhub.mcp.server_context.current_request_context`,
    this does NOT raise on missing context — operator smoke scripts and
    standalone agent tests legitimately call :class:`MCPClient` without
    a chat request scope, and ``None`` means "send no extra headers".
    """
    return _CLIENT_HEADERS_CONTEXT.get()
