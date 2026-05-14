"""Optional few-shot examples for the system prompt.

These are NOT injected by default. If the LLM starts producing malformed
outputs in production, enable them via settings.enable_few_shot_examples
(see definition.create_agent).
"""

EXAMPLES: dict[str, str] = {
    "discovery": """{
  "action_type": "final_answer",
  "final_answer": {
    "answer": "🎮 In my library: 1. Dead Cells 2. Gloomhaven 3. Wingspan. Ask me anything about these games!",
    "confidence": 1.0
  },
  "stage_reasoning": "User asked for game list. Called list_directory_tree(), formatted as numbered list."
}""",
    "found_answer": """{
  "action_type": "final_answer",
  "game_identification": {
    "identified_game": "Super Fantasy Brawl",
    "pdf_file": "Super Fantasy Brawl.pdf"
  },
  "final_answer": {
    "answer": "📖 \\"Attack: spend 2 AP, choose a target in range, declare attack.\\"\\n📍 Section: Combat, Page 12\\n💡 In short: Attacking costs 2 Action Points and requires a target in range.",
    "confidence": 0.9
  },
  "stage_reasoning": "Found complete attack rules on page 12 via ugrep search."
}""",
    "multi_game_select": """{
  "action_type": "game_selection",
  "game_identification": {
    "candidates": [
      {"english_name": "Gloomhaven", "pdf_filename": "Gloomhaven.pdf", "confidence": 0.9},
      {"english_name": "Gloomhaven: Jaws of the Lion", "pdf_filename": "Gloomhaven JOTL.pdf", "confidence": 0.85}
    ]
  },
  "clarification": {
    "question": "Which Gloomhaven game?",
    "options": ["Gloomhaven", "Gloomhaven: Jaws of the Lion"],
    "context": "Multiple Gloomhaven variants in library"
  },
  "stage_reasoning": "User said 'gloomhaven' but multiple versions match."
}""",
    "react_cycle": """{
  "action_type": "final_answer",
  "final_answer": {
    "answer": "📖 \\"Brown powers activate when you play a bird.\\"\\n📍 Section: Brown Powers, Page 8",
    "confidence": 0.9
  },
  "stage_reasoning": "ACTION 1: search('коричнев|корич') → no_match (PDF is English). ACTION 2: search('brown power') → found on page 8. Adapted from Russian to English query."
}""",
}


def render_examples(keys: list[str] | None = None) -> str:
    """Render selected examples as a markdown section for prompt injection.

    Args:
        keys: List of example names to render. If None, renders all.

    Returns:
        Markdown-formatted string with EXAMPLES section header.
    """
    selected = EXAMPLES if keys is None else {k: EXAMPLES[k] for k in keys}
    lines = ["## EXAMPLES (reference, do not copy verbatim)", ""]
    for name, text in selected.items():
        lines.append(f"### {name}")
        lines.append("```json")
        lines.append(text)
        lines.append("```")
        lines.append("")
    return "\n".join(lines)
