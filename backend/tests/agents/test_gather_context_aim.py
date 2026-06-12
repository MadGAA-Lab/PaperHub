"""Tests for the F6.1 aim-directed and chunk-ID-surfacing extensions to gather_context.

Two new behaviours under test:
1. aim is threaded: when ``aim="..."`` is passed, the string appears in the
   user-prompt the LLM receives (i.e. we don't discard it silently).
2. chunk IDs surfaced: when the agent calls ``read_section`` during its loop,
   the chunk IDs returned by ``_read_section`` accumulate and are exposed on
   the returned ``PaperContextBundle.read_chunk_ids``.

Harness matches the existing ``test_gather_context.py`` exactly:
- ``fake_asset`` fixture for a minimal PaperAsset with one figure on disk
- ``AsyncMock`` for ``llm_acompletion``
- ``_msg_no_tool_calls`` / ``_msg_tool_call`` helpers from the same file
- ``migrated_db`` + ``fake_tracer`` from ``conftest.py``
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from paperhub.agents.gather_context import run_gather_context
from paperhub.pipelines.paper_asset import (
    EquationAsset,
    FigureAsset,
    PaperAsset,
    SectionAsset,
    write_paper_asset,
)
from paperhub.tracing.tracer import Tracer

# ---------------------------------------------------------------------------
# Shared helpers (mirror test_gather_context.py)
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_asset(tmp_path: Path) -> tuple[PaperAsset, Path]:
    """Minimal PaperAsset with one figure on disk."""
    source_dir = tmp_path
    fig_dir = source_dir / "asset" / "figures"
    fig_dir.mkdir(parents=True)
    Image.new("RGB", (1640, 920)).save(fig_dir / "fig-001.png")
    asset = PaperAsset(
        figures=[
            FigureAsset(
                id="fig-001",
                caption="An overview of the method.",
                page=1,
                section="Method",
                image_path="figures/fig-001.png",
            ),
        ],
        equations=[
            EquationAsset(id="eq-001", latex=r"\Phi = \sum a", section="Method"),
        ],
        sections=[SectionAsset(name="Method", order=1)],
    )
    write_paper_asset(asset, source_dir)
    return asset, source_dir


def _bundle_payload(*, paper_id: int, paper_idx: int) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "paper_idx": paper_idx,
        "title": "T",
        "authors": ["A"],
        "year": 2025,
        "narrative_summary": "Contribution: X. Method: Y. Results: 14% better.",
        "key_figures": [
            {
                "key": "p0-fig-001",
                "role": "overview",
                "one_line_interpretation": "An overview",
                "dimensions": {"width_px": 1640, "height_px": 920},
            }
        ],
        "key_equations": [
            {
                "latex": r"\Phi = \sum a",
                "role": "importance_score",
                "notation_legend": "Phi: score",
            }
        ],
        "section_excerpts": [],
        "paper_newcommands": [],
    }


def _msg_no_tool_calls(content: str) -> dict[str, Any]:
    return {
        "choices": [
            {"message": {"role": "assistant", "content": content, "tool_calls": []}}
        ]
    }


def _msg_tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call_{name}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(args),
                            },
                        }
                    ],
                }
            }
        ]
    }


# ---------------------------------------------------------------------------
# Test 1: aim string is threaded into the user prompt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gather_context_aim_appears_in_user_prompt(
    fake_asset: tuple[PaperAsset, Path],
    fake_tracer: Tracer,
) -> None:
    """When ``aim`` is provided, the aim string must appear in the user
    message sent to the LLM (the first acompletion call's messages list).
    """
    asset, source_dir = fake_asset
    payload = _bundle_payload(paper_id=7, paper_idx=0)
    llm = AsyncMock()
    llm.return_value = _msg_no_tool_calls(json.dumps(payload))

    aim_text = "quantitative ablation results for the encoder choice"

    await run_gather_context(
        paper_id=7,
        paper_idx=0,
        asset=asset,
        source_dir=source_dir,
        paper_title="T",
        paper_authors=["A"],
        paper_year=2025,
        paper_abstract="abs",
        paper_newcommands=[],
        conn=None,
        tracer=fake_tracer,
        model="stub",
        llm_acompletion=llm,
        aim=aim_text,
    )

    # The first (and only) acompletion call must have the aim text in the
    # user message.
    first_call_messages: list[dict[str, Any]] = llm.await_args_list[0].kwargs["messages"]
    user_content = " ".join(
        m.get("content") or ""
        for m in first_call_messages
        if m.get("role") == "user"
    )
    assert aim_text in user_content, (
        f"aim string {aim_text!r} not found in user messages: {user_content!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: aim=None (default) does not break existing behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gather_context_aim_none_no_regression(
    fake_asset: tuple[PaperAsset, Path],
    fake_tracer: Tracer,
) -> None:
    """When ``aim`` is omitted (defaults to None), the function still works
    and the bundle is returned normally.  This is the no-op / backwards-compat
    path.
    """
    asset, source_dir = fake_asset
    payload = _bundle_payload(paper_id=42, paper_idx=0)
    llm = AsyncMock()
    llm.return_value = _msg_no_tool_calls(json.dumps(payload))

    bundle = await run_gather_context(
        paper_id=42,
        paper_idx=0,
        asset=asset,
        source_dir=source_dir,
        paper_title="T",
        paper_authors=["A"],
        paper_year=2025,
        paper_abstract="abs",
        paper_newcommands=[],
        conn=None,
        tracer=fake_tracer,
        model="stub",
        llm_acompletion=llm,
        # aim not passed — must default gracefully
    )

    assert bundle.paper_id == 42
    assert bundle.paper_idx == 0
    # read_chunk_ids must default to an empty list when no sections were read
    assert bundle.read_chunk_ids == []


# ---------------------------------------------------------------------------
# Test 3: chunk IDs from read_section are surfaced on the returned bundle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gather_context_chunk_ids_surfaced(
    fake_asset: tuple[PaperAsset, Path],
    fake_tracer: Tracer,
    migrated_db,  # type: ignore[no-untyped-def]
) -> None:
    """When the agent calls ``read_section``, the chunk IDs returned by
    ``_read_section`` must appear in ``bundle.read_chunk_ids``.

    We seed the DB with two chunks in the 'Method' section, then drive the
    LLM stub to call ``read_section(name='Method')`` once, then emit the
    final bundle.  We assert the two seeded chunk IDs appear in
    ``bundle.read_chunk_ids``.
    """
    asset, source_dir = fake_asset

    # Seed paper_content + chunks so _read_section returns real IDs.
    # kind='arxiv' requires arxiv_id (schema CHECK: exactly one of arxiv_id / sha256 non-null).
    await migrated_db.execute(
        "INSERT INTO paper_content "
        "(content_key, kind, arxiv_id, title, authors_json, "
        "source_path, source_dir_path, html_path) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "arxiv:test-aim",
            "arxiv",
            "test-aim-0000.00000",
            "T",
            "[]",
            "/tmp/s.tex",
            str(source_dir),
            "/tmp/s.html",
        ),
    )
    await migrated_db.commit()
    async with migrated_db.execute("SELECT last_insert_rowid()") as cur:
        row = await cur.fetchone()
    assert row is not None
    paper_id = int(row[0])

    # Insert two chunks in the 'Method' section.
    await migrated_db.execute(
        "INSERT INTO chunks (paper_content_id, section, text, char_start, char_end) "
        "VALUES (?, ?, ?, ?, ?)",
        (paper_id, "Method", "Chunk A text", 0, 12),
    )
    await migrated_db.execute(
        "INSERT INTO chunks (paper_content_id, section, text, char_start, char_end) "
        "VALUES (?, ?, ?, ?, ?)",
        (paper_id, "Method", "Chunk B text", 13, 25),
    )
    await migrated_db.commit()

    # Fetch the IDs that were just inserted so the assertion is DB-driven.
    async with migrated_db.execute(
        "SELECT id FROM chunks WHERE paper_content_id = ? ORDER BY char_start",
        (paper_id,),
    ) as cur:
        chunk_rows = await cur.fetchall()
    expected_chunk_ids = sorted(int(r[0]) for r in chunk_rows)
    assert len(expected_chunk_ids) == 2

    payload = _bundle_payload(paper_id=paper_id, paper_idx=0)
    llm = AsyncMock()
    llm.side_effect = [
        _msg_tool_call("read_section", {"name": "Method"}),
        _msg_no_tool_calls(json.dumps(payload)),
    ]

    bundle = await run_gather_context(
        paper_id=paper_id,
        paper_idx=0,
        asset=asset,
        source_dir=source_dir,
        paper_title="T",
        paper_authors=["A"],
        paper_year=2025,
        paper_abstract="abs",
        paper_newcommands=[],
        conn=migrated_db,
        tracer=fake_tracer,
        model="stub",
        llm_acompletion=llm,
    )

    assert bundle.paper_id == paper_id
    assert sorted(bundle.read_chunk_ids) == expected_chunk_ids, (
        f"Expected chunk IDs {expected_chunk_ids!r}, "
        f"got {sorted(bundle.read_chunk_ids)!r}"
    )
