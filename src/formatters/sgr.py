"""Schema-Guided Reasoning (SGR) output formatters for Telegram.

Implements formatting for structured agent responses with transparent,
auditable reasoning chains.
"""

from src.agent.schemas import ReasonedAnswer
from src.utils.logger import logger


def format_reasoned_answer(answer: ReasonedAnswer, verbose: bool = False) -> str:
    """Format structured SGR answer for Telegram display.

    Args:
        answer: The structured answer from the agent
        verbose: If True, include full reasoning chain (for debugging)

    Returns:
        Formatted markdown string for Telegram
    """
    parts = []

    # Main answer (always shown) - now includes direct quotes and sources
    parts.append(answer.answer)

    # Confidence indicator (only if not high confidence)
    if answer.confidence < 0.8:
        if answer.confidence >= 0.5:
            conf_emoji = "⚠️"
        else:
            conf_emoji = "❓"
        parts.append(f"\n{conf_emoji} Уверенность: {answer.confidence:.0%}")

    # Limitations (if any)
    if answer.limitations:
        limitations_text = "; ".join(answer.limitations)
        parts.append(f"\n⚠️ *Ограничения:* {limitations_text}")

    # Suggestions for follow-up questions
    if answer.suggestions:
        suggestions_text = " • ".join(answer.suggestions[:3])  # Max 3
        parts.append(f"\n💡 *См. также:* {suggestions_text}")

    # Verbose mode: show full reasoning chain
    if verbose:
        parts.append("\n\n" + "═" * 30)
        parts.append("*REASONING CHAIN*")
        parts.append("═" * 30)

        # Query Analysis
        qa = answer.query_analysis
        parts.append("\n*1. Query Analysis*")
        parts.append(f"  Type: {qa.query_type.value}")
        parts.append(f"  Game: {qa.game_name or 'Not specified'}")
        parts.append(f"  Interpreted: {qa.interpreted_question}")
        parts.append(f"  Concepts: {', '.join(qa.primary_concepts)}")
        if qa.potential_dependencies:
            parts.append(f"  Dependencies: {', '.join(qa.potential_dependencies)}")
        parts.append(f"  Reasoning: {qa.reasoning}")

        # Search Plan
        sp = answer.search_plan
        parts.append("\n*2. Search Plan*")
        parts.append(f"  File: {sp.target_file or 'To be determined'}")
        parts.append(f"  Terms: {', '.join(sp.search_terms)}")
        parts.append(f"  Strategy: {sp.search_strategy}")
        parts.append(f"  Reasoning: {sp.reasoning}")

        # Primary Search Result
        psr = answer.primary_search_result
        parts.append("\n*3. Primary Search*")
        parts.append(f"  Term: {psr.search_term}")
        parts.append(f"  Found: {'Yes' if psr.found else 'No'}")
        parts.append(f"  Completeness: {psr.completeness_score:.0%}")
        if psr.relevant_excerpts:
            excerpts = psr.relevant_excerpts[:2]  # Max 2 excerpts
            for i, excerpt in enumerate(excerpts, 1):
                truncated = excerpt[:100] + "..." if len(excerpt) > 100 else excerpt
                parts.append(f"  Excerpt {i}: {truncated}")
        if psr.referenced_concepts:
            parts.append(f"  References: {', '.join(psr.referenced_concepts)}")
        parts.append(f"  Analysis: {psr.reasoning}")

        # Follow-up Searches
        if answer.follow_up_searches:
            parts.append(
                f"\n*4. Follow-up Searches ({len(answer.follow_up_searches)})*"
            )
            for i, fs in enumerate(answer.follow_up_searches, 1):
                parts.append(f"  [{i}] {fs.concept}")
                parts.append(f"      Why: {fs.why_needed}")
                parts.append(f"      Found: {fs.found_info[:80]}...")
                parts.append(
                    f"      Useful: {'Yes' if fs.contributed_to_answer else 'No'}"
                )

    return "\n".join(parts)


def log_reasoning_chain(user_id: int, answer: ReasonedAnswer) -> None:
    """Log the full reasoning chain for debugging and analysis.

    Args:
        user_id: Telegram user ID
        answer: The structured answer from the agent
    """
    logger.info(f"[SGR] User {user_id} - Reasoning Chain:")

    # Query Analysis
    qa = answer.query_analysis
    logger.info(f"  [Query] Type: {qa.query_type.value}, Game: {qa.game_name}")
    logger.info(f"  [Query] Interpreted: {qa.interpreted_question}")
    logger.info(f"  [Query] Concepts: {qa.primary_concepts}")

    # Search Plan
    sp = answer.search_plan
    logger.info(f"  [Plan] File: {sp.target_file}, Strategy: {sp.search_strategy}")
    logger.info(f"  [Plan] Terms: {sp.search_terms}")

    # Primary Search
    psr = answer.primary_search_result
    logger.info(
        f"  [Search] Found: {psr.found}, Completeness: {psr.completeness_score:.0%}"
    )
    logger.info(f"  [Search] Referenced: {psr.referenced_concepts}")

    # Follow-ups
    if answer.follow_up_searches:
        for i, fs in enumerate(answer.follow_up_searches, 1):
            logger.info(f"  [Follow-up {i}] {fs.concept}: {fs.contributed_to_answer}")

    # Final
    logger.info(f"  [Result] Confidence: {answer.confidence:.0%}")
    logger.info(f"  [Result] Sources: {len(answer.sources)}")
    if answer.limitations:
        logger.info(f"  [Result] Limitations: {answer.limitations}")
