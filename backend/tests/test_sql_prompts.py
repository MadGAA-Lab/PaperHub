from paperhub.llm.prompts.registry import PromptRegistry


def test_sql_planner_nudges_paper_content_id_and_title_for_listing() -> None:
    reg = PromptRegistry()
    slot = reg.get("sql_planner/v1")
    system = slot.system
    # Listing/finding queries must select attachable identity columns.
    assert "paper_content_id" in system
    assert "title" in system
    assert "listing" in system.lower() or "finding" in system.lower()
