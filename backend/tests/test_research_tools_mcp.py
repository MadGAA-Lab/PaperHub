"""Task v2.5-4: research agent dispatch must flow through MCPRegistry.

After v2.5-4 the in-process `papers.*` branch in
``_dispatch_paper_search_tool_call`` is gone — every tool call is
``await registry.call(name, args)`` and the tracer step name carries
the namespaced tool name (``paper_search:papers.search_library``,
``paper_search:web.search``).

These tests stub the registry directly (no FastMCP server roundtrip)
so they exercise the dispatch wiring without needing a live transport.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from paperhub.agents.research import (
    MAX_EXTERNAL_DISCOVERY_CALLS_PER_TURN,
    FinalOnlyMessage,
    _dispatch_paper_search_tool_call,
    paper_search,
)
from paperhub.agents.research_tools import (
    LibraryHit,
    build_tool_schemas,
    find_related_papers_dispatch,
    search_library_dispatch,
    search_semantic_scholar_dispatch,
)
from paperhub.tracing.tracer import Tracer

pytestmark = pytest.mark.asyncio


class FakeRegistry:
    """Test stub matching the :class:`MCPRegistry` surface the agent uses.

    Holds canned namespaced schemas + a routing table for ``call(...)``.
    Routes ``papers.*`` straight to the in-process dispatchers when the
    test wants high-fidelity behaviour, otherwise to a hand-rolled
    callable per tool name.
    """

    def __init__(
        self,
        *,
        schemas: list[dict[str, Any]] | None = None,
        handlers: dict[str, Any] | None = None,
    ) -> None:
        self.schemas = schemas or []
        self.handlers: dict[str, Any] = handlers or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def aggregate_tool_schemas(self) -> list[dict[str, Any]]:
        return list(self.schemas)

    async def has_tool(self, name: str) -> bool:
        return any(s["function"]["name"] == name for s in self.schemas)

    async def call(self, name: str, args: dict[str, Any]) -> Any:
        self.calls.append((name, args))
        handler = self.handlers.get(name)
        if handler is None:
            raise RuntimeError(f"FakeRegistry: no handler for {name!r}")
        return await handler(**args)


def _namespaced_schema(name: str) -> dict[str, Any]:
    """Build a minimal namespaced LiteLLM tool schema dict."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "stub",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _tool_call(call_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


# ---------------------------------------------------------------------------
# build_tool_schemas: returns registry schemas verbatim
# ---------------------------------------------------------------------------


async def test_build_tool_schemas_returns_registry_schemas_verbatim() -> None:
    canned = [
        _namespaced_schema("papers.search_library"),
        _namespaced_schema("papers.search_semantic_scholar"),
        _namespaced_schema("papers.find_related_papers"),
        _namespaced_schema("web.search"),
    ]
    reg = FakeRegistry(schemas=canned)
    out = await build_tool_schemas(reg)
    assert out == canned


# ---------------------------------------------------------------------------
# _dispatch_paper_search_tool_call routes through the registry
# ---------------------------------------------------------------------------


async def test_dispatch_routes_papers_search_library_via_registry(
    migrated_db: aiosqlite.Connection, fake_tracer: Tracer,
) -> None:
    """``papers.search_library`` is routed through ``registry.call(...)``
    and its tracer step is named ``paper_search:papers.search_library``."""

    async def _fake_lib(**kwargs: Any) -> list[dict[str, Any]]:
        return [
            asdict(
                LibraryHit(
                    paper_content_id=11,
                    arxiv_id="2401.00001",
                    title="Hit",
                    abstract="abs",
                    year=2024,
                ),
            ),
        ]

    reg = FakeRegistry(handlers={"papers.search_library": _fake_lib})
    recent: dict[str, dict[str, Any]] = {}
    call = _tool_call("c1", "papers.search_library", {"query": "x"})
    result, new_count = await _dispatch_paper_search_tool_call(
        call=call,
        tracer=fake_tracer,
        conn=migrated_db,
        session_id=1,
        external_discovery_calls=0,
        recent_results=recent,
        registry=reg,
    )
    assert new_count == 0  # library search is uncapped
    assert reg.calls == [("papers.search_library", {"query": "x"})]
    assert isinstance(result, list)
    assert recent  # indexed
    # Tracer step row carries the namespaced name.
    async with migrated_db.execute(
        "SELECT tool FROM tool_calls WHERE agent='research'",
    ) as cur:
        rows = await cur.fetchall()
    tools = [r[0] for r in rows]
    assert any(t == "paper_search:papers.search_library" for t in tools)


