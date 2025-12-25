"""Pydantic schemas for multi-stage conversational pipeline.

This module defines structured output types for the agent's multi-stage
pipeline that routes bot responses based on conversation state.

The main output is PipelineOutput which uses ActionType as a discriminator
to handle different stages: game selection, clarification, search, and final answer.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    """Discriminator for multi-stage pipeline output routing."""

    CLARIFICATION_NEEDED = "clarification_needed"
    """Agent needs user to clarify something (game name, question details)."""

    GAME_SELECTION = "game_selection"
    """Multiple games match - user must select one via inline buttons."""

    SEARCH_IN_PROGRESS = "search_in_progress"
    """Search ongoing, agent needs additional info from user."""

    FINAL_ANSWER = "final_answer"
    """Complete answer ready to send to user."""


class FinalAnswer(BaseModel):
    """Simplified final answer structure.

    Contains the formatted answer text with optional metadata.
    The answer should be pre-formatted following the template from agent instructions.
    """

    answer: str = Field(
        description="Complete formatted answer following the template: direct quotes, sources, explanations"
    )

    confidence: float = Field(
        ge=0,
        le=1,
        default=1.0,
        description="Confidence in answer correctness: 0=guess, 1=certain",
    )

    limitations: list[str] = Field(
        default_factory=list,
        description="Caveats, assumptions, or things user should verify",
    )

    suggestions: list[str] = Field(
        default_factory=list, description="Related questions user might want to ask"
    )


# === Multi-Stage Pipeline Schemas ===


class GameCandidate(BaseModel):
    """A candidate game found during identification."""

    english_name: str = Field(description="Game name in English")
    pdf_filename: str = Field(description="PDF file name")
    confidence: float = Field(
        ge=0, le=1, description="Match confidence: 0=unlikely, 1=exact match"
    )


class ClarificationRequest(BaseModel):
    """Request for user clarification when game is ambiguous or more info needed."""

    question: str = Field(description="Question to ask the user in their language")
    options: list[str] = Field(
        default_factory=list,
        description="Suggested options for inline buttons (max 5)",
    )
    context: str = Field(description="Why clarification is needed (for logging)")


class GameIdentification(BaseModel):
    """Result of game identification stage."""

    identified_game: Optional[str] = Field(
        default=None, description="Identified game name (English)"
    )
    pdf_file: Optional[str] = Field(default=None, description="Located PDF filename")
    candidates: list[GameCandidate] = Field(
        default_factory=list,
        description="Multiple matching games when selection needed",
    )
    from_session_context: bool = Field(
        default=False, description="True if game was inferred from session history"
    )


class SearchProgress(BaseModel):
    """Information about ongoing search when additional user input needed."""

    game_name: str = Field(description="Game being searched")
    pdf_file: str = Field(description="PDF file being searched")
    search_terms: list[str] = Field(description="Search terms used so far")
    found_relevant: bool = Field(description="Whether relevant info was found")
    needs_more_info: bool = Field(
        default=False, description="True if additional user input needed"
    )
    additional_question: Optional[str] = Field(
        default=None, description="Question to ask user for more context"
    )


class PipelineOutput(BaseModel):
    """Unified output schema for multi-stage SGR pipeline.

    Uses action_type as discriminator to route bot responses.
    This avoids Union types which can cause JSON schema issues.
    """

    # Discriminator field - determines how bot handles the output
    action_type: ActionType = Field(
        description="Type of action: clarification_needed, game_selection, search_in_progress, or final_answer"
    )

    # Stage 1: Game identification result
    game_identification: Optional[GameIdentification] = Field(
        default=None,
        description="Game identification result (populated for all action types except clarification_needed when game unknown)",
    )

    # Clarification request (when action_type is clarification_needed or game_selection)
    clarification: Optional[ClarificationRequest] = Field(
        default=None,
        description="Clarification request details (required when action_type is clarification_needed or game_selection)",
    )

    # Stage 3: Search progress (when action_type is search_in_progress)
    search_progress: Optional[SearchProgress] = Field(
        default=None,
        description="Search progress info (required when action_type is search_in_progress)",
    )

    # Stage 4: Final answer (when action_type is final_answer)
    final_answer: Optional[FinalAnswer] = Field(
        default=None,
        description="Complete formatted answer (required when action_type is final_answer)",
    )

    # Reasoning trace for debugging and logging
    stage_reasoning: str = Field(
        description="Explanation of current stage decision and next steps"
    )
