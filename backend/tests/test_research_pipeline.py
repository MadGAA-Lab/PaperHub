"""Unit + integration tests for the v2.7 decomposed paper_search pipeline.

Each test patches ``litellm.acompletion`` and stubs ``MCPRegistry.call`` to
exercise the four stages (Parser / Discoverer / Resolver / Synthesizer)
independently and end-to-end through the subgraph.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest

from paperhub.agents.research_pipeline import (
    CanonicalIdentity,
    ParsedRequest,
    ResolvedPaper,
    discover_canonical,
    parse_user_message,
    resolve_via_ss,
    synthesize_prose,
)
from paperhub.tracing.tracer import Tracer

# ───────────────────────────── helpers ─────────────────────────────


def _msg(content: str | None = None, tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    m: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        m["tool_calls"] = tool_calls
    return {"choices": [{"message": m}]}


def _tool_call(call_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _async_completion_mock(seq: list[dict[str, Any]]) -> AsyncMock:
    return AsyncMock(side_effect=seq)


class _StubRegistry:
    """In-memory MCP registry: stub web.search + papers.search_semantic_scholar."""

    def __init__(
        self,
        web_hits: list[dict[str, Any]] | None = None,
        ss_hits: list[dict[str, Any]] | None = None,
        has_web_search: bool = True,
    ) -> None:
        self.web_hits = web_hits or []
        self.ss_hits = ss_hits or []
        self._has_web = has_web_search
        self.call_log: list[tuple[str, dict[str, Any]]] = []

    async def has_tool(self, name: str) -> bool:
        if name == "web.search":
            return self._has_web
        return True

    async def aggregate_tool_schemas(self) -> list[dict[str, Any]]:
        if self._has_web:
            return [{
                "type": "function",
                "function": {
                    "name": "web.search",
                    "description": "Web search",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }]
        return []

    async def call(self, name: str, args: dict[str, Any]) -> Any:
        self.call_log.append((name, args))
        if name == "web.search":
            return list(self.web_hits)
        if name == "papers.search_semantic_scholar":
            return list(self.ss_hits)
        raise RuntimeError(f"_StubRegistry: unknown tool {name!r}")


@pytest.fixture
async def migrated_db() -> aiosqlite.Connection:
    """In-memory SQLite with the project schema applied."""
    from paperhub.db.migrate import apply_schema

    conn = await aiosqlite.connect(":memory:")
    await apply_schema(conn)
    # Seed a chat_sessions + runs row so the tracer has a foreign key target.
    await conn.execute("INSERT INTO chat_sessions DEFAULT VALUES")
    await conn.execute(
        "INSERT INTO runs (session_id, status) VALUES (1, 'running')",
    )
    await conn.commit()
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
def fake_tracer(migrated_db: aiosqlite.Connection) -> Tracer:
    return Tracer(conn=migrated_db, run_id=1, branch="")


# ───────────────────────────── Parser ─────────────────────────────


async def test_parse_arxiv_id_shortcircuits_without_llm(
    fake_tracer: Tracer,
) -> None:
    """A message that's PURELY a pasted ID (no significant natural-
    language words around it) short-circuits without an LLM call.
    Mixed-content messages with both IDs and natural language still
    go through the LLM so any non-ID paper hints get parsed too."""
    comp = AsyncMock()
    with patch("paperhub.agents.research_pipeline.litellm.acompletion", new=comp):
        out = await parse_user_message(
            "arxiv:1706.03762",
            tracer=fake_tracer, model="m",
        )
    # Short-circuit path: zero LLM calls.
    assert comp.await_count == 0
    assert len(out) == 1
    assert out[0].kind == "arxiv_id"
    assert out[0].hint == "1706.03762"


async def test_parse_natural_language_single_paper(
    fake_tracer: Tracer,
) -> None:
    """LLM returns one ParsedRequest for a single-paper natural-language query."""
    comp = _async_completion_mock([
        _msg(content='[{"hint": "mamba paper", "kind": "natural_language"}]'),
    ])
    with patch("paperhub.agents.research_pipeline.litellm.acompletion", new=comp):
        out = await parse_user_message(
            "find the mamba paper",
            tracer=fake_tracer, model="m",
        )
    assert len(out) == 1
    assert out[0] == ParsedRequest(hint="mamba paper", kind="natural_language")


async def test_parse_multi_paper_fanout(
    fake_tracer: Tracer,
) -> None:
    """LLM returns N ParsedRequests for a multi-paper query."""
    raw = [
        {"hint": "Mamba", "kind": "natural_language"},
        {"hint": "DDPM", "kind": "natural_language"},
        {"hint": "Vaswani 2017", "kind": "natural_language"},
    ]
    comp = _async_completion_mock([_msg(content=json.dumps(raw))])
    with patch("paperhub.agents.research_pipeline.litellm.acompletion", new=comp):
        out = await parse_user_message(
            "Mamba, DDPM, and Vaswani 2017",
            tracer=fake_tracer, model="m",
        )
    assert len(out) == 3
    assert {r.hint for r in out} == {"Mamba", "DDPM", "Vaswani 2017"}


async def test_parse_empty_for_non_paper_search(
    fake_tracer: Tracer,
) -> None:
    """Parser returns [] when the message isn't a paper-search query."""
    comp = _async_completion_mock([_msg(content="[]")])
    with patch("paperhub.agents.research_pipeline.litellm.acompletion", new=comp):
        out = await parse_user_message(
            "compare these two papers",
            tracer=fake_tracer, model="m",
        )
    assert out == []


