"""Real-socket tests for `paperhub.mcp.registry._tcp_reachable`.

The autostart subprocess tracker depends on a reliable "is the daemon
listening?" probe. Our other registry tests stub `_tcp_reachable` so they
exercise the policy (skip/spawn/terminate) without paying for sockets —
which means they could NOT catch a bug like the one diagnosed during
live-backend smoke: on Windows, ``localhost`` resolves to ``::1`` first
but Node servers bind IPv4 only, and ``asyncio.open_connection`` hangs
on the unreachable IPv6 address until the per-probe timeout fires.

These tests spin up real ``asyncio.start_server`` listeners and probe
them through the public ``_tcp_reachable`` API. They run on every CI box.
"""
from __future__ import annotations

import asyncio
import contextlib
import socket

import pytest

from paperhub.mcp.registry import _tcp_reachable

pytestmark = pytest.mark.asyncio


def _pick_free_port() -> int:
    """Bind ephemeral, release, return the port number."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def _serve_briefly(host: str, port: int) -> asyncio.Server:
    """Stand up a no-op TCP listener on ``host:port`` for the test."""

    async def _handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
    ) -> None:
        # Just close; the probe is only checking accept().
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()

    return await asyncio.start_server(_handle, host=host, port=port)


async def test_probe_returns_true_for_listener_on_127_0_0_1() -> None:
    """Sanity: a live IPv4 loopback listener is detected as reachable."""
    port = _pick_free_port()
    server = await _serve_briefly("127.0.0.1", port)
    try:
        assert await _tcp_reachable("127.0.0.1", port) is True
    finally:
        server.close()
        await server.wait_closed()


async def test_probe_returns_true_when_host_is_localhost_ipv4_only() -> None:
    """Regression: ``localhost`` probe must succeed against an IPv4-only
    listener.

    On Windows this is the live-backend bug — ``localhost`` resolves to
    ``::1`` first; if `_tcp_reachable` only tries the first address and
    times out, the autostart kills the open-websearch subprocess. The
    fix iterates over all ``getaddrinfo`` results (IPv4 preferred).
    """
    port = _pick_free_port()
    server = await _serve_briefly("127.0.0.1", port)  # IPv4 ONLY
    try:
        # Probe via the hostname `localhost` — must succeed even though
        # `localhost` may resolve to `::1` first on Windows.
        assert await _tcp_reachable("localhost", port) is True
    finally:
        server.close()
        await server.wait_closed()


async def test_probe_returns_false_for_unbound_port() -> None:
    """A port nobody's listening on must report as unreachable."""
    port = _pick_free_port()
    # Don't start a server. The probe should fail-fast (no 30s wait).
    assert await _tcp_reachable("127.0.0.1", port) is False


async def test_probe_returns_false_for_unresolvable_host() -> None:
    """A clearly bogus hostname must return False without raising."""
    assert await _tcp_reachable(
        "this-host-should-never-resolve.invalid", 80,
    ) is False
