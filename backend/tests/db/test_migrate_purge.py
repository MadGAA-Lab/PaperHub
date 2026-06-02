"""Tests for ``purge_deleted_sessions`` disk-cascade + the orphan-folder
sweeper. Both close the leaky-cleanup gap: a tombstoned session's row was
hard-deleted past the retention window, but its
``workspace/chat_session/<id>/`` folder leaked indefinitely.
"""
import aiosqlite
import pytest

from paperhub.db.migrate import (
    apply_schema,
    purge_deleted_sessions,
    sweep_orphan_session_folders,
)


@pytest.mark.asyncio
async def test_purge_deletes_db_row_and_disk_folder(tmp_path):
    """Tombstoned + past-retention sessions: DB row gone AND folder gone."""
    db = tmp_path / "test.db"
    workspace = tmp_path / "workspace"
    sessions_root = workspace / "chat_session"
    sessions_root.mkdir(parents=True)

    async with aiosqlite.connect(str(db)) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await apply_schema(conn)
        # Seed three sessions: one active, one tombstoned-fresh, one tombstoned-old.
        await conn.execute(
            "INSERT INTO chat_sessions (id, created_at, title) "
            "VALUES (1, datetime('now'), 'active')"
        )
        await conn.execute(
            "INSERT INTO chat_sessions (id, created_at, title, deleted_at) "
            "VALUES (2, datetime('now'), 'fresh-tomb', datetime('now'))"
        )
        await conn.execute(
            "INSERT INTO chat_sessions (id, created_at, title, deleted_at) "
            "VALUES (3, datetime('now'), 'old-tomb', datetime('now', '-100 days'))"
        )
        await conn.commit()

        # Create folders for all three.
        for sid in (1, 2, 3):
            (sessions_root / str(sid) / "slides").mkdir(parents=True)
            (sessions_root / str(sid) / "slides" / "deck.tex").write_text("test")

        # Purge with retention=30 days.
        n = await purge_deleted_sessions(
            conn, retention_days=30, workspace_dir=workspace,
        )
        assert n == 1  # only session 3 (older than 30 days)

        # DB: session 1 + 2 remain; 3 is gone.
        async with conn.execute(
            "SELECT id FROM chat_sessions ORDER BY id"
        ) as cur:
            ids = [r[0] for r in await cur.fetchall()]
        assert ids == [1, 2]

        # Disk: folders for 1 + 2 remain; 3 is gone.
        assert (sessions_root / "1").exists()
        assert (sessions_root / "2").exists()
        assert not (sessions_root / "3").exists()


@pytest.mark.asyncio
async def test_purge_no_workspace_dir_is_db_only_backward_compat(tmp_path):
    """When workspace_dir is None (legacy callers), purge is DB-only."""
    db = tmp_path / "test.db"
    async with aiosqlite.connect(str(db)) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await apply_schema(conn)
        await conn.execute(
            "INSERT INTO chat_sessions (id, created_at, title, deleted_at) "
            "VALUES (1, datetime('now'), 'old', datetime('now', '-100 days'))"
        )
        await conn.commit()
        # No workspace_dir -> DB-only purge, no error.
        n = await purge_deleted_sessions(conn, retention_days=30)
        assert n == 1


@pytest.mark.asyncio
async def test_purge_missing_folder_does_not_block(tmp_path):
    """A session with no on-disk folder still purges the DB row cleanly."""
    db = tmp_path / "test.db"
    workspace = tmp_path / "workspace"
    (workspace / "chat_session").mkdir(parents=True)
    async with aiosqlite.connect(str(db)) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await apply_schema(conn)
        await conn.execute(
            "INSERT INTO chat_sessions (id, created_at, title, deleted_at) "
            "VALUES (42, datetime('now'), 'old', datetime('now', '-100 days'))"
        )
        await conn.commit()
        # Folder for 42 does NOT exist on disk; purge must still succeed.
        n = await purge_deleted_sessions(
            conn, retention_days=30, workspace_dir=workspace,
        )
        assert n == 1


@pytest.mark.asyncio
async def test_sweep_orphan_folders(tmp_path):
    """Folders whose session id has no DB row are removed."""
    db = tmp_path / "test.db"
    workspace = tmp_path / "workspace"
    sessions_root = workspace / "chat_session"
    sessions_root.mkdir(parents=True)

    async with aiosqlite.connect(str(db)) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await apply_schema(conn)
        await conn.execute(
            "INSERT INTO chat_sessions (id, created_at, title) "
            "VALUES (1, datetime('now'), 'active')"
        )
        await conn.commit()

        for sid in (1, 5, 7):  # 5 and 7 are orphans
            (sessions_root / str(sid)).mkdir()
            (sessions_root / str(sid) / "marker.txt").write_text("x")

        removed = await sweep_orphan_session_folders(conn, workspace)
        assert removed == 2  # 5 and 7
        assert (sessions_root / "1").exists()
        assert not (sessions_root / "5").exists()
        assert not (sessions_root / "7").exists()


@pytest.mark.asyncio
async def test_sweep_ignores_non_digit_directories(tmp_path):
    """Non-numeric directories (e.g. 'scratch', 'tmp') are left alone."""
    db = tmp_path / "test.db"
    workspace = tmp_path / "workspace"
    sessions_root = workspace / "chat_session"
    sessions_root.mkdir(parents=True)
    (sessions_root / "scratch").mkdir()
    (sessions_root / "tmp_data").mkdir()
    (sessions_root / "5").mkdir()  # orphan

    async with aiosqlite.connect(str(db)) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await apply_schema(conn)
        removed = await sweep_orphan_session_folders(conn, workspace)
        assert removed == 1
        assert (sessions_root / "scratch").exists()
        assert (sessions_root / "tmp_data").exists()
        assert not (sessions_root / "5").exists()


@pytest.mark.asyncio
async def test_sweep_no_sessions_root_returns_zero(tmp_path):
    """When workspace/chat_session/ doesn't exist, sweep is a clean no-op."""
    db = tmp_path / "test.db"
    workspace = tmp_path / "workspace"  # never created
    async with aiosqlite.connect(str(db)) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await apply_schema(conn)
        removed = await sweep_orphan_session_folders(conn, workspace)
        assert removed == 0
