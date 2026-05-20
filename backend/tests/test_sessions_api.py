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


# ---------------------------------------------------------------------------
# DELETE /sessions/{id} — cascade cleanup of session-scoped rows
# ---------------------------------------------------------------------------


async def test_delete_session_returns_404_for_missing(
    sessions_client: AsyncClient,
) -> None:
    resp = await sessions_client.delete("/sessions/9999")
    assert resp.status_code == 404
    assert "9999" in resp.json()["detail"]


async def test_delete_session_cascades_papers_messages_runs_tool_calls(
    sessions_client: AsyncClient, tmp_path: Path,
) -> None:
    """Verify the FK chain: deleting a chat_sessions row also deletes its
    papers (membership), messages, runs, and tool_calls — but leaves the
    shared paper_content row intact."""
    db_path = tmp_path / "paperhub.db"

    # Seed: 1 session, 1 paper_content (shared with another session below),
    # 1 papers membership row, 1 message, 1 run, 1 tool_call.
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        # Two sessions — one we'll delete, one survives so we can assert
        # the paper_content row isn't touched.
        await conn.execute("INSERT INTO chat_sessions DEFAULT VALUES")
        await conn.execute("INSERT INTO chat_sessions DEFAULT VALUES")
        await conn.execute(
            "INSERT INTO paper_content "
            "(content_key, kind, arxiv_id, title, authors_json, year, abstract, "
            " source_path, source_dir_path, html_path) "
            "VALUES ('arxiv:test', 'arxiv', 'test', 't', '[]', 2024, 'a', '/x', '/x', '/x.html')",
        )
        # Attach the paper to BOTH sessions.
        await conn.execute(
            "INSERT INTO papers (session_id, paper_content_id) VALUES (1, 1)",
        )
        await conn.execute(
            "INSERT INTO papers (session_id, paper_content_id) VALUES (2, 1)",
        )
        await conn.execute(
            "INSERT INTO runs (session_id, status) VALUES (1, 'ok')",
        )
        await conn.execute(
            "INSERT INTO messages (session_id, role, content, run_id) "
            "VALUES (1, 'user', 'hi', 1)",
        )
        await conn.execute(
            "INSERT INTO tool_calls (run_id, branch, step_index, agent, tool, latency_ms, status) "
            "VALUES (1, '', 0, 'router', 'classify', 10, 'ok')",
        )
        await conn.commit()

    # Delete session 1.
    resp = await sessions_client.delete("/sessions/1")
    assert resp.status_code == 204

    # Verify the cascade.
    async with aiosqlite.connect(db_path) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM chat_sessions WHERE id = 1",
        ) as cur:
            sess = await cur.fetchone()
        async with conn.execute(
            "SELECT COUNT(*) FROM papers WHERE session_id = 1",
        ) as cur:
            papers_sess1 = await cur.fetchone()
        async with conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = 1",
        ) as cur:
            msgs = await cur.fetchone()
        async with conn.execute(
            "SELECT COUNT(*) FROM runs WHERE session_id = 1",
        ) as cur:
            runs = await cur.fetchone()
        async with conn.execute(
            "SELECT COUNT(*) FROM tool_calls WHERE run_id = 1",
        ) as cur:
            tcs = await cur.fetchone()
        async with conn.execute(
            "SELECT COUNT(*) FROM papers WHERE session_id = 2",
        ) as cur:
            papers_sess2 = await cur.fetchone()
        async with conn.execute(
            "SELECT COUNT(*) FROM paper_content WHERE id = 1",
        ) as cur:
            pc = await cur.fetchone()

    # Session-scoped rows are gone.
    assert sess is not None and sess[0] == 0, "chat_sessions row should be deleted"
    assert papers_sess1 is not None and papers_sess1[0] == 0, (
        "papers rows for session 1 should cascade-delete"
    )
    assert msgs is not None and msgs[0] == 0, "messages should cascade-delete"
    assert runs is not None and runs[0] == 0, "runs should cascade-delete"
    assert tcs is not None and tcs[0] == 0, (
        "tool_calls should cascade via runs"
    )
    # Shared rows survive.
    assert papers_sess2 is not None and papers_sess2[0] == 1, (
        "session 2's membership row must NOT be touched"
    )
    assert pc is not None and pc[0] == 1, (
        "paper_content row must NOT be touched — papers are deduplicated"
    )
