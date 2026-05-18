"""Per-server MCP connector (SRS v2.5, §III-6.1).

`MCPClient` wraps the official Anthropic `mcp` Python SDK
(`mcp.client.streamable_http.streamablehttp_client` + `mcp.ClientSession`)
behind a small surface tailored to PaperHub's Research Agent dispatch:

* `connect()` is idempotent and uses exponential backoff (cap 4 attempts)
  before raising `MCPUnavailableError` for transport-level failures.
* `list_tools()` returns LiteLLM-shaped JSON-schema tool dicts with the
  upstream tool names namespaced (`<server>.<tool>`), filtered by the
  `expose` allowlist, with `aliases` applied.
* `call_tool(name, args)` accepts either the original upstream name *or*
  its alias (the registry strips the `<server>.` prefix before calling),
  enforces the per-server `timeout_seconds`, distinguishes transport
  failures (`MCPUnavailableError`) from upstream tool errors
  (`MCPToolError`).

Only the `streamable_http` transport is wired in v2.5-1; `stdio` raises
`NotImplementedError`. Plan E wires the stdio path when it adds the
sqlite MCP server block.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .config import MCPServerConfig
from .errors import MCPToolError, MCPUnavailableError

__all__ = ["MCPClient"]

_LOG = logging.getLogger(__name__)

# Exponential backoff schedule (seconds) for transport reconnect. Cap 4
# attempts total → 3 sleeps between them. Kept small so a permanently
# unreachable server doesn't block FastAPI startup for more than ~1s.
_BACKOFF_SCHEDULE: tuple[float, ...] = (0.1, 0.3, 0.7)


class MCPClient:
    """One connector per configured MCP server.

    The `connect()` lifetime owns an `AsyncExitStack` that holds open the
    underlying streamable-HTTP transport and the `ClientSession`. They
    are released together by `disconnect()` (or by a failed `connect()`
    retry loop).
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self._config = config
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._connected = False
        # Reverse alias map: exposed-name → upstream-name, populated lazily.
        self._reverse_aliases: dict[str, str] = {
            exposed: upstream for upstream, exposed in config.aliases.items()
        }

    @property
    def name(self) -> str:
        """Server namespace (the `<server>.` prefix on aggregated tool names)."""
        return self._config.name

    @property
    def connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------ lifecycle

    async def connect(self) -> None:
        """Open the transport + session. Idempotent.

        Retries transport errors with exponential backoff, capped at 4
        attempts. Raises `MCPUnavailableError` after the final failure
        or for any unsupported transport. Raises `NotImplementedError`
        for `stdio` (deferred to Plan E).
        """
        if self._connected:
            return

        if self._config.transport == "stdio":
            raise NotImplementedError(
                "stdio MCP transport is not wired in v2.5-1; ships in Plan E "
                "alongside the sqlite MCP server"
            )

        if self._config.transport != "streamable_http":
            # Defensive — config loader already rejects this, but keep
            # the dispatcher honest.
            raise MCPUnavailableError(
                f"unsupported MCP transport {self._config.transport!r} for "
                f"server {self._config.name!r}"
            )

        url = self._config.url
        assert url is not None  # guaranteed by config loader

        last_exc: BaseException | None = None
        attempts = len(_BACKOFF_SCHEDULE) + 1  # 4 total
        for attempt in range(attempts):
            if attempt > 0:
                await asyncio.sleep(_BACKOFF_SCHEDULE[attempt - 1])
            try:
                await self._open_session(url)
                self._connected = True
                _LOG.info("mcp.connect ok server=%s url=%s", self._config.name, url)
                return
            except Exception as exc:  # noqa: BLE001 — re-raised below
                last_exc = exc
                _LOG.warning(
                    "mcp.connect attempt %d/%d failed server=%s err=%s",
                    attempt + 1,
                    attempts,
                    self._config.name,
                    exc,
                )
                # Ensure any half-opened stack is released before retry.
                await self._close_stack_silently()

        assert last_exc is not None
        raise MCPUnavailableError(
            f"could not connect to MCP server {self._config.name!r} at {url} "
            f"after {attempts} attempts: {last_exc}"
        ) from last_exc

    async def disconnect(self) -> None:
        """Close the transport + session. Safe to call when not connected."""
        await self._close_stack_silently()
        self._connected = False

    async def _open_session(self, url: str) -> None:
        stack = AsyncExitStack()
        try:
            read, write, _get_session_id = await stack.enter_async_context(
                streamablehttp_client(url)
            )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except BaseException:
            await stack.aclose()
            raise
        self._stack = stack
        self._session = session

    async def _close_stack_silently(self) -> None:
        stack = self._stack
        self._stack = None
        self._session = None
        if stack is None:
            return
        try:
            await stack.aclose()
        except Exception as exc:  # noqa: BLE001
            _LOG.debug(
                "mcp.disconnect cleanup raised (suppressed) server=%s err=%s",
                self._config.name,
                exc,
            )

    # ------------------------------------------------------------------ public ops

    async def list_tools(self) -> list[dict[str, Any]]:
        """Fetch the upstream `tools/list` and reshape for LiteLLM.

        Returned schemas are namespaced (`<server>.<tool>`), filtered by
        `MCPServerConfig.expose`, and have `MCPServerConfig.aliases`
        applied to the final tool name.
        """
        session = self._require_session()
        result = await session.list_tools()

        expose = set(self._config.expose)
        out: list[dict[str, Any]] = []
        for tool in result.tools:
            if tool.name not in expose:
                continue
            exposed_name = self._config.aliases.get(tool.name, tool.name)
            namespaced = f"{self._config.name}.{exposed_name}"
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": namespaced,
                        "description": tool.description or "",
                        "parameters": tool.inputSchema or {"type": "object"},
                    },
                }
            )
        return out

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Invoke an upstream tool by its un-namespaced name.

        ``name`` may be either the original upstream name (e.g.
        ``fetchWebContent``) or its alias (e.g. ``fetch``); the client
        translates the alias back before the wire call.

        Returns:
            ``structuredContent`` if the upstream provided it, else the
            concatenated text of the result's content blocks.

        Raises:
            MCPUnavailableError: on timeout or transport failure.
            MCPToolError: if the tool is not exposed, or the upstream
                response has ``isError=True``.
        """
        session = self._require_session()

        upstream_name = self._reverse_aliases.get(name, name)
        if upstream_name not in self._config.expose:
            raise MCPToolError(
                f"unknown tool {name!r} for MCP server {self._config.name!r} "
                f"(exposed: {sorted(self._config.expose)})"
            )

        try:
            result = await asyncio.wait_for(
                session.call_tool(upstream_name, arguments=args),
                timeout=self._config.timeout_seconds,
            )
        except TimeoutError as exc:
            raise MCPUnavailableError(
                f"MCP tool {self._config.name}.{name} timed out after "
                f"{self._config.timeout_seconds:.1f}s"
            ) from exc
        except MCPToolError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MCPUnavailableError(
                f"MCP tool {self._config.name}.{name} transport error: {exc}"
            ) from exc

        text_parts = [
            getattr(block, "text", "")
            for block in (result.content or [])
            if getattr(block, "type", None) == "text"
        ]
        joined_text = "\n".join(p for p in text_parts if p)

        if getattr(result, "isError", False):
            raise MCPToolError(
                f"MCP tool {self._config.name}.{name} returned error: "
                f"{joined_text or '<no message>'}"
            )

        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            return structured
        return joined_text

    def _require_session(self) -> ClientSession:
        if not self._connected or self._session is None:
            raise MCPUnavailableError(
                f"MCP client for server {self._config.name!r} is not connected; "
                "call connect() first"
            )
        return self._session
