"""Task R1: PaperDigest + ReadRequest schema tests (F6.1-R gather rework)."""


def test_paper_digest_and_read_request() -> None:
    from paperhub.models.slide_domain import (
        DigestEquation,
        DigestSection,
        PaperDigest,
        ReadRequest,
        RoundAction,
        SeedFigure,
    )
    d = PaperDigest(
        paper_id=73, title="A Survey of X", abstract="...",
        sections=[DigestSection(name="Method", insight="Combines A and B to do C.")],
        figures=[SeedFigure(key="p0-fig-001", caption="arch")],
        key_equations=[DigestEquation(latex="x=y", role="loss")])
    assert d.sections[0].insight.startswith("Combines")
    rr = ReadRequest(paper_id=73, section_name="Method")
    ra = RoundAction(action="read", reads=[rr])
    assert ra.reads[0].section_name == "Method"