async def test_parse_tolerates_prose_around_json(
    fake_tracer: Tracer,
) -> None:
    """Parser extracts the JSON array even if the LLM wraps it in prose."""
    comp = _async_completion_mock([_msg(
        content='Here are the requests: [{"hint": "DDPM", "kind": "natural_language"}]',
    )])
    with patch("paperhub.agents.research_pipeline.litellm.acompletion", new=comp):
        out = await parse_user_message(
            "DDPM",
            tracer=fake_tracer, model="m",
        )
    assert len(out) == 1
    assert out[0].hint == "DDPM"


# ─────────────────────────── Discoverer ─────────────────────────────


async def test_discover_shortcircuits_for_arxiv_id(
    fake_tracer: Tracer,
) -> None:
    """arxiv_id / doi / quoted_title requests skip web.search entirely."""
    reg = _StubRegistry()
    out = await discover_canonical(
        ParsedRequest(hint="1706.03762", kind="arxiv_id"),
        tracer=fake_tracer, model="m", mcp_registry=reg,  # type: ignore[arg-type]
    )
    assert out is not None
    assert out.title == "1706.03762"
    assert out.confidence == "high"
    # No web.search invocations.
    assert all(name != "web.search" for name, _ in reg.call_log)


async def test_discover_natural_language_multi_angle_then_returns_identity(
    fake_tracer: Tracer,
) -> None:
    """Discoverer issues web.search, reads results, returns CanonicalIdentity."""
    reg = _StubRegistry(web_hits=[
        {"title": "Mamba: Linear-Time Sequence Modeling", "url": "https://arxiv.org/abs/2312.00752"},
    ])
    # 1) LLM responds with a tool call to web.search.
    # 2) After tool result, LLM emits canonical identity JSON.
    seq = [
        _msg(tool_calls=[_tool_call("c1", "web.search", {"query": "mamba paper foundational"})]),
        _msg(content=json.dumps({
            "title": "Mamba: Linear-Time Sequence Modeling with Selective State Spaces",
            "author_surname": "Gu",
            "year": 2023,
            "confidence": "high",
            "rationale": "Multiple hits pointed to Gu & Dao 2023.",
        })),
    ]
    comp = _async_completion_mock(seq)
    with patch("paperhub.agents.research_pipeline.litellm.acompletion", new=comp):
        out = await discover_canonical(
            ParsedRequest(hint="mamba paper", kind="natural_language"),
            tracer=fake_tracer, model="m", mcp_registry=reg,  # type: ignore[arg-type]
        )
    assert out is not None
    assert out.title.startswith("Mamba")
    assert out.year == 2023
    assert out.author_surname == "Gu"
    assert out.confidence == "high"
    # Exactly one web.search invocation logged.
    web_calls = [n for n, _ in reg.call_log if n == "web.search"]
    assert len(web_calls) == 1


async def test_discover_returns_none_when_llm_says_not_found(
    fake_tracer: Tracer,
) -> None:
    """Title=null in the canonical identity payload → returns None."""
    reg = _StubRegistry(web_hits=[])
    seq = [
        _msg(tool_calls=[_tool_call("c1", "web.search", {"query": "foo"})]),
        _msg(content='{"title": null, "reason": "no usable hits"}'),
    ]
    comp = _async_completion_mock(seq)
    with patch("paperhub.agents.research_pipeline.litellm.acompletion", new=comp):
        out = await discover_canonical(
            ParsedRequest(hint="obscure paper", kind="natural_language"),
            tracer=fake_tracer, model="m", mcp_registry=reg,  # type: ignore[arg-type]
        )
    assert out is None


async def test_discover_returns_none_when_web_not_in_registry(
    fake_tracer: Tracer,
) -> None:
    """No web.search → discover returns None without invoking the LLM."""
    reg = _StubRegistry(has_web_search=False)
    comp = AsyncMock()
    with patch("paperhub.agents.research_pipeline.litellm.acompletion", new=comp):
        out = await discover_canonical(
            ParsedRequest(hint="mamba", kind="natural_language"),
            tracer=fake_tracer, model="m", mcp_registry=reg,  # type: ignore[arg-type]
        )
    assert out is None
    assert comp.await_count == 0


# ───────────────────────────── Resolver ─────────────────────────────


