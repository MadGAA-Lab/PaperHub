"""Tests for `paperhub.mcp.config` loader + validation."""
from __future__ import annotations

from pathlib import Path

import pytest

from paperhub.mcp.config import MCPServerConfig, load_mcp_servers


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "mcp_servers.toml"
    p.write_text(body, encoding="utf-8")
    return p


def test_load_streamable_http_block(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[[server]]
name = "web"
transport = "streamable_http"
url = "http://localhost:3000/mcp"
expose = ["search", "fetchWebContent"]
aliases = { "fetchWebContent" = "fetch" }
timeout_seconds = 8.0
""",
    )
    servers = load_mcp_servers(path)
    assert len(servers) == 1
    cfg = servers[0]
    assert cfg.name == "web"
    assert cfg.transport == "streamable_http"
    assert cfg.url == "http://localhost:3000/mcp"
    assert cfg.expose == ["search", "fetchWebContent"]
    assert cfg.aliases == {"fetchWebContent": "fetch"}
    assert cfg.timeout_seconds == pytest.approx(8.0)
    assert cfg.command is None
    assert cfg.args == []


def test_load_multiple_servers(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[[server]]
name = "web"
transport = "streamable_http"
url = "http://localhost:3000/mcp"
expose = ["search"]

[[server]]
name = "sql"
transport = "streamable_http"
url = "http://localhost:3100/mcp"
expose = ["query"]
""",
    )
    servers = load_mcp_servers(path)
    assert [s.name for s in servers] == ["web", "sql"]


def test_load_stdio_block(tmp_path: Path) -> None:
    """Stdio config schema is accepted (dispatch is not implemented yet)."""
    path = _write(
        tmp_path,
        """
[[server]]
name = "fs"
transport = "stdio"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]
expose = ["read_file"]
""",
    )
    servers = load_mcp_servers(path)
    assert len(servers) == 1
    cfg = servers[0]
    assert cfg.transport == "stdio"
    assert cfg.command == "npx"
    assert cfg.args == ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]
    assert cfg.url is None


def test_default_timeout_when_omitted(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[[server]]
name = "web"
transport = "streamable_http"
url = "http://localhost:3000/mcp"
expose = ["search"]
""",
    )
    cfg = load_mcp_servers(path)[0]
    assert cfg.timeout_seconds > 0  # default applied


def test_missing_name_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[[server]]
transport = "streamable_http"
url = "http://localhost:3000/mcp"
expose = ["search"]
""",
    )
    with pytest.raises(ValueError, match=r"server\[0\].*name"):
        load_mcp_servers(path)


def test_missing_transport_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[[server]]
name = "web"
url = "http://localhost:3000/mcp"
expose = ["search"]
""",
    )
    with pytest.raises(ValueError, match=r"transport"):
        load_mcp_servers(path)


def test_unknown_transport_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[[server]]
name = "web"
transport = "websocket"
url = "ws://localhost:3000/mcp"
expose = ["search"]
""",
    )
    with pytest.raises(ValueError, match=r"transport"):
        load_mcp_servers(path)


def test_streamable_http_requires_url(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[[server]]
name = "web"
transport = "streamable_http"
expose = ["search"]
""",
    )
    with pytest.raises(ValueError, match=r"url"):
        load_mcp_servers(path)


def test_stdio_requires_command(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[[server]]
name = "fs"
transport = "stdio"
expose = ["read_file"]
""",
    )
    with pytest.raises(ValueError, match=r"command"):
        load_mcp_servers(path)


def test_alias_referencing_unknown_tool_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[[server]]
name = "web"
transport = "streamable_http"
url = "http://localhost:3000/mcp"
expose = ["search"]
aliases = { "fetchWebContent" = "fetch" }
""",
    )
    with pytest.raises(ValueError, match=r"alias"):
        load_mcp_servers(path)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_mcp_servers(tmp_path / "nope.toml")


def test_empty_file_returns_empty_list(tmp_path: Path) -> None:
    path = _write(tmp_path, "")
    assert load_mcp_servers(path) == []


def test_dataclass_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    cfg = MCPServerConfig(
        name="web",
        transport="streamable_http",
        url="http://x",
        expose=["search"],
    )
    with pytest.raises(FrozenInstanceError):
        cfg.name = "other"  # type: ignore[misc]
