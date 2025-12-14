"""Per-user conversation state for multi-stage pipeline UI flow.

This module provides state management for the bot-level UI flow:
- Tracking which stage of the pipeline we're in
- Storing current game context
- Managing pending clarification/selection requests

Note: This is separate from the SQLiteSession which stores
conversation history for the agent. This state manages the
Telegram UI flow (inline keyboards, pending responses).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ConversationStage(str, Enum):
    """Current stage in the multi-stage pipeline UI flow."""

    AWAITING_INPUT = "awaiting_input"
    """Normal state - waiting for user question."""

    AWAITING_GAME_SELECTION = "awaiting_game_selection"
    """Waiting for user to select a game via inline buttons."""

    AWAITING_CLARIFICATION = "awaiting_clarification"
    """Waiting for user to answer a clarification question."""


@dataclass
class ConversationState:
    """Per-user conversation state stored in context.user_data.

    This state is stored in memory and does not persist across bot restarts.
    The agent's SQLiteSession handles conversation history persistence.
    """

    stage: ConversationStage = ConversationStage.AWAITING_INPUT

    # Game context (persisted across questions within session)
    current_game: Optional[str] = None
    current_pdf: Optional[str] = None

    # Pending clarification/selection
    pending_question: Optional[str] = None
    pending_options: list[str] = field(default_factory=list)

    # For game selection callback - stores candidates for button mapping
    game_candidates: list[dict] = field(default_factory=list)

    def reset_pending(self) -> None:
        """Clear pending clarification/selection state."""
        self.stage = ConversationStage.AWAITING_INPUT
        self.pending_question = None
        self.pending_options = []
        self.game_candidates = []

    def set_game(self, game_name: str, pdf_file: str) -> None:
        """Set current game context."""
        self.current_game = game_name
        self.current_pdf = pdf_file

    def clear_game(self) -> None:
        """Clear current game context."""
        self.current_game = None
        self.current_pdf = None

    def has_game_context(self) -> bool:
        """Check if game context is available."""
        return self.current_game is not None and self.current_pdf is not None
