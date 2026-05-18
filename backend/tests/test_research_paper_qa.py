"""Research Agent paper_qa streaming tests (SRS v2.3, FR-03, I-8 #3)."""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import aiosqlite
import pytest

from paperhub.agents.research import FinalOnlyMessage, paper_qa_stream
from paperhub.rag.retriever import RetrievedChunk, Retriever
from paperhub.tracing.tracer import Tracer

pytestmark = pytest.mark.asyncio


async def _make_session(conn: aiosqlite.Connection) -> int:
    await conn.execute("INSERT INTO chat_sessions DEFAULT VALUES")
    await conn.commit()
    async with conn.execute("SELECT last_insert_rowid()") as cur:
        row = await cur.fetchone()
    assert row is not None
    return int(row[0])


async def _insert_paper_with_chunks(
    conn: aiosqlite.Connection,
    *,
    session_id: int,
    arxiv_id: str,
    title: str,
    chunk_texts: list[str],
) -> tuple[int, list[int]]:
    await conn.execute(
        "INSERT INTO paper_content "
        "(content_key, kind, arxiv_id, title, authors_json, year, abstract, "
        "source_path, source_dir_path, html_path) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            f"arxiv:{arxiv_id}", "arxiv", arxiv_id, title, "[]", 2024,
            "abs", "/tmp/x.tex", "/tmp", "/tmp/x.html",
        ),
    )
    async with conn.execute("SELECT last_insert_rowid()") as cur:
        row = await cur.fetchone()
    assert row is not None
    pcid = int(row[0])
    chunk_ids: list[int] = []
    for i, txt in enumerate(chunk_texts):
        await conn.execute(
            "INSERT INTO chunks (paper_content_id, section, char_start, "
            "char_end, text) VALUES (?, ?, ?, ?, ?)",
            (pcid, "Body", i * 100, (i + 1) * 100, txt),
        )
        async with conn.execute("SELECT last_insert_rowid()") as cur:
            cr = await cur.fetchone()
        assert cr is not None
        chunk_ids.append(int(cr[0]))
    await conn.execute(
        "INSERT INTO papers (session_id, paper_content_id, enabled) "
        "VALUES (?, ?, 1)",
        (session_id, pcid),
    )
    await conn.commit()
    return pcid, chunk_ids