async def test_dispatch_routes_web_search_via_registry(
    migrated_db: aiosqlite.Connection, fake_tracer: Tracer,
) -> None:
    """``web.search`` is routed through the registry, tracer-step name is
    ``paper_search:web.search``, results are NOT indexed into recent_results."""

    async def _fake_web(**kwargs: Any) -> list[dict[str, Any]]:
        return [{"url": "https://example.com", "title": "Web Hit"}]

    reg = FakeRegistry(handlers={"web.search": _fake_web})
    recent: dict[str, dict[str, Any]] = {}
    call = _tool_call("c2", "web.search", {"query": "x"})
    result, new_count = await _dispatch_paper_search_tool_call(
        call=call,
        tracer=fake_tracer,
        conn=migrated_db,
        session_id=1,
        external_discovery_calls=0,
        recent_results=recent,
        registry=reg,
    )
    # web.* IS counted under the discovery cap.
    assert new_count == 1
    assert reg.calls == [("web.search", {"query": "x"})]
    assert result == [{"url": "https://example.com", "title": "Web Hit"}]
    # web hits are not indexed (no namespaced paper_id surface).
    assert recent == {}
    async with migrated_db.execute(
        "SELECT tool FROM tool_calls WHERE agent='research'",
    ) as cur:
        rows = await cur.fetchall()
    assert any(r[0] == "paper_search:web.search" for r in rows)


async def test_dispatch_registry_error_is_translated(
    migrated_db: aiosqlite.Connection, fake_tracer: Tracer,
) -> None:
    """Errors raised inside ``registry.call`` are caught and surfaced as
    ``{"error": ..., "tool": name}`` so the loop continues."""

    async def _boom(**kwargs: Any) -> Any:
        raise RuntimeError("upstream blew up")

    reg = FakeRegistry(handlers={"papers.search_semantic_scholar": _boom})
    recent: dict[str, dict[str, Any]] = {}
    call = _tool_call("c3", "papers.search_semantic_scholar", {"query": "x"})
    result, _new_count = await _dispatch_paper_search_tool_call(
        call=call,
        tracer=fake_tracer,
        conn=migrated_db,
        session_id=1,
        external_discovery_calls=0,
        recent_results=recent,
        registry=reg,
    )
    assert isinstance(result, dict)
    assert result["error"] == "upstream blew up"
    assert result["tool"] == "papers.search_semantic_scholar"


# ---------------------------------------------------------------------------
# Cap: papers.search_semantic_scholar + web.* combined, capped at the
# module-level MAX_EXTERNAL_DISCOVERY_CALLS_PER_TURN (raised 3 → 10 in
# v2.6 to support the multi-paper fan-out pipeline).
# ---------------------------------------------------------------------------


async def test_cap_blocks_past_limit_mix_ss_then_web(
    migrated_db: aiosqlite.Connection, fake_tracer: Tracer,
) -> None:
    """A mix of papers.search_semantic_scholar + web.search up to the cap
    is allowed; the call past the cap is rejected with the cap error."""

    async def _empty(**kwargs: Any) -> list[dict[str, Any]]:
        return []

    reg = FakeRegistry(
        handlers={
            "papers.search_semantic_scholar": _empty,
            "web.search": _empty,
        },
    )
    cap = MAX_EXTERNAL_DISCOVERY_CALLS_PER_TURN
    # First cap calls: 1 SS + (cap - 1) web.search. Then one more web
    # past the cap must be rejected.
    sequence: list[tuple[str, str]] = [("papers.search_semantic_scholar", "ssA")]
    sequence.extend(("web.search", f"w{i}") for i in range(1, cap))
    sequence.append(("web.search", "wOver"))

    recent: dict[str, dict[str, Any]] = {}
    count = 0
    for idx, (name, q) in enumerate(sequence):
        call = _tool_call(f"c{idx}", name, {"query": q})
        result, count = await _dispatch_paper_search_tool_call(
            call=call, tracer=fake_tracer, conn=migrated_db, session_id=1,
            external_discovery_calls=count,
            recent_results=recent, registry=reg,
        )
        if idx < cap:
            assert not (
                isinstance(result, dict)
                and result.get("error", "").startswith("external_discovery")
            )
        else:
            assert isinstance(result, dict)
            assert result["error"] == "external_discovery_call_cap_reached"
            assert result["cap"] == cap


async def test_cap_blocks_past_limit_ss_heavy(
    migrated_db: aiosqlite.Connection, fake_tracer: Tracer,
) -> None:
    """Cap-1 papers.search_semantic_scholar + 1 web.search uses the full
    budget; the next call (whatever flavour) is rejected with the cap error."""

    async def _empty(**kwargs: Any) -> list[dict[str, Any]]:
        return []

    reg = FakeRegistry(
        handlers={
            "papers.search_semantic_scholar": _empty,
            "web.search": _empty,
        },
    )
    cap = MAX_EXTERNAL_DISCOVERY_CALLS_PER_TURN
    sequence: list[tuple[str, str]] = [
        ("papers.search_semantic_scholar", f"q{i}") for i in range(cap - 1)
    ]
    sequence.append(("web.search", "w1"))
    sequence.append(("web.search", "wOver"))

    recent: dict[str, dict[str, Any]] = {}
    count = 0
    for idx, (name, q) in enumerate(sequence):
        call = _tool_call(f"c{idx}", name, {"query": q})
        result, count = await _dispatch_paper_search_tool_call(
            call=call, tracer=fake_tracer, conn=migrated_db, session_id=1,
            external_discovery_calls=count,
            recent_results=recent, registry=reg,
        )
        if idx < cap:
            assert not (
                isinstance(result, dict)
                and result.get("error", "").startswith("external_discovery")
            )
        else:
            assert isinstance(result, dict)
            assert result["error"] == "external_discovery_call_cap_reached"


