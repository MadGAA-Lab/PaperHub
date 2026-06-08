# Fork-a-message ("rewind & resend") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user branch a NEW chat session from any of their own past messages — copying the history above the fork point plus the enabled references, session memories, and the deck — and prefill (NOT auto-send) the forked message into the composer so it can be edited (re-prompt) or sent unchanged (retry), leaving the original session untouched.

**Architecture:** A new backend `POST /sessions/{id}/fork` does the durable copy (a client-only copy would be pruned by `useSessionsSync`'s strict DB mirror, v2.15). Given the forked user message's `run_id`, it copies — in a single core transaction — every message strictly *before* that message (remapping each turn's `run_id` to fresh `runs` rows carrying `routing_decision_json` + `search_results_json` + `deck_version_id`), the session's `papers` membership rows (same shared `paper_content`, no re-ingest), and the active session-scoped `memories` + `slide_style_overrides`. The deck is copied best-effort *after* the core commit: copytree the session's `slides/` cache dir into the fork's own dir, then insert the `decks` + `deck_slides` rows with rewritten artifact paths — if the artifact copy fails, the fork still succeeds *without* a deck. The frontend reveals a rewind icon (lucide `RotateCcw`) on hover of the user's own messages; clicking forks, adds the returned session to the store, selects it, and prefills the composer (editable, no send). The fork arrives as a real backend session so the strict mirror keeps it and `useSessionsSync` hydrates its copied history.

**Tech Stack:** Python 3.12 / FastAPI / aiosqlite / pytest (asyncio_mode=auto) / `uv`; React 19 / TypeScript / Zustand / Vitest + RTL + MSW.

---

## File Structure

**Backend**
- Create `backend/src/paperhub/db/fork.py` — `fork_session(...)`: the transactional slice-copy + best-effort deck-artifact copy. One responsibility: produce a complete fork of a session up to a fork point.
- Modify `backend/src/paperhub/api/sessions.py` — add `POST /sessions/{session_id}/fork` (request `{run_id}`, response `{session_id, forked_message, title}`).
- Modify `backend/src/paperhub/api/chat.py` — `_record_user_message` title-promote also fires for the `"Fork of …"` placeholder (so the first send renames the fork).
- Create `backend/tests/test_fork.py` — unit tests for `fork_session`.
- Modify `backend/tests/test_sessions_api.py` — endpoint tests + the title-promote test.

**Frontend**
- Modify `frontend/src/lib/api.ts` — `forkSession(sessionId, runId)` client.
- Modify `frontend/src/types/domain.ts` — `ForkResult` interface.
- Modify `frontend/src/store/chat.ts` — `addForkedSession(backendId, title)` action.
- Modify `frontend/src/components/chat/MessageBubble.tsx` — hover-revealed rewind control on user messages (`onFork` prop).
- Modify `frontend/src/components/chat/ChatThread.tsx` — resolve each user message's fork `run_id`, call the API, wire `addForkedSession` + `requestComposerText`.
- Modify `frontend/src/store/chat.test.ts` (create if absent) — `addForkedSession` test.
- Create `frontend/src/components/chat/MessageBubble.fork.test.tsx` — rewind-icon rendering + click behaviour.

---

## Background the implementer needs (read before starting)

- **One turn = one `runs` row + (usually) one user `messages` row + one assistant `messages` row, both pointing at that `run_id`.** See `backend/src/paperhub/api/chat.py` `_new_run` / `_record_user_message` / `_finalise`.
- **`GET /sessions/{id}/messages`** (in `sessions.py`) replays history by joining `runs` (for `routing_decision_json`, `search_results_json`) and `decks` (for the per-turn DeckChip). The deck card attaches to a turn when `runs.deck_version_id IS NOT NULL` OR the deck row's `run_id` equals the message's `run_id`. So copied runs must carry the original `deck_version_id` for the deck chip to replay on the right turns.
- **`GET /sessions`** lists a session when `message_count > 0 OR title <> 'New chat'`. A fork titled `"Fork of …"` is always listed (even an empty-history fork), so the strict mirror in `reconcileBackendSessions` won't prune it.
- **Deck artifacts** live at `<workspace_dir>/chat_session/<session_id>/slides/` — `deck.tex`, `deck.pdf`, staged `figures`, and `edit_history/version_*.json|.pdf`. `decks.tex_path` / `pdf_path` are ABSOLUTE paths into that dir (written by `sl_emit.run_sl_emit`). `settings.workspace_dir` is the root (`backend/src/paperhub/config.py`).
- **Schema** (`backend/src/paperhub/db/schema.sql`): `papers(session_id, paper_content_id, enabled, added_at, UNIQUE(session_id, paper_content_id))`; `memories(scope, session_id, content, …, status, supersedes, superseded_by, metadata, CHECK((scope='global')=(session_id IS NULL)))`; `decks` has `UNIQUE(session_id)`; `deck_slides(deck_id, slide_index, frame_tex, note_text, note_language, page_start, page_end, UNIQUE(deck_id, slide_index))`; `slide_style_overrides(session_id PK, preamble_tex, source, …)`.
- **`tool_calls` is NOT copied** — it's dev-only observability, not user history.
- **Live user messages carry `run_id: null`** until the turn's `run_id` is patched onto the assistant message and the session is re-hydrated from the DB. So the frontend must resolve a user message's fork `run_id` from the message itself OR the following assistant message, and disable the rewind control when neither is known.

---

## Task 1: `fork_session` core copy (messages + runs + papers + memories + style; NO deck)

**Files:**
- Create: `backend/src/paperhub/db/fork.py`
- Test: `backend/tests/test_fork.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_fork.py
from __future__ import annotations

from pathlib import Path

import aiosqlite

from paperhub.db.fork import fork_session
from paperhub.db.migrate import apply_schema


async def _seed_paper_content(conn: aiosqlite.Connection, *, title: str) -> int:
    cur = await conn.execute(
        "INSERT INTO paper_content "
        "(content_key, kind, arxiv_id, title, source_path, source_dir_path, html_path) "
        "VALUES (?, 'arxiv', ?, ?, '/x', '/x', '/x/h.html')",
        (f"arxiv:{title}", title, title),
    )
    await conn.commit()
    return int(cur.lastrowid)


async def _turn(conn: aiosqlite.Connection, sid: int, user: str, asst: str,
                *, routing: str | None = None, cards: str | None = None) -> int:
    """Create one run + a user message + an assistant message. Returns run_id."""
    cur = await conn.execute(
        "INSERT INTO runs (session_id, routing_decision_json, search_results_json, "
        "status) VALUES (?, ?, ?, 'ok')",
        (sid, routing, cards),
    )
    run_id = int(cur.lastrowid)
    await conn.execute(
        "INSERT INTO messages (session_id, role, content, run_id) "
        "VALUES (?, 'user', ?, ?)", (sid, user, run_id))
    await conn.execute(
        "INSERT INTO messages (session_id, role, content, run_id) "
        "VALUES (?, 'assistant', ?, ?)", (sid, asst, run_id))
    await conn.commit()
    return run_id


async def test_fork_copies_only_slice_above_point(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await apply_schema(conn)
        await conn.execute("INSERT INTO chat_sessions (title) VALUES ('Orig')")
        await conn.commit()
        r1 = await _turn(conn, 1, "first q", "first a", routing='{"intent":"chitchat"}')
        r2 = await _turn(conn, 1, "second q", "second a")  # <- fork point
        r3 = await _turn(conn, 1, "third q", "third a")

        res = await fork_session(
            conn, source_session_id=1, fork_run_id=r2,
            workspace_dir=tmp_path,
        )

        # New session created with the "Fork of <orig>" placeholder title.
        assert res.new_session_id != 1
        assert res.forked_message == "second q"
        async with conn.execute(
            "SELECT title FROM chat_sessions WHERE id = ?", (res.new_session_id,)
        ) as cur:
            assert (await cur.fetchone())[0] == "Fork of Orig"

        # Only the turn(s) STRICTLY BEFORE the fork point are copied:
        # r1's user+assistant (2 messages). r2 and r3 excluded.
        async with conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
            (res.new_session_id,),
        ) as cur:
            rows = await cur.fetchall()
        assert rows == [("user", "first q"), ("assistant", "first a")]

        # The original session is byte-unchanged: 6 messages, 3 runs.
        async with conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = 1") as cur:
            assert (await cur.fetchone())[0] == 6

        # Copied messages reference NEW run rows (remapped), not the originals.
        async with conn.execute(
            "SELECT DISTINCT run_id FROM messages WHERE session_id = ?",
            (res.new_session_id,),
        ) as cur:
            new_run_ids = {r[0] for r in await cur.fetchall()}
        assert new_run_ids and r1 not in new_run_ids
        # The remapped run preserves routing_decision_json.
        async with conn.execute(
            "SELECT routing_decision_json FROM runs WHERE id = ?",
            (next(iter(new_run_ids)),),
        ) as cur:
            assert (await cur.fetchone())[0] == '{"intent":"chitchat"}'


async def test_fork_copies_papers_and_session_memories(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await apply_schema(conn)
        await conn.execute("INSERT INTO chat_sessions (title) VALUES ('Orig')")
        await conn.commit()
        pc1 = await _seed_paper_content(conn, title="P1")
        pc2 = await _seed_paper_content(conn, title="P2")
        await conn.execute(
            "INSERT INTO papers (session_id, paper_content_id, enabled) VALUES (1, ?, 1)",
            (pc1,))
        await conn.execute(
            "INSERT INTO papers (session_id, paper_content_id, enabled) VALUES (1, ?, 0)",
            (pc2,))
        await conn.execute(
            "INSERT INTO memories (scope, session_id, content) "
            "VALUES ('session', 1, 'reply in Japanese')")
        await conn.execute(
            "INSERT INTO memories (scope, session_id, content, status) "
            "VALUES ('session', 1, 'stale', 'superseded')")
        await conn.execute(
            "INSERT INTO memories (scope, session_id, content) VALUES (NULL, NULL, 'x') "
        ) if False else None  # global memory not copied (applies everywhere already)
        r1 = await _turn(conn, 1, "q", "a")
        await conn.commit()

        res = await fork_session(
            conn, source_session_id=1, fork_run_id=r1, workspace_dir=tmp_path)

        # Both papers rows copied, enabled flag preserved, same paper_content.
        async with conn.execute(
            "SELECT paper_content_id, enabled FROM papers WHERE session_id = ? "
            "ORDER BY paper_content_id", (res.new_session_id,)) as cur:
            assert await cur.fetchall() == [(pc1, 1), (pc2, 0)]

        # Only ACTIVE session memories copied, re-scoped, chain FKs reset to NULL.
        async with conn.execute(
            "SELECT content, scope, session_id, supersedes, superseded_by "
            "FROM memories WHERE session_id = ?", (res.new_session_id,)) as cur:
            mem = await cur.fetchall()
        assert mem == [("reply in Japanese", "session", res.new_session_id, None, None)]


async def test_fork_first_message_yields_empty_history(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await apply_schema(conn)
        await conn.execute("INSERT INTO chat_sessions (title) VALUES ('Orig')")
        await conn.commit()
        r1 = await _turn(conn, 1, "only q", "only a")

        res = await fork_session(
            conn, source_session_id=1, fork_run_id=r1, workspace_dir=tmp_path)

        assert res.forked_message == "only q"
        async with conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?",
            (res.new_session_id,)) as cur:
            assert (await cur.fetchone())[0] == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend; uv run pytest tests/test_fork.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'paperhub.db.fork'`.

- [ ] **Step 3: Write the minimal implementation**

```python
# backend/src/paperhub/db/fork.py
"""Fork a chat session at a chosen message (SRS v2.30).

``fork_session`` branches a NEW chat session from the point ABOVE a forked
user message: it copies every message STRICTLY BEFORE that message (remapping
each turn's ``run_id`` to a fresh ``runs`` row carrying the per-turn replay
data), the session's ``papers`` membership rows (same shared ``paper_content``),
the active session-scoped ``memories``, and the ``slide_style_overrides`` row.
The forked message itself + everything after it are NOT copied — the message
text is returned for the composer prefill. The dev-only ``tool_calls`` trace is
NOT copied (observability, not user history).

The deck is copied by ``_copy_deck`` (Task 2), AFTER the core transaction commits
and best-effort: a deck-artifact copy failure leaves the fork deckless rather
than aborting it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import aiosqlite

_FORK_TITLE_PREFIX = "Fork of "


@dataclass(frozen=True)
class ForkResult:
    new_session_id: int
    forked_message: str
    title: str


async def _forked_message(
    conn: aiosqlite.Connection, *, source_session_id: int, fork_run_id: int
) -> tuple[int, str]:
    """Return (message_id, content) of the forked user message — the earliest
    user message of ``fork_run_id`` in the source session. Raises ValueError if
    no such message exists (a bad run_id, or a run with no user message)."""
    async with conn.execute(
        "SELECT id, content FROM messages "
        "WHERE session_id = ? AND run_id = ? AND role = 'user' "
        "ORDER BY id LIMIT 1",
        (source_session_id, fork_run_id),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise ValueError(
            f"no user message for run_id={fork_run_id} in session {source_session_id}"
        )
    return int(row[0]), str(row[1])


async def fork_session(
    conn: aiosqlite.Connection,
    *,
    source_session_id: int,
    fork_run_id: int,
    workspace_dir: Path,
) -> ForkResult:
    # Resolve the fork point first (raises if the run_id is bogus).
    fork_msg_id, forked_text = await _forked_message(
        conn, source_session_id=source_session_id, fork_run_id=fork_run_id
    )

    async with conn.execute(
        "SELECT title FROM chat_sessions WHERE id = ?", (source_session_id,)
    ) as cur:
        srow = await cur.fetchone()
    if srow is None:
        raise ValueError(f"source session {source_session_id} not found")
    new_title = f"{_FORK_TITLE_PREFIX}{srow[0]}"

    # --- Core copy: atomic. -------------------------------------------------
    await conn.execute("BEGIN")
    try:
        cur = await conn.execute(
            "INSERT INTO chat_sessions (title) VALUES (?)", (new_title,)
        )
        new_sid = int(cur.lastrowid)

        # Messages strictly before the fork point, in id order.
        async with conn.execute(
            "SELECT id, role, content, run_id, created_at FROM messages "
            "WHERE session_id = ? AND id < ? ORDER BY id",
            (source_session_id, fork_msg_id),
        ) as mcur:
            msg_rows = await mcur.fetchall()

        # Remap each distinct old run_id -> a fresh run row (preserving the
        # replay payload). NULL run_ids stay NULL.
        run_map: dict[int, int] = {}
        for _mid, _role, _content, old_run_id, _created in msg_rows:
            if old_run_id is None or old_run_id in run_map:
                continue
            async with conn.execute(
                "SELECT routing_decision_json, search_results_json, "
                "deck_version_id, started_at, finished_at, status "
                "FROM runs WHERE id = ?",
                (old_run_id,),
            ) as rcur:
                r = await rcur.fetchone()
            if r is None:
                continue
            ins = await conn.execute(
                "INSERT INTO runs (session_id, routing_decision_json, "
                "search_results_json, deck_version_id, started_at, finished_at, "
                "status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (new_sid, r[0], r[1], r[2], r[3], r[4], r[5]),
            )
            run_map[int(old_run_id)] = int(ins.lastrowid)

        for _mid, role, content, old_run_id, created in msg_rows:
            new_run_id = run_map.get(int(old_run_id)) if old_run_id is not None else None
            await conn.execute(
                "INSERT INTO messages (session_id, role, content, run_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (new_sid, role, content, new_run_id, created),
            )

        # papers membership: same shared paper_content, preserve enabled+added_at.
        await conn.execute(
            "INSERT INTO papers (session_id, paper_content_id, enabled, added_at) "
            "SELECT ?, paper_content_id, enabled, added_at FROM papers "
            "WHERE session_id = ?",
            (new_sid, source_session_id),
        )

        # Active session memories, re-scoped, chain FKs reset (fresh chain).
        await conn.execute(
            "INSERT INTO memories (scope, session_id, content, status, metadata) "
            "SELECT 'session', ?, content, 'active', metadata FROM memories "
            "WHERE session_id = ? AND scope = 'session' AND status = 'active'",
            (new_sid, source_session_id),
        )

        # slide_style_overrides (per-session deck style) — at most one row.
        await conn.execute(
            "INSERT INTO slide_style_overrides "
            "(session_id, preamble_tex, source) "
            "SELECT ?, preamble_tex, source FROM slide_style_overrides "
            "WHERE session_id = ?",
            (new_sid, source_session_id),
        )

        await conn.execute("COMMIT")
    except Exception:
        await conn.execute("ROLLBACK")
        raise

    # Deck copy (best-effort) is added in Task 2.

    return ForkResult(
        new_session_id=new_sid, forked_message=forked_text, title=new_title
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend; uv run pytest tests/test_fork.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/paperhub/db/fork.py backend/tests/test_fork.py
git commit -m "feat(fork): fork_session core slice-copy (messages/runs/papers/memories)"
```

---

## Task 2: `fork_session` best-effort deck copy

**Files:**
- Modify: `backend/src/paperhub/db/fork.py`
- Test: `backend/tests/test_fork.py`

- [ ] **Step 1: Write the failing test**

```python
# Append to backend/tests/test_fork.py

async def _seed_deck(conn, *, session_id, run_id, slides_dir: Path) -> int:
    slides_dir.mkdir(parents=True, exist_ok=True)
    (slides_dir / "deck.tex").write_text("\\documentclass{beamer}", encoding="utf-8")
    (slides_dir / "deck.pdf").write_bytes(b"%PDF-1.5 fake")
    (slides_dir / "edit_history").mkdir(exist_ok=True)
    (slides_dir / "edit_history" / "version_x.json").write_text("{}", encoding="utf-8")
    cur = await conn.execute(
        "INSERT INTO decks (session_id, run_id, tex_path, pdf_path, page_count, "
        "current_version_id, status) VALUES (?, ?, ?, ?, 2, 'version_x', 'ok')",
        (session_id, run_id, str(slides_dir / "deck.tex"), str(slides_dir / "deck.pdf")),
    )
    deck_id = int(cur.lastrowid)
    for i in range(2):
        await conn.execute(
            "INSERT INTO deck_slides (deck_id, slide_index, frame_tex, page_start, "
            "page_end) VALUES (?, ?, ?, ?, ?)",
            (deck_id, i, f"\\begin{{frame}}{{S{i}}}\\end{{frame}}", i + 1, i + 1))
    await conn.commit()
    return deck_id


async def test_fork_copies_deck_with_rewritten_paths(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await apply_schema(conn)
        await conn.execute("INSERT INTO chat_sessions (title) VALUES ('Orig')")
        await conn.commit()
        r1 = await _turn(conn, 1, "make slides", "done", routing='{"intent":"slides"}')
        src_slides = tmp_path / "chat_session" / "1" / "slides"
        await _seed_deck(conn, session_id=1, run_id=r1, slides_dir=src_slides)
        # The fork point is a LATER turn so r1 (with the deck) is copied.
        r2 = await _turn(conn, 1, "next", "ok")

        res = await fork_session(
            conn, source_session_id=1, fork_run_id=r2, workspace_dir=tmp_path)

        # Deck row copied; tex/pdf paths rewritten into the fork's own dir.
        async with conn.execute(
            "SELECT tex_path, pdf_path, page_count, current_version_id "
            "FROM decks WHERE session_id = ?", (res.new_session_id,)) as cur:
            drow = await cur.fetchone()
        assert drow is not None
        fork_slides = tmp_path / "chat_session" / str(res.new_session_id) / "slides"
        assert drow[0] == str(fork_slides / "deck.tex")
        assert drow[1] == str(fork_slides / "deck.pdf")
        assert drow[2] == 2 and drow[3] == "version_x"
        # deck_slides copied.
        async with conn.execute(
            "SELECT COUNT(*) FROM deck_slides d JOIN decks k ON k.id = d.deck_id "
            "WHERE k.session_id = ?", (res.new_session_id,)) as cur:
            assert (await cur.fetchone())[0] == 2
        # Artifacts copied to the fork's dir (incl. edit_history).
        assert (fork_slides / "deck.tex").exists()
        assert (fork_slides / "edit_history" / "version_x.json").exists()


async def test_fork_deck_artifact_failure_yields_deckless_fork(
    tmp_path: Path, monkeypatch
) -> None:
    """If copying the slides dir fails, the fork still succeeds WITHOUT a deck
    (degrade, don't dead-end)."""
    import paperhub.db.fork as fork_mod

    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(fork_mod.shutil, "copytree", _boom)

    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await apply_schema(conn)
        await conn.execute("INSERT INTO chat_sessions (title) VALUES ('Orig')")
        await conn.commit()
        r1 = await _turn(conn, 1, "make slides", "done")
        src_slides = tmp_path / "chat_session" / "1" / "slides"
        await _seed_deck(conn, session_id=1, run_id=r1, slides_dir=src_slides)
        r2 = await _turn(conn, 1, "next", "ok")

        res = await fork_session(
            conn, source_session_id=1, fork_run_id=r2, workspace_dir=tmp_path)

        # Fork exists; core slice copied; NO deck row.
        async with conn.execute(
            "SELECT COUNT(*) FROM decks WHERE session_id = ?",
            (res.new_session_id,)) as cur:
            assert (await cur.fetchone())[0] == 0
        async with conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?",
            (res.new_session_id,)) as cur:
            assert (await cur.fetchone())[0] == 2  # r1's user+assistant
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend; uv run pytest tests/test_fork.py -k deck -v`
Expected: FAIL — no deck row is copied yet (counts are 0 / paths absent).

- [ ] **Step 3: Write the implementation**

Add the imports + the `_copy_deck` helper, and call it after the core commit in `fork_session`.

At the top of `fork.py`, extend the imports:

```python
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

_LOG = logging.getLogger(__name__)
```

Add the helper (after `fork_session`):

```python
async def _copy_deck(
    conn: aiosqlite.Connection,
    *,
    source_session_id: int,
    new_session_id: int,
    workspace_dir: Path,
) -> None:
    """Best-effort: copy the source deck (decks + deck_slides rows + the whole
    slides/ artifact dir) into the fork. On ANY failure, leave the fork deckless
    — never raise, so a deck problem can't abort an otherwise-good fork."""
    async with conn.execute(
        "SELECT id, run_id, tex_path, pdf_path, speaker_notes_json, plan_json, "
        "page_count, current_version_id, contributing_paper_ids_json, status "
        "FROM decks WHERE session_id = ?",
        (source_session_id,),
    ) as cur:
        deck = await cur.fetchone()
    if deck is None:
        return  # no deck to copy

    src_slides = workspace_dir / "chat_session" / str(source_session_id) / "slides"
    dst_slides = workspace_dir / "chat_session" / str(new_session_id) / "slides"

    try:
        # Copy the artifact tree FIRST. If the source dir is missing or the
        # copy fails, bail without inserting deck rows (deckless fork).
        if not src_slides.exists():
            _LOG.warning(
                "fork: source slides dir %s missing; fork %s left deckless",
                src_slides, new_session_id,
            )
            return
        dst_slides.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_slides, dst_slides, dirs_exist_ok=True)
    except OSError as exc:
        _LOG.warning(
            "fork: deck-artifact copy failed (%r); fork %s left deckless",
            exc, new_session_id,
        )
        return

    # Rewrite the absolute tex/pdf paths to point into the fork's own dir.
    old_tex, old_pdf = deck[2], deck[3]
    new_tex = str(dst_slides / "deck.tex")
    new_pdf = (
        str(dst_slides / "deck.pdf") if old_pdf else None
    )

    await conn.execute(
        "INSERT INTO decks (session_id, run_id, tex_path, pdf_path, "
        "speaker_notes_json, plan_json, page_count, current_version_id, "
        "contributing_paper_ids_json, status) "
        "VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)",
        (new_session_id, new_tex, new_pdf, deck[4], deck[5], deck[6], deck[7],
         deck[8], deck[9]),
    )
    async with conn.execute(
        "SELECT id FROM decks WHERE session_id = ?", (new_session_id,)
    ) as cur:
        new_deck_id = int((await cur.fetchone())[0])

    await conn.execute(
        "INSERT INTO deck_slides (deck_id, slide_index, frame_tex, note_text, "
        "note_language, page_start, page_end) "
        "SELECT ?, slide_index, frame_tex, note_text, note_language, "
        "page_start, page_end FROM deck_slides WHERE deck_id = ?",
        (new_deck_id, deck[0]),
    )
    await conn.commit()
```

Then in `fork_session`, replace the `# Deck copy (best-effort) is added in Task 2.` comment with:

```python
    await _copy_deck(
        conn,
        source_session_id=source_session_id,
        new_session_id=new_sid,
        workspace_dir=workspace_dir,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend; uv run pytest tests/test_fork.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Lint + type-check the new module**

Run: `cd backend; uv run ruff check src/paperhub/db/fork.py tests/test_fork.py; uv run mypy src/paperhub/db/fork.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/paperhub/db/fork.py backend/tests/test_fork.py
git commit -m "feat(fork): best-effort deck-artifact copy into the forked session"
```

---

## Task 3: `POST /sessions/{id}/fork` endpoint

**Files:**
- Modify: `backend/src/paperhub/api/sessions.py`
- Test: `backend/tests/test_sessions_api.py`

- [ ] **Step 1: Write the failing test**

```python
# Append to backend/tests/test_sessions_api.py

async def test_fork_endpoint_creates_session_and_returns_prefill(
    sessions_client: AsyncClient, tmp_path: Path,
) -> None:
    # Build a 2-turn original session directly in the DB.
    db_path = tmp_path / "paperhub.db"
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute("INSERT INTO chat_sessions (title) VALUES ('My chat')")
        c1 = await conn.execute("INSERT INTO runs (session_id, status) VALUES (1, 'ok')")
        r1 = int(c1.lastrowid)
        await conn.execute(
            "INSERT INTO messages (session_id, role, content, run_id) "
            "VALUES (1, 'user', 'first', ?)", (r1,))
        await conn.execute(
            "INSERT INTO messages (session_id, role, content, run_id) "
            "VALUES (1, 'assistant', 'a1', ?)", (r1,))
        c2 = await conn.execute("INSERT INTO runs (session_id, status) VALUES (1, 'ok')")
        r2 = int(c2.lastrowid)
        await conn.execute(
            "INSERT INTO messages (session_id, role, content, run_id) "
            "VALUES (1, 'user', 'second', ?)", (r2,))
        await conn.execute(
            "INSERT INTO messages (session_id, role, content, run_id) "
            "VALUES (1, 'assistant', 'a2', ?)", (r2,))
        await conn.commit()

    resp = await sessions_client.post("/sessions/1/fork", json={"run_id": r2})
    assert resp.status_code == 201
    body = resp.json()
    assert body["forked_message"] == "second"
    assert body["title"] == "Fork of My chat"
    new_sid = body["session_id"]
    assert new_sid != 1

    # The fork replays via GET /sessions/{id}/messages — only the first turn.
    msgs = (await sessions_client.get(f"/sessions/{new_sid}/messages")).json()
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "first"), ("assistant", "a1")]

    # The fork is listed by GET /sessions (title <> 'New chat').
    listed = {s["id"] for s in (await sessions_client.get("/sessions")).json()}
    assert new_sid in listed