async def test_resolver_calls_ss_exactly_once(
    fake_tracer: Tracer,
) -> None:
    """Resolver invokes papers.search_semantic_scholar ONCE per request.

    This is the architectural property the v2.7 refactor enforces:
    SS rate-limiting protection is structural, not a prompt rule.
    """
    reg = _StubRegistry(ss_hits=[
        {
            "paper_id": "arxiv:2312.00752",
            "title": "Mamba: Linear-Time Sequence Modeling with Selective State Spaces",
            "year": 2023,
            "authors": ["Albert Gu", "Tri Dao"],
            "arxiv_id": "2312.00752",
            "has_open_pdf": True,
        },
    ])
    identity = CanonicalIdentity(
        title="Mamba: Linear-Time Sequence Modeling with Selective State Spaces",
        author_surname="Gu", year=2023, confidence="high",
    )
    req = ParsedRequest(hint="mamba paper", kind="natural_language")
    out = await resolve_via_ss(
        req, identity, tracer=fake_tracer, mcp_registry=reg,  # type: ignore[arg-type]
    )
    assert out is not None
    assert out.paper_id == "arxiv:2312.00752"
    assert out.request is req
    assert out.identity is identity
    # Exactly one SS call — the structural invariant.
    ss_calls = [n for n, _ in reg.call_log if n == "papers.search_semantic_scholar"]
    assert len(ss_calls) == 1


async def test_resolver_returns_none_when_ss_empty(
    fake_tracer: Tracer,
) -> None:
    """SS empty → Resolver returns None; the subgraph treats this as
    'kick back to Discoverer' (or, after MAX_REFINEMENT_LOOPS, as
    NotFound)."""
    reg = _StubRegistry(ss_hits=[])
    out = await resolve_via_ss(
        ParsedRequest(hint="obscure", kind="natural_language"),
        CanonicalIdentity(title="some title", author_surname=None, year=None,
                          confidence="low"),
        tracer=fake_tracer, mcp_registry=reg,  # type: ignore[arg-type]
    )
    assert out is None
    # Still exactly one SS call attempted.
    ss_calls = [n for n, _ in reg.call_log if n == "papers.search_semantic_scholar"]
    assert len(ss_calls) == 1


# ─────────────────────────── Synthesizer ────────────────────────────


async def test_synthesizer_writes_prose_for_resolved_set(
    fake_tracer: Tracer,
) -> None:
    """Synthesizer is called with resolved + not_found context."""
    resolved = [
        ResolvedPaper(
            request=ParsedRequest(hint="mamba", kind="natural_language"),
            identity=CanonicalIdentity(
                title="Mamba", author_surname="Gu", year=2023, confidence="high"),
            paper_id="arxiv:2312.00752",
            meta={"title": "Mamba"},
        ),
    ]
    comp = _async_completion_mock([
        _msg(content="The Mamba paper by Gu & Dao (2023) introduced selective SSMs..."),
    ])
    with patch("paperhub.agents.research_pipeline.litellm.acompletion", new=comp):
        prose = await synthesize_prose(
            resolved, [],
            user_message="the mamba paper",
            tracer=fake_tracer, model="m",
        )
    assert "Mamba" in prose
    assert comp.await_count == 1


async def test_synthesizer_handles_all_not_found(
    fake_tracer: Tracer,
) -> None:
    """Empty resolved + non-empty not_found → honest 'I couldn't find'
    prose. The synthesizer prompt's contract is that it must say so AND
    ask one clarifying question."""
    not_found = [ParsedRequest(hint="quantum cucumber paper", kind="natural_language")]
    comp = _async_completion_mock([
        _msg(content=(
            "I couldn't find a clear match for 'quantum cucumber paper'. "
            "Do you have an arxiv ID or the lead author's name?"
        )),
    ])
    with patch("paperhub.agents.research_pipeline.litellm.acompletion", new=comp):
        prose = await synthesize_prose(
            [], not_found,
            user_message="find the quantum cucumber paper",
            tracer=fake_tracer, model="m",
        )
    assert "couldn't find" in prose.lower()
    assert "?" in prose  # clarifying question


# ──────────────────────── Public-API dataclass smoke ────────────────────


def test_dataclasses_serialise_via_asdict() -> None:
    """The chat layer / SSE wire shape depends on asdict() round-tripping
    cleanly for diagnostics — keep them dataclasses-compatible."""
    req = ParsedRequest(hint="mamba", kind="natural_language")
    identity = CanonicalIdentity(
        title="Mamba", author_surname="Gu", year=2023, confidence="high")
    resolved = ResolvedPaper(
        request=req, identity=identity, paper_id="arxiv:2312.00752", meta={},
    )
    d = asdict(resolved)
    assert d["paper_id"] == "arxiv:2312.00752"
    assert d["request"]["kind"] == "natural_language"
    assert d["identity"]["confidence"] == "high"
