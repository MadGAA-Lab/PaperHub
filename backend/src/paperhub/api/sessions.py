"""Sessions REST surface — eager session creation.

Provides POST /sessions so the frontend can obtain a backend session_id
before the first chat turn, making the Reference Sources drawer and Library
Browser available from app load.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from paperhub.config import load_settings
from paperhub.db.connection import open_db

router = APIRouter()


class CreateSessionResponse(BaseModel):
    session_id: int


@router.post("/sessions", response_model=CreateSessionResponse, status_code=201)
async def create_session() -> CreateSessionResponse:
    """Create an empty chat_sessions row.

    Used by the frontend to eagerly obtain a backend session_id before the
    first chat turn, so the Reference Sources drawer and Library Browser are
    usable from app load.
    """
    settings = load_settings()
    async with open_db(settings.db_path) as conn:
        cur = await conn.execute("INSERT INTO chat_sessions DEFAULT VALUES")
        await conn.commit()
        session_id = cur.lastrowid
        if session_id is None:
            raise HTTPException(status_code=500, detail="session creation failed")
    return CreateSessionResponse(session_id=session_id)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: int) -> None:
    """Delete a chat session and everything tied to it.

    Foreign-key cascade chain (schema, with PRAGMA foreign_keys=ON):
      chat_sessions ─CASCADE→ papers      (membership rows for this session only)
                    ─CASCADE→ messages
                    ─CASCADE→ runs        ─CASCADE→ tool_calls
      messages.run_id is SET NULL on run delete (audit trail decouples).

    Important: `paper_content` is NOT touched — papers are deduplicated at the
    content layer and may still be referenced by other sessions.  Only the
    *membership* rows for this session are removed.
    """
    settings = load_settings()
    async with open_db(settings.db_path) as conn:
        cur = await conn.execute(
            "DELETE FROM chat_sessions WHERE id = ?", (session_id,),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, f"chat_sessions row {session_id} not found")
        await conn.commit()