async def test_fork_endpoint_404_on_unknown_session(
    sessions_client: AsyncClient,
) -> None:
    resp = await sessions_client.post("/sessions/9999/fork", json={"run_id": 1})
    assert resp.status_code == 404


async def test_fork_endpoint_400_on_bad_run_id(
    sessions_client: AsyncClient, tmp_path: Path,
) -> None:
    db_path = tmp_path / "paperhub.db"
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("INSERT INTO chat_sessions (title) VALUES ('X')")
        await conn.commit()
    # run_id 4242 has no user message in session 1.
    resp = await sessions_client.post("/sessions/1/fork", json={"run_id": 4242})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend; uv run pytest tests/test_sessions_api.py -k fork -v`
Expected: FAIL — 404/405 (route not defined).

- [ ] **Step 3: Write the implementation**

In `backend/src/paperhub/api/sessions.py`, add the import near the top:

```python
from paperhub.db.fork import fork_session
```

Add the request/response models near `CreateSessionResponse`:

```python
class ForkSessionRequest(BaseModel):
    # The forked user message's run_id — the fork copies everything strictly
    # before that message. The frontend resolves it from the clicked user
    # message (or its paired assistant message).
    run_id: int


class ForkSessionResponse(BaseModel):
    session_id: int
    forked_message: str
    title: str
