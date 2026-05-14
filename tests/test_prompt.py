"""Tests for the system prompt: size budget and key invariants."""
import re

import pytest

from src.rules_lawyer_bot.agent.definition import create_agent


def _get_instructions() -> str:
    """Extract the current agent instructions string."""
    agent = create_agent()
    return agent.instructions


def test_prompt_size_under_budget():
    """System prompt is at most 200 lines (target from Phase 3 spec)."""
    instructions = _get_instructions()
    line_count = instructions.count("\n") + 1
    assert line_count <= 200, f"Prompt has {line_count} lines, budget is 200"


def test_prompt_size_under_char_budget():
    """System prompt is at most 8000 characters."""
    instructions = _get_instructions()
    assert len(instructions) <= 8000, f"Prompt is {len(instructions)} chars, budget is 8000"


def test_prompt_contains_anti_hallucination_rule():
    """Anti-hallucination rule (don't fabricate tool results) is present."""
    instructions = _get_instructions().lower()
    pattern = re.compile(r"(never guess|do not guess|must call .*tool)", re.IGNORECASE)
    assert pattern.search(instructions), "anti-hallucination rule not found"


def test_prompt_contains_tool_output_sandbox_rule():
    """Tool output sandbox rule from Phase 1 is still present."""
    instructions = _get_instructions().lower()
    assert "tool_output" in instructions or "untrusted data" in instructions, (
        "tool output sandbox rule not found"
    )


def test_prompt_mentions_json_output_format():
    """Prompt mentions that search tools return JSON with page numbers."""
    instructions = _get_instructions().lower()
    assert "json" in instructions, "prompt does not mention JSON output"
    assert "page" in instructions, "prompt does not mention page numbers"


def test_prompt_no_emoji_in_instructions():
    """Instructions sections use markdown headings, not emoji.

    Emoji are allowed inside example output strings (the LLM copies them
    to the user), but not in directive sentences like 'CRITICAL'.
    """
    instructions = _get_instructions()
    danger_emoji = sum(instructions.count(c) for c in ("🚨", "⚠️"))
    assert danger_emoji <= 5, (
        f"prompt has {danger_emoji} danger emojis, budget is 5"
    )
