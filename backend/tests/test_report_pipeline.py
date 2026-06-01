from typing import Any

import pytest

from paperhub.agents.report_pipeline import (
    edit_preamble_block,
    edit_title_block,
    revise_tex,
)
from paperhub.llm.prompts.registry import PromptRegistry
from paperhub.tracing.tracer import Tracer


@pytest.mark.parametrize("slot", ["slides_edit_title/v1", "slides_edit_preamble/v1"])
def test_edit_block_prompt_formats_with_brace_heavy_page_block(slot: str) -> None:
    """The page-1 block fed to these prompts is full of literal LaTeX braces
    (\\begin{document}, \\begin{frame}{...}). The adapter renders the USER
    template via str.format(**vars), so the template must NOT carry unescaped
    literal braces of its own (they belong in the system block). Rendering with
    a brace-heavy page_block must not raise KeyError/IndexError."""
    tmpl = PromptRegistry().get(slot).user_template
    page_block = (
        "\\documentclass{beamer}\n\\title{T}\n\\begin{document}\n"
        "\\begin{frame}[plain]\\titlepage\\end{frame}"
    )
    rendered = tmpl.format(
        page_block=page_block, instruction="do x", response_language="English"
    )
    assert "\\begin{document}" in rendered and "do x" in rendered


class _StructAdapter:
    def __init__(self, obj: Any = None, tokens: list[str] | None = None) -> None:
        self._obj, self._tokens = obj, tokens or []

    async def structured(self, **kw: Any) -> Any:
        return self._obj

    def stream(self, **kw: Any):
        async def g():
            for t in self._tokens:
                yield t
        return g()


# --------------------------------------------------------------------------
# F4 surviving helpers (revise_tex).
# --------------------------------------------------------------------------
async def _step_tools(tracer: Tracer) -> list[str]:
    """Return the tool names recorded on tool_calls for the tracer's run."""
    async with tracer.connection.execute(
        "SELECT tool FROM tool_calls WHERE run_id = ? ORDER BY step_index",
        (tracer.run_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [r[0] for r in rows]


@pytest.mark.asyncio
async def test_revise_tex_strips_fences(fake_tracer: Tracer) -> None:
    corrected = "\\documentclass{beamer}\n\\begin{document}\\end{document}"
    out = await revise_tex(
        pdflatex_log="! Overfull \\hbox ...",
        tex="\\documentclass{beamer}",
        adapter=_StructAdapter(tokens=["```latex\n", corrected, "\n```"]),
        tracer=fake_tracer, model="m",
    )
    assert out == corrected
    assert "```" not in out
    tools = await _step_tools(fake_tracer)
    assert "report:revise" in tools


# --------------------------------------------------------------------------
# F4.2: edit_title_block + edit_preamble_block
# --------------------------------------------------------------------------
class _StreamAdapter:
    def __init__(self) -> None:
        self.slot: str | None = None

    def stream(self, *, slot: str, variables: dict[str, object], model: str):  # type: ignore[no-untyped-def]
        self.slot = slot

        async def g():
            yield "```latex\n" + str(variables["page_block"]).replace("T", "X") + "\n```"

        return g()


@pytest.mark.asyncio
async def test_edit_title_block_uses_slot_and_strips_fences(fake_tracer: Tracer) -> None:
    a = _StreamAdapter()
    out = await edit_title_block(
        adapter=a,
        tracer=fake_tracer,
        model="m",
        page_block="\\title{T}\n\\begin{document}\n\\begin{frame}[plain]\\titlepage\\end{frame}",
        instruction="rename",
        response_language="English",
    )
    assert a.slot == "slides_edit_title/v1"
    assert "```" not in out and "\\title{X}" in out


@pytest.mark.asyncio
async def test_edit_preamble_block_uses_slot(fake_tracer: Tracer) -> None:
    a = _StreamAdapter()
    out = await edit_preamble_block(
        adapter=a,
        tracer=fake_tracer,
        model="m",
        page_block="\\usetheme{default}\n\\begin{document}\n\\begin{frame}[plain]\\titlepage\\end{frame}",
        instruction="dark theme",
        response_language="English",
    )
    assert a.slot == "slides_edit_preamble/v1"
    assert "```" not in out