```

Add the endpoint (after `restore_session`):

```python
@router.post(
    "/sessions/{session_id}/fork",
    response_model=ForkSessionResponse,
    status_code=201,
)
async def fork_session_endpoint(
    session_id: int, req: ForkSessionRequest
) -> ForkSessionResponse:
    """Branch a NEW session from the point ABOVE a chosen user message.

    Copies every message strictly before the forked message (remapped runs),
    the session's enabled references, active session memories, and the deck
    (best-effort). The original session is untouched; the forked message text
    is returned so the frontend can prefill the composer (editable, not sent).
    """
    settings = load_settings()
    async with open_db(settings.db_path) as conn:
        async with conn.execute(
            "SELECT 1 FROM chat_sessions WHERE id = ?", (session_id,)
        ) as cur:
            if await cur.fetchone() is None:
                raise HTTPException(404, f"chat_sessions row {session_id} not found")
        try:
            result = await fork_session(
                conn,
                source_session_id=session_id,
                fork_run_id=req.run_id,
                workspace_dir=settings.workspace_dir,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return ForkSessionResponse(
        session_id=result.new_session_id,
        forked_message=result.forked_message,
        title=result.title,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend; uv run pytest tests/test_sessions_api.py -k fork -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/paperhub/api/sessions.py backend/tests/test_sessions_api.py
git commit -m "feat(fork): POST /sessions/{id}/fork endpoint"
```

---

## Task 4: First-send title re-derive for the fork placeholder

**Files:**
- Modify: `backend/src/paperhub/api/chat.py` (`_record_user_message`, lines ~290-305)
- Test: `backend/tests/test_sessions_api.py`

The fork's title is `"Fork of <orig>"`. The spec requires it to become the sent message on the first send. `_record_user_message` already promotes a `'New chat'` title from the first user message; extend the condition so a `"Fork of …"` placeholder is promoted too. It fires exactly once because the first send renames the title away from the `"Fork of "` prefix.

- [ ] **Step 1: Write the failing test**

```python
# Append to backend/tests/test_sessions_api.py
# (uses the already-imported _record_user_message, _ensure_session)

async def test_record_user_message_promotes_fork_placeholder_title(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "paperhub.db"
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await apply_schema(conn)
        await conn.execute(
            "INSERT INTO chat_sessions (title) VALUES ('Fork of My chat')")
        c = await conn.execute("INSERT INTO runs (session_id, status) VALUES (1, 'ok')")
        run_id = int(c.lastrowid)
        await conn.commit()

        await _record_user_message(conn, 1, "a brand new prompt", run_id)

        async with conn.execute(
            "SELECT title FROM chat_sessions WHERE id = 1") as cur:
            assert (await cur.fetchone())[0] == "a brand new prompt"

        # A SECOND send must NOT overwrite the now-real title.
        c2 = await conn.execute("INSERT INTO runs (session_id, status) VALUES (1, 'ok')")
        await _record_user_message(conn, 1, "follow up", int(c2.lastrowid))
        async with conn.execute(
            "SELECT title FROM chat_sessions WHERE id = 1") as cur:
            assert (await cur.fetchone())[0] == "a brand new prompt"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend; uv run pytest tests/test_sessions_api.py -k fork_placeholder -v`
Expected: FAIL — title stays `"Fork of My chat"` (the current `WHERE title = 'New chat'` guard doesn't match).

- [ ] **Step 3: Write the implementation**

In `backend/src/paperhub/api/chat.py`, change the title-promote `UPDATE` inside `_record_user_message` from:

```python
    await conn.execute(
        "UPDATE chat_sessions SET title = ? WHERE id = ? AND title = 'New chat'",
        (_derive_title(content), session_id),
    )
```

to:

```python
    # Promote the still-default title from the first user message so the
    # session is identifiable in GET /sessions across devices. Fires while the
    # title is the seed 'New chat' OR a fork placeholder ('Fork of …'); the
    # rename moves the title off both sentinels so later turns never overwrite it.
    await conn.execute(
        "UPDATE chat_sessions SET title = ? "
        "WHERE id = ? AND (title = 'New chat' OR title LIKE 'Fork of %')",
        (_derive_title(content), session_id),
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend; uv run pytest tests/test_sessions_api.py -k "fork_placeholder or fork_endpoint" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/paperhub/api/chat.py backend/tests/test_sessions_api.py
git commit -m "feat(fork): re-derive the fork placeholder title on the first send"
```

---

## Task 5: `forkSession` API client + `ForkResult` type

**Files:**
- Modify: `frontend/src/types/domain.ts`
- Modify: `frontend/src/lib/api.ts`
- Test: `frontend/src/lib/api.fork.test.ts` (create)

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/lib/api.fork.test.ts
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { forkSession } from "@/lib/api";

const server = setupServer(
  http.post("http://localhost:8000/sessions/7/fork", async ({ request }) => {
    const body = (await request.json()) as { run_id: number };
    expect(body.run_id).toBe(42);
    return HttpResponse.json(
      { session_id: 99, forked_message: "explain this", title: "Fork of X" },
      { status: 201 },
    );
  }),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("forkSession", () => {
  it("POSTs the run_id and returns the fork result", async () => {
    const res = await forkSession(7, 42);
    expect(res).toEqual({
      session_id: 99,
      forked_message: "explain this",
      title: "Fork of X",
    });
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend; npx vitest run src/lib/api.fork.test.ts`
Expected: FAIL — `forkSession` is not exported.

- [ ] **Step 3: Write the implementation**

Add to `frontend/src/types/domain.ts` (near `SessionSummary`):

```ts
/** Result of POST /sessions/{id}/fork — the new session + the forked message
 *  text to prefill into the composer (editable, not auto-sent). */
export interface ForkResult {
  session_id: number;
  forked_message: string;
  title: string;
}
```

Add to `frontend/src/lib/api.ts` — extend the type import:

```ts
import type {
  // …existing imports…
  ForkResult,
} from "@/types/domain";
```

and add the client (after `restoreBackendSession`):

```ts
/** Fork a session at a chosen user message. `runId` is that message's turn
 *  run_id; the backend copies everything strictly above it (messages, enabled
 *  references, session memories, deck) into a new session and returns the
 *  forked message text for the composer prefill. */
export async function forkSession(
  sessionId: number,
  runId: number,
): Promise<ForkResult> {
  return apiFetch<ForkResult>(`/sessions/${sessionId}/fork`, {
    method: "POST",
    body: JSON.stringify({ run_id: runId }),
  });
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend; npx vitest run src/lib/api.fork.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/domain.ts frontend/src/lib/api.ts frontend/src/lib/api.fork.test.ts
git commit -m "feat(fork): forkSession API client + ForkResult type"
```

---

## Task 6: `addForkedSession` chat-store action

**Files:**
- Modify: `frontend/src/store/chat.ts`
- Test: `frontend/src/store/chat.test.ts` (create)

The action adds the returned backend session to the local store with its `backend_session_id` set + title, selects it (so `useSessionsSync` hydrates its copied history), and returns the new local id. Messages start empty; the sync hook fills them from the DB on activation.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/store/chat.test.ts
import { beforeEach, describe, expect, it } from "vitest";

import { useChatStore } from "@/store/chat";

describe("addForkedSession", () => {
  beforeEach(() => {
    useChatStore.getState().reset();
  });

  it("adds a backend-of-record session, selects it, returns its local id", () => {
    const localId = useChatStore.getState().addForkedSession(99, "Fork of X");
    const state = useChatStore.getState();
    const sess = state.sessions.find((s) => s.id === localId);
    expect(sess).toBeDefined();
    expect(sess!.backend_session_id).toBe(99);
    expect(sess!.title).toBe("Fork of X");
    expect(sess!.messages).toEqual([]);
    expect(state.activeSessionId).toBe(localId);
  });

  it("does not duplicate when the backend id is already present", () => {
    const first = useChatStore.getState().addForkedSession(99, "Fork of X");
    const second = useChatStore.getState().addForkedSession(99, "Fork of X");
    expect(second).toBe(first);
    const count = useChatStore
      .getState()
      .sessions.filter((s) => s.backend_session_id === 99).length;
    expect(count).toBe(1);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend; npx vitest run src/store/chat.test.ts`
Expected: FAIL — `addForkedSession` is not a function.

- [ ] **Step 3: Write the implementation**

In `frontend/src/store/chat.ts`, add to the `ChatState` interface (near `newSession`):

```ts
  /** Add a session created by POST /sessions/{id}/fork: it already has a
   *  backend row (with copied history), so insert it with backend_session_id
   *  set + select it (useSessionsSync hydrates its messages on activation).
   *  Returns the local id. Idempotent on an already-present backend id. */
  addForkedSession: (backendId: number, title: string) => number;
```

Add the implementation (after `newSession`):

```ts
      addForkedSession: (backendId, title) => {
        const existing = get().sessions.find(
          (s) => s.backend_session_id === backendId,
        );
        if (existing) {
          set({ activeSessionId: existing.id });
          return existing.id;
        }
        const id = get()._nextId;
        set((s) => ({
          sessions: [
            { id, title, messages: [], backend_session_id: backendId },
            ...s.sessions,
          ],
          activeSessionId: id,
          _nextId: s._nextId + 1,
        }));
        return id;
      },
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend; npx vitest run src/store/chat.test.ts`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/store/chat.ts frontend/src/store/chat.test.ts
git commit -m "feat(fork): addForkedSession chat-store action"
```

---

## Task 7: Rewind control on user messages + ChatThread fork wiring

**Files:**
- Modify: `frontend/src/components/chat/MessageBubble.tsx`
- Modify: `frontend/src/components/chat/ChatThread.tsx`
- Test: `frontend/src/components/chat/MessageBubble.fork.test.tsx` (create)

The rewind icon (`RotateCcw`, already imported in MessageBubble) appears on hover of the user's own messages and calls `onFork`. ChatThread resolves each user message's fork `run_id` (the message's own `run_id`, falling back to the next/assistant message's), forks via the API, then adds + selects the fork and prefills the composer. When no `run_id` can be resolved (a just-sent turn whose run_id isn't assigned yet), no `onFork` is passed and the control is hidden.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/chat/MessageBubble.fork.test.tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { MessageBubble } from "@/components/chat/MessageBubble";
import type { ChatMessage } from "@/types/domain";

const userMsg: ChatMessage = { role: "user", content: "my prompt", run_id: 5 };
const asstMsg: ChatMessage = {
  role: "assistant", content: "answer", run_id: 5, status: "ok",
};

describe("MessageBubble fork control", () => {
  it("renders a rewind control on a user message when onFork is given", () => {
    render(<MessageBubble message={userMsg} onFork={vi.fn()} />);
    expect(
      screen.getByRole("button", { name: /fork|rewind|branch/i }),
    ).toBeInTheDocument();
  });

  it("does not render the rewind control on an assistant message", () => {
    render(<MessageBubble message={asstMsg} onFork={vi.fn()} />);
    expect(
      screen.queryByRole("button", { name: /fork|rewind|branch/i }),
    ).not.toBeInTheDocument();
  });

  it("does not render the rewind control without onFork", () => {
    render(<MessageBubble message={userMsg} />);
    expect(
      screen.queryByRole("button", { name: /fork|rewind|branch/i }),
    ).not.toBeInTheDocument();
  });

  it("calls onFork when clicked", async () => {
    const onFork = vi.fn();
    render(<MessageBubble message={userMsg} onFork={onFork} />);
    await userEvent.click(
      screen.getByRole("button", { name: /fork|rewind|branch/i }),
    );
    expect(onFork).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend; npx vitest run src/components/chat/MessageBubble.fork.test.tsx`
Expected: FAIL — `onFork` prop / control don't exist.

- [ ] **Step 3: Add the `onFork` prop + control to MessageBubble**

In `frontend/src/components/chat/MessageBubble.tsx`, add to `Props`:

```tsx
  /** Fork this (user) message: branch a new session from the point above it
   *  and prefill the composer with this message. Only shown on user messages. */
  onFork?: () => void;
```

Add `onFork` to the destructured params:

```tsx
export function MessageBubble({
  message,
  onRetry,
  backendSessionId,
  researching = false,
  onPrefill,
  onFork,
}: Props) {
```

Add a `showFork` flag near the other flags (after `showCopy`):

```tsx
  const showFork = isUser && !!onFork;
```

Render the control inside the outer `group/bubble` div, as a sibling of the Copy block (just before the closing `</div>` of `group/bubble`). It mirrors the Copy button's hover-reveal but anchors to the user side (bottom-left):

```tsx
        {/* Fork (rewind & resend) — hover-revealed on the user's own messages.
            RotateCcw signals "rewind to here" (Claude-Code idiom), NOT a pencil
            (which would imply destructive in-place editing). */}
        {showFork && (
          <div className="opacity-0 group-hover/bubble:opacity-100 focus-within:opacity-100 transition-opacity absolute -bottom-7 left-0 flex gap-1">
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="h-6 w-6"
              aria-label="Fork from this message"
              title="Fork from here — branch a new chat and edit this message"
              onClick={onFork}
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </Button>
          </div>
        )}
```

(`RotateCcw` and `Button` are already imported.)

- [ ] **Step 4: Run the MessageBubble test to verify it passes**

Run: `cd frontend; npx vitest run src/components/chat/MessageBubble.fork.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Wire the fork in ChatThread**

In `frontend/src/components/chat/ChatThread.tsx`:

Add imports at the top:

```tsx
import { toast } from "sonner";

import { forkSession } from "@/lib/api";
```

Add a `forkFrom` callback inside the component (after the `retryFrom` callback, before the early return):

```tsx
  const forkFrom = useCallback(
    async (runId: number) => {
      if (!session || session.backend_session_id === null) return;
      try {
        const res = await forkSession(session.backend_session_id, runId);
        const store = useChatStore.getState();
        store.addForkedSession(res.session_id, res.title);
        // Prefill the forked message — editable, NOT sent (edit = re-prompt;
        // send unchanged = retry). requestComposerText focuses the composer.
        store.requestComposerText(res.forked_message);
      } catch (err) {
        console.warn("[ChatThread] fork failed:", err);
        toast.error("Couldn't fork this message");
      }
    },
    [session],
  );
```

In the `.map`, before the `return (`, resolve the fork run_id for user messages and build the handler:

```tsx
          // A user message can fork. Its turn run_id is the message's own
          // run_id, or — for a just-sent turn not yet hydrated — the paired
          // assistant message's. Hidden when neither is known.
          let forkHandler: (() => void) | undefined;
          if (msg.role === "user" && session.backend_session_id !== null) {
            const runId = msg.run_id ?? session.messages[i + 1]?.run_id ?? null;
            if (runId !== null) {
              const captured = runId;
              forkHandler = () => void forkFrom(captured);
            }
          }
```

Pass it to the bubble:

```tsx
              <MessageBubble
                message={msg}
                onRetry={retryHandler}
                backendSessionId={session.backend_session_id}
                researching={showResearchCard || showSlideCard}
                onPrefill={requestComposerText}
                onFork={forkHandler}
              />
```

- [ ] **Step 6: Run the full frontend test files touched + typecheck/lint**

Run: `cd frontend; npx vitest run src/components/chat/MessageBubble.fork.test.tsx src/store/chat.test.ts src/lib/api.fork.test.ts; npm run typecheck; npm run lint`
Expected: PASS / clean.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/chat/MessageBubble.tsx frontend/src/components/chat/ChatThread.tsx frontend/src/components/chat/MessageBubble.fork.test.tsx
git commit -m "feat(fork): rewind control on user messages + ChatThread fork wiring"
```

---

## Task 8: Phase-end quality gates + real-API `:8000` verification

This is the plan's correctness gate (per CLAUDE.md: pytest measures mechanism, not process correctness). Run it ONCE, after Tasks 1-7 are complete.

- [ ] **Step 1: Full backend gate**

Run from `backend/`:
```powershell
uv run pytest -q
uv run ruff check src tests
uv run mypy src
```
Expected: all green.

- [ ] **Step 2: Full frontend gate**

Run from `frontend/`:
```powershell
npm test
npm run typecheck
npm run lint
npm run build
```
Expected: all green.

- [ ] **Step 3: Real-API fork scenario (requires the user's live backend on `:8000`)**

First confirm the backend is up: `curl -s -m 3 http://127.0.0.1:8000/health`. If it is NOT reachable, STOP and ask the user to start it (`scripts/start.ps1`) — do not boot your own instance.

Then, as a user would (HTTP calls the frontend makes):
1. `POST /sessions` → get `sid`.
2. `POST /papers` with an arXiv id → attach a paper to `sid`.
3. `POST /chat` with a `paper_qa` question (`session_id=sid`, real `user_message`) → read the streamed answer; note the turn's `run_id`.
4. `POST /sessions/{sid}/fork` with `{run_id: <that run_id>}` → assert `201`, capture `session_id=fork_sid` + `forked_message`.
5. Verify the copy:
   - `GET /sessions/{fork_sid}/messages` replays only the turns ABOVE the forked message.
   - `GET /papers?session_id={fork_sid}` lists the SAME paper(s) (copied references).
   - The ORIGINAL session is unchanged: `GET /sessions/{sid}/messages` identical to before.
6. **Edit-then-send (re-prompt):** `POST /chat` with `session_id=fork_sid` and an *edited* version of `forked_message`, sending the fork's copied messages as `history` → assert a grounded answer citing real chunks from the COPIED references; confirm the fork's title became the sent message (`GET /sessions` shows it, no longer "Fork of …").
7. **Send-unchanged (retry):** repeat the fork + `POST /chat` with `forked_message` verbatim → a fresh answer (a retry), original session still intact.
8. Trace-verify one forked turn from SQLite: `uv run paperhub-replay --run-id <N>` (DB at `backend/workspace/paperhub.db`) — the right stages fired with `status=ok`.

- [ ] **Step 4: Frontend visual sign-off (ask the user)**

Ask the user to open the frontend and confirm: hovering one of their own messages reveals the rewind icon; clicking it creates a new "Fork of …" chat, switches to it showing the copied history, and drops the forked message into the composer (focused, editable, NOT sent); the original chat is untouched in the sidebar.

- [ ] **Step 5: Commit any fixes surfaced by the gate**

```bash
git add -A
git commit -m "fix(fork): address issues surfaced by the real-API gate"
```

---

## Self-Review (completed during planning)

**Spec coverage** (SRS v2.30 fork entry):
- Fork (not edit-in-place), durable backend copy → Tasks 1-3.
- Copy messages strictly above the point + remapped runs (`routing_decision_json` + `search_results_json` + `deck_version_id`) → Task 1. `tool_calls` NOT copied → Task 1 (only messages/runs copied).
- Enabled references (same shared `paper_content`) → Task 1 (all `papers` rows, `enabled` preserved).
- Session-scoped memories re-scoped → Task 1 (active session memories; global untouched).
- Deck (decks + deck_slides + artifact cache copy into the fork's own dir) → Task 2; best-effort, deckless on artifact failure → Task 2.
- Forked message returned for prefill; first message → empty-history fork → Tasks 1/3.
- Frontend: rewind icon (`RotateCcw`) on user messages only → Task 7; `forkSession` client → Task 5; store wiring `addForkedSession`/`requestComposerText` (prefill, no auto-send) → Tasks 6/7; fork arrives as a real backend session kept by the strict mirror → covered by `addForkedSession` setting `backend_session_id` + `GET /sessions` listing the "Fork of …" title.
- Title: "Fork of <original>" placeholder → first send derives from the sent message → Task 4.
- Error handling: core copy atomic (BEGIN/COMMIT/ROLLBACK), deck artifact best-effort → Tasks 1/2.
- Out of scope (v1) — edit-in-place, forking assistant messages, branch-tree view, merging forks — none implemented (assistant messages get no `onFork`; Task 7).
- Testing matches the spec's named cases (slice-only copy, refs/memories/deck copied, original unchanged, replay + fresh turn, deck-artifact-failure → deckless; frontend rewind-on-user-only + create/select/prefill no-send) → Tasks 1-8.

**Type consistency:** `ForkResult` (`session_id`/`forked_message`/`title`) is identical across the backend `ForkSessionResponse`, the api client return type, and the domain interface. `fork_session` returns `ForkResult(new_session_id, forked_message, title)`; the endpoint maps `new_session_id` → response `session_id`. `addForkedSession(backendId, title)` and `requestComposerText(text)` signatures match their store definitions.

**Placeholder scan:** none — every step has concrete code/commands.
