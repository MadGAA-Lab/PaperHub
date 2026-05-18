"""Tests for POST /sessions — eager session creation endpoint."""
from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from paperhub.app import create_app
from paperhub.db.migrate import apply_schema

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def sessions_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    """ASGI test client with DB bootstrapped and model pre-warm disabled."""
    monkeypatch.setenv("PAPERHUB_PREWARM_MODELS", "0")
    monkeypatch.setenv("PAPERHUB_WORKSPACE", str(tmp_path))
    db_path = tmp_path / "paperhub.db"
    async with aiosqlite.connect(db_path) as conn:
        await apply_schema(conn)
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


async def test_post_sessions_creates_empty_session_row(
    sessions_client: AsyncClient,
    tmp_path: Path,
) -> None:
    """POST /sessions returns 201 + {session_id: <int>} and creates a row
    in chat_sessions."""
    resp = await sessions_client.post("/sessions")
    assert resp.status_code == 201
    data = resp.json()
    assert "session_id" in data
    session_id = data["session_id"]
    assert isinstance(session_id, int)
    assert session_id >= 1

    # Verify the row actually exists in the DB.
    db_path = tmp_path / "paperhub.db"
    async with aiosqlite.connect(db_path) as conn, conn.execute(
        "SELECT id FROM chat_sessions WHERE id = ?", (session_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row is not None, f"chat_sessions row {session_id} not found"


async def test_post_sessions_returns_incrementing_ids(
    sessions_client: AsyncClient,
) -> None:
    """Multiple POST /sessions calls return different session_ids."""
    resp1 = await sessions_client.post("/sessions")
    resp2 = await sessions_client.post("/sessions")
    assert resp1.status_code == 201
    assert resp2.status_code == 201
    id1 = resp1.json()["session_id"]
    id2 = resp2.json()["session_id"]
    assert id1 != id2
