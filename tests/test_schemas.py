"""Tests for PipelineOutput schema validation.

Verifies that @model_validator rejects invalid combinations of
action_type and populated fields, so the LLM cannot return a
FINAL_ANSWER without final_answer, etc. Combined with Phase 1
retry, these ValidationErrors trigger automatic re-prompting.
"""
import pytest
from pydantic import ValidationError

from src.rules_lawyer_bot.agent.schemas import (
    ActionType,
    ClarificationRequest,
    FinalAnswer,
    GameCandidate,
    GameIdentification,
    PipelineOutput,
    SearchProgress,
)


# ===== CLARIFICATION_NEEDED =====


def test_clarification_needed_valid():
    """CLARIFICATION_NEEDED with clarification populated is valid."""
    output = PipelineOutput(
        action_type=ActionType.CLARIFICATION_NEEDED,
        clarification=ClarificationRequest(
            question="Какая игра?", options=[], context="no game"
        ),
        stage_reasoning="user did not specify a game",
    )
    assert output.action_type == ActionType.CLARIFICATION_NEEDED


def test_clarification_needed_without_clarification_rejected():
    """CLARIFICATION_NEEDED without clarification field is rejected."""
    with pytest.raises(ValidationError, match="clarification"):
        PipelineOutput(
            action_type=ActionType.CLARIFICATION_NEEDED,
            clarification=None,
            stage_reasoning="oops",
        )


# ===== GAME_SELECTION =====


def test_game_selection_valid():
    """GAME_SELECTION with clarification AND game_identification.candidates is valid."""
    output = PipelineOutput(
        action_type=ActionType.GAME_SELECTION,
        game_identification=GameIdentification(
            candidates=[
                GameCandidate(
                    english_name="Gloomhaven",
                    pdf_filename="Gloomhaven.pdf",
                    confidence=0.9,
                )
            ],
        ),
        clarification=ClarificationRequest(
            question="Which Gloomhaven?", options=["Gloomhaven", "JotL"], context="multi"
        ),
        stage_reasoning="multiple matches",
    )
    assert output.action_type == ActionType.GAME_SELECTION


def test_game_selection_without_clarification_rejected():
    """GAME_SELECTION without clarification is rejected."""
    with pytest.raises(ValidationError, match="clarification"):
        PipelineOutput(
            action_type=ActionType.GAME_SELECTION,
            game_identification=GameIdentification(
                candidates=[
                    GameCandidate(
                        english_name="X", pdf_filename="X.pdf", confidence=0.9
                    )
                ],
            ),
            clarification=None,
            stage_reasoning="oops",
        )


def test_game_selection_without_game_identification_rejected():
    """GAME_SELECTION without game_identification is rejected."""
    with pytest.raises(ValidationError, match="game_identification"):
        PipelineOutput(
            action_type=ActionType.GAME_SELECTION,
            game_identification=None,
            clarification=ClarificationRequest(
                question="?", options=[], context=""
            ),
            stage_reasoning="oops",
        )


def test_game_selection_empty_candidates_rejected():
    """GAME_SELECTION with empty candidates list is rejected."""
    with pytest.raises(ValidationError, match="candidates"):
        PipelineOutput(
            action_type=ActionType.GAME_SELECTION,
            game_identification=GameIdentification(candidates=[]),
            clarification=ClarificationRequest(
                question="?", options=[], context=""
            ),
            stage_reasoning="oops",
        )


# ===== SEARCH_IN_PROGRESS =====


def test_search_in_progress_valid():
    """SEARCH_IN_PROGRESS with search_progress is valid."""
    output = PipelineOutput(
        action_type=ActionType.SEARCH_IN_PROGRESS,
        search_progress=SearchProgress(
            game_name="X",
            pdf_file="X.pdf",
            search_terms=["attack"],
            found_relevant=False,
            needs_more_info=True,
            additional_question="Which character?",
        ),
        stage_reasoning="need more info",
    )
    assert output.action_type == ActionType.SEARCH_IN_PROGRESS


def test_search_in_progress_without_search_progress_rejected():
    """SEARCH_IN_PROGRESS without search_progress is rejected."""
    with pytest.raises(ValidationError, match="search_progress"):
        PipelineOutput(
            action_type=ActionType.SEARCH_IN_PROGRESS,
            search_progress=None,
            stage_reasoning="oops",
        )


# ===== FINAL_ANSWER =====


def test_final_answer_valid():
    """FINAL_ANSWER with final_answer is valid (game_identification optional)."""
    output = PipelineOutput(
        action_type=ActionType.FINAL_ANSWER,
        final_answer=FinalAnswer(answer="text", confidence=0.9),
        stage_reasoning="found it",
    )
    assert output.action_type == ActionType.FINAL_ANSWER


def test_final_answer_valid_with_game_identification():
    """FINAL_ANSWER may include game_identification."""
    output = PipelineOutput(
        action_type=ActionType.FINAL_ANSWER,
        game_identification=GameIdentification(
            identified_game="Gloomhaven", pdf_file="Gloomhaven.pdf"
        ),
        final_answer=FinalAnswer(answer="text", confidence=0.9),
        stage_reasoning="found it",
    )
    assert output.final_answer.answer == "text"


def test_final_answer_without_final_answer_rejected():
    """FINAL_ANSWER without final_answer field is rejected."""
    with pytest.raises(ValidationError, match="final_answer"):
        PipelineOutput(
            action_type=ActionType.FINAL_ANSWER,
            final_answer=None,
            stage_reasoning="oops",
        )