async def test_cap_does_not_count_papers_search_library(
    migrated_db: aiosqlite.Connection, fake_tracer: Tracer,
) -> None:
    """``papers.search_library`` is uncapped — call it 10 times, all pass."""

    async def _empty(**_: Any) -> list[dict[str, Any]]:
        return []

    reg = FakeRegistry(handlers={"papers.search_library": _empty})
    recent: dict[str, dict[str, Any]] = {}
    count = 0
    for idx in range(10):
        call = _tool_call(f"c{idx}", "papers.search_library", {"query": "x"})
        result, count = await _dispatch_paper_search_tool_call(
            call=call, tracer=fake_tracer, conn=migrated_db, session_id=1,
            external_discovery_calls=count, recent_results=recent, registry=reg,
        )
        assert not (isinstance(result, dict) and result.get("error", "").startswith("external_discovery"))
    # Counter never advanced.
    assert count == 0


async def test_cap_does_not_count_papers_find_related_papers(
    migrated_db: aiosqlite.Connection, fake_tracer: Tracer,
) -> None:
    """``papers.find_related_papers`` is uncapped — precise citation-graph
    navigation, not free-text search."""

    async def _empty(**_: Any) -> list[dict[str, Any]]:
        return []

    reg = FakeRegistry(handlers={"papers.find_related_papers": _empty})
    recent: dict[str, dict[str, Any]] = {}
    count = 0
    for idx in range(8):
        call = _tool_call(
            f"c{idx}", "papers.find_related_papers",
            {"paper_id": "arxiv:1", "mode": "cited_by"},
        )
        result, count = await _dispatch_paper_search_tool_call(
            call=call, tracer=fake_tracer, conn=migrated_db, session_id=1,
            external_discovery_calls=count, recent_results=recent, registry=reg,
        )
        assert not (isinstance(result, dict) and result.get("error", "").startswith("external_discovery"))
    assert count == 0


# ---------------------------------------------------------------------------
# paper_search facade routes through registry too
# ---------------------------------------------------------------------------


async def test_paper_search_facade_routes_via_registry(
    migrated_db: aiosqlite.Connection,
    fake_tracer: Tracer,
    fake_pipeline: MagicMock,
) -> None:
    """End-to-end: paper_search facade dispatches through the injected
    registry and the LLM sees namespaced tools."""

    async def _fake_lib(**kwargs: Any) -> list[dict[str, Any]]:
        return [
            asdict(
                LibraryHit(
                    paper_content_id=99,
                    arxiv_id="2401.00001",
                    title="Hit",
                    abstract="abs",
                    year=2024,
                ),
            ),
        ]

    reg = FakeRegistry(
        schemas=[_namespaced_schema("papers.search_library")],
        handlers={"papers.search_library": _fake_lib},
    )

    seq = [
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            _tool_call(
                                "c1", "papers.search_library", {"query": "x"},
                            ),
                        ],
                    },
                },
            ],
        },
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            "Found it.\n\n```json:candidates\n"
                            + json.dumps(
                                [{"paper_id": "library:99", "reason": "r"}],
                            )
                            + "\n```"
                        ),
                    },
                },
            ],
        },
    ]
    comp = AsyncMock(side_effect=seq)

    async with migrated_db.execute("SELECT id FROM runs LIMIT 1") as cur:
        row = await cur.fetchone()
    assert row is not None
    run_id = int(row[0])
    state = {
        "run_id": run_id,
        "branch": "",
        "session_id": 1,
        "user_message": "find papers",
    }
    items: list[Any] = []
    with patch("paperhub.agents.research.litellm.acompletion", new=comp):
        async for item in paper_search(
            state, adapter=None, tracer=fake_tracer,
            model="m", conn=migrated_db, pipeline=fake_pipeline,
            mcp_registry=reg,
        ):
            items.append(item)

    final = next(i for i in items if isinstance(i, FinalOnlyMessage))
    assert "Found it." in final.content
    # The registry was actually used.
    assert reg.calls == [("papers.search_library", {"query": "x"})]
    # Plan step records the namespaced tool name in the tool palette
    # (sanity: LLM call had tools=[...namespaced...]).
    call_args = comp.await_args_list[0]
    tools = call_args.kwargs["tools"]
    assert tools == [_namespaced_schema("papers.search_library")]


# Compatibility imports keep the dispatcher functions reachable from tests
# even though the facade no longer calls them directly.
_ = (search_library_dispatch, search_semantic_scholar_dispatch, find_related_papers_dispatch)
