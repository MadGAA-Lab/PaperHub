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
