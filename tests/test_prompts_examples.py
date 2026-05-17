"""Tests for optional few-shot examples module."""
import pytest


def test_examples_dict_has_expected_keys():
    """EXAMPLES contains the four canonical examples."""
    from src.rules_lawyer_bot.agent.prompts.examples import EXAMPLES

    assert "discovery" in EXAMPLES
    assert "found_answer" in EXAMPLES
    assert "multi_game_select" in EXAMPLES
    assert "react_cycle" in EXAMPLES
    for key, val in EXAMPLES.items():
        assert isinstance(val, str), f"{key}: examples must be strings"
        assert len(val) > 0, f"{key}: example must be non-empty"


def test_render_examples_returns_markdown_section():
    """render_examples returns a markdown-formatted block."""
    from src.rules_lawyer_bot.agent.prompts.examples import render_examples

    rendered = render_examples()
    assert "## EXAMPLES" in rendered
    assert "```json" in rendered
    assert "### discovery" in rendered
    assert "### found_answer" in rendered


def test_render_examples_filters_by_keys():
    """render_examples(keys=[...]) only includes selected examples."""
    from src.rules_lawyer_bot.agent.prompts.examples import render_examples

    rendered = render_examples(keys=["discovery"])
    assert "### discovery" in rendered
    assert "### found_answer" not in rendered


def test_create_agent_with_examples_flag():
    """create_agent(with_examples=True) appends EXAMPLES to instructions."""
    from src.rules_lawyer_bot.agent.definition import create_agent

    agent_plain = create_agent()
    agent_with = create_agent(with_examples=True)

    assert isinstance(agent_plain.instructions, str)
    assert isinstance(agent_with.instructions, str)
    assert len(agent_with.instructions) > len(agent_plain.instructions)
    assert "## EXAMPLES" in agent_with.instructions


def test_create_agent_default_no_examples():
    """create_agent() without with_examples does NOT include examples."""
    from src.rules_lawyer_bot.agent.definition import create_agent

    agent = create_agent()
    assert isinstance(agent.instructions, str)
    assert "## EXAMPLES" not in agent.instructions
