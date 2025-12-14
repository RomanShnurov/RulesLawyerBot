"""End-to-end integration tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.main import handle_message
from src.agent.schemas import (
    ActionType,
    PipelineOutput,
    GameIdentification,
    ReasonedAnswer,
    QueryAnalysis,
    QueryType,
    SearchPlan,
    SearchResultAnalysis,
)


def create_mock_streaming_result(final_output, new_items=None):
    """Create a mock streaming result object."""
    mock_result = MagicMock()
    mock_result.final_output = final_output
    mock_result.new_items = new_items or []

    # Mock stream_events() as an async generator
    async def stream_events():
        # Yield nothing - tests don't need actual events
        return
        yield  # Make it a generator

    mock_result.stream_events = stream_events
    return mock_result


@pytest.mark.asyncio
async def test_message_handling_with_rate_limit(monkeypatch):
    """Test that rate limiting works correctly."""
    # Mock dependencies
    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_user.username = "testuser"
    mock_update.message.text = "How does combat work?"
    mock_update.effective_chat.id = 12345
    mock_update.message.reply_text = AsyncMock()

    mock_context = MagicMock()
    mock_context.bot.send_chat_action = AsyncMock()
    mock_context.bot.send_message = AsyncMock()
    mock_context.user_data = {}  # For conversation state

    # Mock the Runner.run_streamed() to avoid actual agent execution
    mock_result = create_mock_streaming_result(final_output="Test response")

    with patch("src.main.Runner.run_streamed", return_value=mock_result):
        with patch("src.main.send_long_message", new_callable=AsyncMock) as mock_send:
            # First request should succeed
            await handle_message(mock_update, mock_context)

            # Verify chat action was sent (can be called multiple times by ProgressReporter)
            assert mock_context.bot.send_chat_action.called

            # Verify message was sent
            mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_pipeline_output_final_answer():
    """Test handling of PipelineOutput with final_answer action_type."""
    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_user.username = "testuser"
    mock_update.message.text = "How does attack work in Gloomhaven?"
    mock_update.effective_chat.id = 12345
    mock_update.message.reply_text = AsyncMock()

    mock_context = MagicMock()
    mock_context.bot.send_chat_action = AsyncMock()
    mock_context.bot.send_message = AsyncMock()
    mock_context.user_data = {}

    # Create a proper PipelineOutput with final_answer
    final_answer = ReasonedAnswer(
        query_analysis=QueryAnalysis(
            original_question="How does attack work?",
            interpreted_question="Attack mechanics in Gloomhaven",
            query_type=QueryType.PROCEDURAL,
            game_name="Gloomhaven",
            primary_concepts=["attack"],
            language_detected="en",
            reasoning="Test",
        ),
        search_plan=SearchPlan(
            target_file="Gloomhaven.pdf",
            search_terms=["attack"],
            search_strategy="exact_match",
            reasoning="Test",
        ),
        primary_search_result=SearchResultAnalysis(
            search_term="attack",
            found=True,
            completeness_score=0.9,
            reasoning="Found attack rules",
        ),
        answer="Attack works by...",
        confidence=0.9,
    )

    pipeline_output = PipelineOutput(
        action_type=ActionType.FINAL_ANSWER,
        game_identification=GameIdentification(
            identified_game="Gloomhaven",
            pdf_file="Gloomhaven.pdf",
        ),
        final_answer=final_answer,
        stage_reasoning="Game identified, answer found",
    )

    mock_result = create_mock_streaming_result(final_output=pipeline_output)

    with patch("src.main.Runner.run_streamed", return_value=mock_result):
        with patch("src.main.send_long_message", new_callable=AsyncMock) as mock_send:
            await handle_message(mock_update, mock_context)

            # Verify message was sent
            mock_send.assert_called_once()
            # Check that game context was set
            assert "conv_state" in mock_context.user_data
            conv_state = mock_context.user_data["conv_state"]
            assert conv_state.current_game == "Gloomhaven"


@pytest.mark.asyncio
async def test_pipeline_output_clarification_needed():
    """Test handling of PipelineOutput with clarification_needed action_type."""
    from src.agent.schemas import ClarificationRequest

    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_user.username = "testuser"
    mock_update.message.text = "How does movement work?"
    mock_update.effective_chat.id = 12345
    mock_update.message.reply_text = AsyncMock()

    mock_context = MagicMock()
    mock_context.bot.send_chat_action = AsyncMock()
    mock_context.bot.send_message = AsyncMock()
    mock_context.user_data = {}

    # Create PipelineOutput with clarification request
    pipeline_output = PipelineOutput(
        action_type=ActionType.CLARIFICATION_NEEDED,
        clarification=ClarificationRequest(
            question="Which game are you asking about?",
            options=[],
            context="No game specified",
        ),
        stage_reasoning="Game not specified in question",
    )

    mock_result = create_mock_streaming_result(final_output=pipeline_output)

    with patch("src.main.Runner.run_streamed", return_value=mock_result):
        await handle_message(mock_update, mock_context)

        # Verify clarification was sent
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "Which game" in call_args[0][0]
