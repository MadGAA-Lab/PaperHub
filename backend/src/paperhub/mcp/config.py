"""MCP server config dataclass + TOML loader (SRS v2.5, §III-6 / §III-6.1).

`mcp_servers.toml` is the operator-edited list of MCP servers the registry
should connect to at FastAPI startup. Each `[[server]]` block becomes one
`MCPServerConfig`, which is consumed by `MCPClient` (Task v2.5-1) and the
`MCPRegistry` (Task v2.5-2).

Schema (see `mcp_servers.toml.example`):

    [[server]]
    name = "web"                   # namespace prefix → "web.search"
    transport = "streamable_http"  # or "stdio" (dispatch not yet wired)
    url = "http://localhost:3000/mcp"   # streamable_http only
    command = "npx"                # stdio only
    args = ["-y", "pkg", "..."]    # stdio only
    expose = ["search", "fetchWebContent"]
    aliases = { "fetchWebContent" = "fetch" }
    timeout_seconds = 8.0
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

__all__ = ["MCPServerConfig", "Transport", "load_mcp_servers"]


Transport = Literal["streamable_http", "stdio"]
_VALID_TRANSPORTS: tuple[Transport, ...] = ("streamable_http", "stdio")
_DEFAULT_TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True)
class MCPServerConfig:
    """Per-server MCP connector config.

    Exactly one of `url` (streamable_http) or `command` (stdio) must be
    populated, enforced by `load_mcp_servers`. `expose` is the allowlist
    of upstream tool names — anything not in the list is hidden from the
    LiteLLM tool palette. `aliases` is an upstream-name → exposed-name
    rename map applied after the allowlist filter (e.g. rename verbose
    upstream names like `fetchWebContent` to a tidier `fetch`).

    `timeout_seconds` is the per-call upper bound enforced by
    `MCPClient.call_tool` — exceeded calls raise `MCPUnavailableError`
    so the agent dispatch layer treats them like any transport failure.
    """

    name: str
    transport: Transport
    expose: list[str]
    url: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS


def load_mcp_servers(path: Path) -> list[MCPServerConfig]:
    """Parse + validate `mcp_servers.toml`.

    Raises:
        FileNotFoundError: if `path` does not exist.
        ValueError: on any schema violation. The message identifies the
            offending block by index (e.g. ``server[0]: missing 'name'``).
    """
    if not path.exists():
        raise FileNotFoundError(f"MCP servers config not found: {path}")

    with path.open("rb") as f:
        raw = tomllib.load(f)

    blocks: list[dict[str, Any]] = raw.get("server", []) or []
    if not isinstance(blocks, list):
        raise ValueError("'server' must be an array of tables ([[server]])")

    out: list[MCPServerConfig] = []
    for idx, block in enumerate(blocks):
        out.append(_parse_block(idx, block))
    return out


def _parse_block(idx: int, block: dict[str, Any]) -> MCPServerConfig:
    prefix = f"server[{idx}]"
    if not isinstance(block, dict):
        raise ValueError(f"{prefix}: must be a table")

    name = block.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError(f"{prefix}: missing or invalid 'name' (expected non-empty string)")

    transport = block.get("transport")
    if transport is None:
        raise ValueError(f"{prefix}: missing 'transport' (expected one of {_VALID_TRANSPORTS})")
    if transport not in _VALID_TRANSPORTS:
        raise ValueError(
            f"{prefix}: unknown 'transport' {transport!r} "
            f"(expected one of {_VALID_TRANSPORTS})"
        )

    expose_raw = block.get("expose")
    if not isinstance(expose_raw, list) or not all(isinstance(t, str) for t in expose_raw):
        raise ValueError(
            f"{prefix}: 'expose' must be a list of upstream tool name strings"
        )
    expose: list[str] = list(expose_raw)

    url = block.get("url")
    command = block.get("command")
    args_raw = block.get("args", [])
    if not isinstance(args_raw, list) or not all(isinstance(a, str) for a in args_raw):
        raise ValueError(f"{prefix}: 'args' must be a list of strings")
    args: list[str] = list(args_raw)

    if transport == "streamable_http":
        if not isinstance(url, str) or not url:
            raise ValueError(
                f"{prefix}: 'streamable_http' transport requires a non-empty 'url'"
            )
        if command is not None:
            raise ValueError(
                f"{prefix}: 'command' is only valid with transport='stdio'"
            )
    else:  # stdio
        if not isinstance(command, str) or not command:
            raise ValueError(
                f"{prefix}: 'stdio' transport requires a non-empty 'command'"
            )
        if url is not None:
            raise ValueError(
                f"{prefix}: 'url' is only valid with transport='streamable_http'"
            )

    aliases_raw = block.get("aliases", {})
    if not isinstance(aliases_raw, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in aliases_raw.items()
    ):
        raise ValueError(f"{prefix}: 'aliases' must be a string→string map")
    aliases: dict[str, str] = dict(aliases_raw)

    # Every alias key must be present in the expose list — otherwise the
    # operator wrote an alias for a tool that will never be reached.
    expose_set = set(expose)
    for upstream in aliases:
        if upstream not in expose_set:
            raise ValueError(
                f"{prefix}: alias key {upstream!r} is not in 'expose' "
                f"({sorted(expose_set)})"
            )

    timeout_raw = block.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
    if not isinstance(timeout_raw, (int, float)) or isinstance(timeout_raw, bool):
        raise ValueError(f"{prefix}: 'timeout_seconds' must be a number")
    timeout_seconds = float(timeout_raw)
    if timeout_seconds <= 0:
        raise ValueError(f"{prefix}: 'timeout_seconds' must be > 0")

    return MCPServerConfig(
        name=name,
        transport=transport,
        url=url if transport == "streamable_http" else None,
        command=command if transport == "stdio" else None,
        args=args,
        expose=expose,
        aliases=aliases,
        timeout_seconds=timeout_seconds,
    )
