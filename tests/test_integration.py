"""End-to-end integration tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.main import handle_message


@pytest.mark.asyncio
async def test_message_handling_with_rate_limit(monkeypatch):
    """Test that rate limiting works correctly."""
    # Mock dependencies
    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_user.username = "testuser"
    mock_update.message.text = "How does combat work?"
    mock_update.effective_chat.id = 12345

    mock_context = MagicMock()
    mock_context.bot.send_chat_action = AsyncMock()
    mock_context.bot.send_message = AsyncMock()

    # Mock the Runner.run() to avoid actual agent execution
    mock_result = MagicMock()
    mock_result.final_output = "Test response"
    mock_result.steps = []

    with patch("src.main.Runner.run", new_callable=AsyncMock, return_value=mock_result):
        with patch("src.main.send_long_message", new_callable=AsyncMock) as mock_send:
            # First request should succeed
            await handle_message(mock_update, mock_context)

            # Verify chat action was sent
            mock_context.bot.send_chat_action.assert_called_once()

            # Verify message was sent
            mock_send.assert_called_once()
