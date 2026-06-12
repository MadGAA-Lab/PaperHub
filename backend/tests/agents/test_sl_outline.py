from paperhub.llm.prompts.registry import PromptRegistry


def test_outline_prompt_loads_and_has_slots() -> None:
    slot = PromptRegistry().get("slides_outline/v1")
    assert slot.system.strip()
    for key in ("{task_description}", "{response_language}", "{bundles_block}", "{n_bundles}"):
        assert key in slot.user_template