class _StubAdapter:
    """LlmAdapter stub whose ``stream`` yields a pre-canned token list.

    For map-reduce tests, ``token_map`` lets each slot/title combination
    return different tokens. Keys are either slot names or title strings.
    When ``token_map`` is provided and no key matches, falls back to ``tokens``.
    """

    def __init__(
        self,
        tokens: list[str],
        *,
        token_map: dict[str, list[str]] | None = None,
        latency: float = 0.0,
    ) -> None:
        self._tokens = tokens
        self._token_map = token_map or {}
        self._latency = latency
        self.last_variables: dict[str, Any] | None = None
        self.calls: list[dict[str, Any]] = []

    async def structured(self, **_: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    def stream(
        self,
        *,
        slot: str,
        variables: dict[str, Any],
        model: str,  # noqa: ARG002
        history: list[dict[str, str]] | None = None,  # noqa: ARG002
        **_: Any,
    ) -> AsyncIterator[str]:
        self.last_variables = variables
        self.calls.append({"slot": slot, "variables": dict(variables)})

        # Determine which token list to use.
        tokens: list[str]
        title = variables.get("title", "")
        if title and title in self._token_map:
            tokens = list(self._token_map[title])
        elif slot in self._token_map:
            tokens = list(self._token_map[slot])
        else:
            tokens = list(self._tokens)

        latency = self._latency

        async def _gen() -> AsyncIterator[str]:
            if latency:
                await asyncio.sleep(latency)
            for t in tokens:
                yield t

        return _gen()


# ---------------------------------------------------------------------------
# Existing tests — updated for the new resolve+join query + N=1/N>=2 split
# ---------------------------------------------------------------------------

async def test_paper_qa_streams_tokens_with_citations(
    migrated_db: aiosqlite.Connection,
    fake_tracer: Tracer,
) -> None:
    """N=2 map-reduce path: synthesizer stream must contain chunk citations
    from at least 2 distinct papers (I-8 #3)."""
    session_id = await _make_session(migrated_db)
    pcid_a, chunks_a = await _insert_paper_with_chunks(
        migrated_db, session_id=session_id, arxiv_id="2401.0001",
        title="Paper A", chunk_texts=["A1 text", "A2 text"],
    )
    pcid_b, chunks_b = await _insert_paper_with_chunks(
        migrated_db, session_id=session_id, arxiv_id="2401.0002",
        title="Paper B", chunk_texts=["B1 text"],
    )

    # Per-paper map returns one chunk each; retriever is called once per paper.
    retriever = MagicMock(spec=Retriever)
    retriever.retrieve.side_effect = [
        # First call scoped to pcid_a
        [RetrievedChunk(chunk_id=chunks_a[0], paper_content_id=pcid_a,
                        text="A1 text", score=0.9)],
        # Second call scoped to pcid_b
        [RetrievedChunk(chunk_id=chunks_b[0], paper_content_id=pcid_b,
                        text="B1 text", score=0.85)],
    ]

    # Map tokens per paper title; synthesizer gets its own tokens.
    synthesizer_tokens = [
        "Both ", "papers ", "discuss ",
        f"[chunk:{chunks_a[0]}] ", "and ", f"[chunk:{chunks_b[0]}].",
    ]
    adapter = _StubAdapter(
        tokens=synthesizer_tokens,
        token_map={
            "Paper A": [f"Paper A says [chunk:{chunks_a[0]}]."],
            "Paper B": [f"Paper B says [chunk:{chunks_b[0]}]."],
            "paper_qa_synthesize/v1": synthesizer_tokens,
        },
    )

    state = {
        "run_id": fake_tracer._run_id,  # noqa: SLF001
        "branch": "", "session_id": session_id,
        "user_message": "compare the two papers",
    }

    collected: list[str] = []
    async for tok in paper_qa_stream(
        state, adapter=adapter, tracer=fake_tracer,
        model="m", retriever=retriever, conn=migrated_db,
    ):
        collected.append(tok)

    body = "".join(collected)
    assert f"[chunk:{chunks_a[0]}]" in body
    assert f"[chunk:{chunks_b[0]}]" in body


async def test_paper_qa_no_enabled_papers_short_circuits(
    migrated_db: aiosqlite.Connection,
    fake_tracer: Tracer,
) -> None:
    """If the session has no enabled papers, yield a FinalOnlyMessage and stop —
    do NOT call the retriever or adapter."""
    session_id = await _make_session(migrated_db)
    retriever = MagicMock(spec=Retriever)
    adapter = _StubAdapter(["should not stream"])

    state = {
        "run_id": fake_tracer._run_id,  # noqa: SLF001
        "branch": "", "session_id": session_id,
        "user_message": "anything",
    }
    out: list[str | FinalOnlyMessage] = []
    async for item in paper_qa_stream(
        state, adapter=adapter, tracer=fake_tracer,
        model="m", retriever=retriever, conn=migrated_db,
    ):
        out.append(item)
    assert len(out) == 1
    assert isinstance(out[0], FinalOnlyMessage)
    assert "No references are enabled" in out[0].content
    retriever.retrieve.assert_not_called()
    assert adapter.last_variables is None


async def test_paper_qa_no_chunks_short_circuits(
    migrated_db: aiosqlite.Connection,
    fake_tracer: Tracer,
) -> None:
    """N=1 enabled paper but retriever returns no chunks → FinalOnlyMessage."""
    session_id = await _make_session(migrated_db)
    await _insert_paper_with_chunks(
        migrated_db, session_id=session_id, arxiv_id="2401.0099",
        title="Paper", chunk_texts=["text"],
    )

    retriever = MagicMock(spec=Retriever)
    retriever.retrieve.return_value = []
    adapter = _StubAdapter(["should not stream"])

    state = {
        "run_id": fake_tracer._run_id,  # noqa: SLF001
        "branch": "", "session_id": session_id,
        "user_message": "anything",
    }
    out: list[str | FinalOnlyMessage] = []
    async for item in paper_qa_stream(
        state, adapter=adapter, tracer=fake_tracer,
        model="m", retriever=retriever, conn=migrated_db,
    ):
        out.append(item)
    assert len(out) == 1
    assert isinstance(out[0], FinalOnlyMessage)
    assert "No relevant chunks" in out[0].content
    retriever.retrieve.assert_called_once()
    assert adapter.last_variables is None


# ---------------------------------------------------------------------------
# New map-reduce tests
# ---------------------------------------------------------------------------

async def test_paper_qa_map_reduce_calls_retriever_once_per_paper(
    migrated_db: aiosqlite.Connection,
    fake_tracer: Tracer,
) -> None:
    """3 papers enabled → retriever.retrieve invoked 3 times, each scoped to
    a single paper_content_id."""
    session_id = await _make_session(migrated_db)
    pcid_a, chunks_a = await _insert_paper_with_chunks(
        migrated_db, session_id=session_id, arxiv_id="2401.0010",
        title="Alpha", chunk_texts=["alpha chunk"],
    )
    pcid_b, chunks_b = await _insert_paper_with_chunks(
        migrated_db, session_id=session_id, arxiv_id="2401.0011",
        title="Beta", chunk_texts=["beta chunk"],
    )
    pcid_c, chunks_c = await _insert_paper_with_chunks(
        migrated_db, session_id=session_id, arxiv_id="2401.0012",
        title="Gamma", chunk_texts=["gamma chunk"],
    )

    retriever = MagicMock(spec=Retriever)
    retriever.retrieve.side_effect = [
        [RetrievedChunk(chunk_id=chunks_a[0], paper_content_id=pcid_a,
                        text="alpha chunk", score=0.9)],
        [RetrievedChunk(chunk_id=chunks_b[0], paper_content_id=pcid_b,
                        text="beta chunk", score=0.8)],
        [RetrievedChunk(chunk_id=chunks_c[0], paper_content_id=pcid_c,
                        text="gamma chunk", score=0.7)],
    ]

    adapter = _StubAdapter(
        tokens=["synth"],
        token_map={
            "Alpha": ["alpha analysis"],
            "Beta": ["beta analysis"],
            "Gamma": ["gamma analysis"],
        },
    )

    state = {
        "run_id": fake_tracer._run_id,  # noqa: SLF001
        "branch": "", "session_id": session_id,
        "user_message": "compare all three",
    }

    async for _ in paper_qa_stream(
        state, adapter=adapter, tracer=fake_tracer,
        model="m", retriever=retriever, conn=migrated_db,
    ):
        pass

    assert retriever.retrieve.call_count == 3

    # Each call must be scoped to exactly one paper.
    called_ids = [
        call.kwargs["enabled_paper_content_ids"]
        for call in retriever.retrieve.call_args_list
    ]
    assert all(len(ids) == 1 for ids in called_ids), (
        f"Expected single-paper scoping, got: {called_ids}"
    )
    assert {ids[0] for ids in called_ids} == {pcid_a, pcid_b, pcid_c}


async def test_paper_qa_map_reduce_runs_map_steps_in_parallel_via_gather(
    migrated_db: aiosqlite.Connection,
    fake_tracer: Tracer,
) -> None:
    """Map steps run in parallel: 3 papers × 0.2 s latency should finish in
    ~0.2 s total, not ~0.6 s (sequential)."""
    session_id = await _make_session(migrated_db)
    pcid_a, chunks_a = await _insert_paper_with_chunks(
        migrated_db, session_id=session_id, arxiv_id="2401.0020",
        title="P1", chunk_texts=["c1"],
    )
    pcid_b, chunks_b = await _insert_paper_with_chunks(
        migrated_db, session_id=session_id, arxiv_id="2401.0021",
        title="P2", chunk_texts=["c2"],
    )
    pcid_c, chunks_c = await _insert_paper_with_chunks(
        migrated_db, session_id=session_id, arxiv_id="2401.0022",
        title="P3", chunk_texts=["c3"],
    )

    retriever = MagicMock(spec=Retriever)
    retriever.retrieve.side_effect = [
        [RetrievedChunk(chunk_id=chunks_a[0], paper_content_id=pcid_a,
                        text="c1", score=0.9)],
        [RetrievedChunk(chunk_id=chunks_b[0], paper_content_id=pcid_b,
                        text="c2", score=0.8)],
        [RetrievedChunk(chunk_id=chunks_c[0], paper_content_id=pcid_c,
                        text="c3", score=0.7)],
    ]

    # Each per-paper LLM call sleeps 0.2 s; synthesizer is instant.
    adapter = _StubAdapter(
        tokens=["synth"],
        token_map={
            "P1": ["p1 analysis"],
            "P2": ["p2 analysis"],
            "P3": ["p3 analysis"],
        },
        latency=0.2,
    )

    state = {
        "run_id": fake_tracer._run_id,  # noqa: SLF001
        "branch": "", "session_id": session_id,
        "user_message": "compare all",
    }

    t0 = time.monotonic()
    async for _ in paper_qa_stream(
        state, adapter=adapter, tracer=fake_tracer,
        model="m", retriever=retriever, conn=migrated_db,
    ):
        pass
    elapsed = time.monotonic() - t0

    # Parallel: should finish in <0.5 s (generous allowance for CI overhead).
    # Sequential would be 3 × 0.2 = 0.6 s minimum.
    assert elapsed < 0.5, (
        f"Map steps appear sequential: elapsed={elapsed:.2f}s (expected <0.5s)"
    )


async def test_paper_qa_map_reduce_synthesis_streams_tokens_with_chunk_markers(
    migrated_db: aiosqlite.Connection,
    fake_tracer: Tracer,
) -> None:
    """Synthesizer output contains [chunk:N] markers from at least 2 papers."""
    session_id = await _make_session(migrated_db)
    pcid_a, chunks_a = await _insert_paper_with_chunks(
        migrated_db, session_id=session_id, arxiv_id="2401.0030",
        title="PaperX", chunk_texts=["x text"],
    )
    pcid_b, chunks_b = await _insert_paper_with_chunks(
        migrated_db, session_id=session_id, arxiv_id="2401.0031",
        title="PaperY", chunk_texts=["y text"],
    )

    retriever = MagicMock(spec=Retriever)
    retriever.retrieve.side_effect = [
        [RetrievedChunk(chunk_id=chunks_a[0], paper_content_id=pcid_a,
                        text="x text", score=0.9)],
        [RetrievedChunk(chunk_id=chunks_b[0], paper_content_id=pcid_b,
                        text="y text", score=0.8)],
    ]

    synth_tokens = [
        f"PaperX says [chunk:{chunks_a[0]}] ",
        f"while PaperY says [chunk:{chunks_b[0]}].",
    ]
    adapter = _StubAdapter(
        tokens=synth_tokens,
        token_map={
            "PaperX": ["x analysis"],
            "PaperY": ["y analysis"],
            "paper_qa_synthesize/v1": synth_tokens,
        },
    )

    state = {
        "run_id": fake_tracer._run_id,  # noqa: SLF001
        "branch": "", "session_id": session_id,
        "user_message": "how do they differ?",
    }

    collected: list[str] = []
    async for tok in paper_qa_stream(
        state, adapter=adapter, tracer=fake_tracer,
        model="m", retriever=retriever, conn=migrated_db,
    ):
        collected.append(tok)

    body = "".join(collected)
    assert f"[chunk:{chunks_a[0]}]" in body, "Expected chunk marker from PaperX"
    assert f"[chunk:{chunks_b[0]}]" in body, "Expected chunk marker from PaperY"


async def test_paper_qa_map_reduce_short_circuits_when_no_paper_has_chunks(
    migrated_db: aiosqlite.Connection,
    fake_tracer: Tracer,
) -> None:
    """When all per-paper retrievals return empty, yield FinalOnlyMessage
    and do NOT call the synthesizer."""
    session_id = await _make_session(migrated_db)
    await _insert_paper_with_chunks(
        migrated_db, session_id=session_id, arxiv_id="2401.0040",
        title="Empty A", chunk_texts=["a"],
    )
    await _insert_paper_with_chunks(
        migrated_db, session_id=session_id, arxiv_id="2401.0041",
        title="Empty B", chunk_texts=["b"],
    )

    retriever = MagicMock(spec=Retriever)
    retriever.retrieve.return_value = []

    adapter = _StubAdapter(["should not appear"])

    state = {
        "run_id": fake_tracer._run_id,  # noqa: SLF001
        "branch": "", "session_id": session_id,
        "user_message": "anything",
    }

    out: list[str | FinalOnlyMessage] = []
    async for item in paper_qa_stream(
        state, adapter=adapter, tracer=fake_tracer,
        model="m", retriever=retriever, conn=migrated_db,
    ):
        out.append(item)

    assert len(out) == 1
    assert isinstance(out[0], FinalOnlyMessage)
    assert "No relevant chunks" in out[0].content

    # The synthesizer slot must never be called.
    synth_calls = [c for c in adapter.calls if c["slot"] == "paper_qa_synthesize/v1"]
    assert synth_calls == [], f"Synthesizer should not be called; got {synth_calls}"


async def test_paper_qa_map_reduce_skipped_when_only_one_paper_enabled(
    migrated_db: aiosqlite.Connection,
    fake_tracer: Tracer,
) -> None:
    """N=1 takes the single-paper path — no map-reduce, no synthesizer call."""
    session_id = await _make_session(migrated_db)
    pcid, chunk_ids = await _insert_paper_with_chunks(
        migrated_db, session_id=session_id, arxiv_id="2401.0050",
        title="Solo Paper", chunk_texts=["solo text"],
    )

    retriever = MagicMock(spec=Retriever)
    retriever.retrieve.return_value = [
        RetrievedChunk(chunk_id=chunk_ids[0], paper_content_id=pcid,
                       text="solo text", score=0.9),
    ]

    single_tokens = [f"Solo answer [chunk:{chunk_ids[0]}]."]
    adapter = _StubAdapter(tokens=single_tokens)

    state = {
        "run_id": fake_tracer._run_id,  # noqa: SLF001
        "branch": "", "session_id": session_id,
        "user_message": "tell me about the paper",
    }

    collected: list[str] = []
    async for tok in paper_qa_stream(
        state, adapter=adapter, tracer=fake_tracer,
        model="m", retriever=retriever, conn=migrated_db,
    ):
        collected.append(tok)

    # Single-paper path: exactly one retrieve call.
    retriever.retrieve.assert_called_once()
    assert retriever.retrieve.call_args.kwargs["enabled_paper_content_ids"] == [pcid]

    # No synthesizer call — that slot is map-reduce only.
    synth_calls = [c for c in adapter.calls if c["slot"] == "paper_qa_synthesize/v1"]
    assert synth_calls == []

    # The paper_qa/v1 slot should have been used with the title variable.
    qa_calls = [c for c in adapter.calls if c["slot"] == "paper_qa/v1"]
    assert len(qa_calls) == 1
    assert qa_calls[0]["variables"]["title"] == "Solo Paper"

    body = "".join(collected)
    assert f"[chunk:{chunk_ids[0]}]" in body


async def test_paper_qa_tracer_steps_n_ge_2(
    migrated_db: aiosqlite.Connection,
    fake_tracer: Tracer,
) -> None:
    """N=2: tracer must record resolve + 2×map + synthesize steps."""
    session_id = await _make_session(migrated_db)
    pcid_a, chunks_a = await _insert_paper_with_chunks(
        migrated_db, session_id=session_id, arxiv_id="2401.0060",
        title="Tracer A", chunk_texts=["ta"],
    )
    pcid_b, chunks_b = await _insert_paper_with_chunks(
        migrated_db, session_id=session_id, arxiv_id="2401.0061",
        title="Tracer B", chunk_texts=["tb"],
    )

    retriever = MagicMock(spec=Retriever)
    retriever.retrieve.side_effect = [
        [RetrievedChunk(chunk_id=chunks_a[0], paper_content_id=pcid_a,
                        text="ta", score=0.9)],
        [RetrievedChunk(chunk_id=chunks_b[0], paper_content_id=pcid_b,
                        text="tb", score=0.8)],
    ]

    adapter = _StubAdapter(
        tokens=["synth"],
        token_map={
            "Tracer A": ["a analysis"],
            "Tracer B": ["b analysis"],
        },
    )

    state = {
        "run_id": fake_tracer._run_id,  # noqa: SLF001
        "branch": "", "session_id": session_id,
        "user_message": "compare",
    }

    async for _ in paper_qa_stream(
        state, adapter=adapter, tracer=fake_tracer,
        model="m", retriever=retriever, conn=migrated_db,
    ):
        pass

    # Read recorded tool_calls from the DB.
    async with migrated_db.execute(
        "SELECT tool FROM tool_calls WHERE run_id = ? ORDER BY step_index",
        (fake_tracer._run_id,),  # noqa: SLF001
    ) as cur:
        tools = [row[0] for row in await cur.fetchall()]

    assert "paper_qa:resolve" in tools
    assert tools.count("paper_qa:map") == 2
    assert "paper_qa:synthesize" in tools
    # No retrieve or generate steps (those are N=1 path).
    assert "paper_qa:retrieve" not in tools
    assert "paper_qa:generate" not in tools
