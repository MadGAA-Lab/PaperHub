from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from paperhub.mcp.registry import MCPRegistry


@dataclass(frozen=True)
class PromptSlot:
    system: str
    user_template: str


class PromptRegistry:
    def __init__(self) -> None:
        self._cache: dict[str, PromptSlot] = {}

    def get(self, slot: str) -> PromptSlot:
        if slot in self._cache:
            return self._cache[slot]
        name, _, version = slot.partition("/")
        if not version:
            raise ValueError(f"prompt slot must be 'name/version', got {slot!r}")
        path = files("paperhub.llm.prompts") / f"{name}_{version}.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        result = PromptSlot(system=data["system"], user_template=data["user"])
        self._cache[slot] = result
        return result


async def get_paper_search_slot(mcp_registry: MCPRegistry) -> str:
    """Return the paper_search prompt slot to use for this turn.

    Loads ``paper_search/v2`` (the discover-then-refine variant that teaches
    the agent to use ``web.search`` / ``web.fetch`` to disambiguate vague
    queries) when the MCP registry advertises ``web.search``. Falls back to
    ``paper_search/v1`` (the daemon-down variant — papers.* only) otherwise.

    The selector hinges on ``web.search`` specifically because the v2 worked
    example assumes search-first discovery; a registry advertising only
    ``web.fetch`` would let v2 mislead the agent into calling fetch with no
    URL in hand.
    """
    if await mcp_registry.has_tool("web.search"):
        return "paper_search/v2"
    return "paper_search/v1"
