"""MCP client error hierarchy (SRS v2.5, §III-6.1).

Two surface types so callers (the Research Agent dispatch path) can
distinguish *we couldn't reach the server* — fall back to the in-process
palette — from *the server reached us, but the tool itself errored* —
surface the message to the LLM and let it choose another tool.
"""
from __future__ import annotations


class MCPError(Exception):
    """Base class for everything raised by `paperhub.mcp`."""


class MCPUnavailableError(MCPError):
    """Transport / connection failure.

    Raised when the MCP server is unreachable, when initialization fails,
    when the streamable-HTTP transport raises, or when a per-call timeout
    fires. Reconnect-with-backoff has already been exhausted by the time
    this is raised.
    """


class MCPToolError(MCPError):
    """Upstream tool returned an error in its `CallToolResult` (`isError=True`),
    or the caller asked for a tool that the server does not expose.

    Distinct from `MCPUnavailableError` because the connection is healthy —
    the tool itself failed. The dispatcher should surface this to the LLM
    as a normal `{"error": "..."}` tool result.
    """
