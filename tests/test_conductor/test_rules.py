"""Anti-drift checks between the rules text and its delivery channels."""

from __future__ import annotations

from derzug.conductor.rules import AGENT_RULES
from derzug.conductor.skill import skill_text


def test_rules_cover_the_core_workflow_contract():
    """The single-source briefing keeps its load-bearing conventions."""
    for phrase in ("wait_for_idle", "set_params", "list_widget_types", "Patch"):
        assert phrase in AGENT_RULES


def test_skill_defers_to_the_rules_tool_instead_of_duplicating_rules():
    """The skill points at get_derzug_rules; drift is prevented structurally."""
    text = skill_text()
    assert "get_derzug_rules" in text
    assert "supersedes this file" in text
    # The full briefing must not be pasted into the skill.
    assert "COMMON NODE TYPES" not in text
