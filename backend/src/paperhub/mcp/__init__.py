"""MCP client layer (SRS v2.5, §III-6.1).

Per-server connectors over the official Anthropic ``mcp`` Python SDK.
Plan C v2.5 ships ``open-webSearch`` as the first consumer; Plan E
(sqlite MCP) and Plan G (filesystem + ``paperhub.*`` MCP) reuse this
layer unchanged by adding ``[[server]]`` blocks to ``mcp_servers.toml``.

`MCPRegistry` is provided by `paperhub.mcp.registry` (Task v2.5-2) and
re-exported here once that module lands.
"""
from __future__ import annotations

from .client import MCPClient
from .config import MCPServerConfig, load_mcp_servers
from .errors import MCPError, MCPToolError, MCPUnavailableError

__all__ = [
    "MCPClient",
    "MCPError",
    "MCPServerConfig",
    "MCPToolError",
    "MCPUnavailableError",
    "load_mcp_servers",
]
