"""Telegram-specific utility functions."""
from telegram import Bot

from src.rules_lawyer_bot.utils.logger import logger


async def send_long_message(
    bot: Bot,
    chat_id: int,
    text: str,
    max_length: int = 4000
) -> None:
    """Split and send long messages to avoid Telegram's 4096 char limit.

    Splits on newlines to preserve formatting and avoid breaking code blocks.

    Args:
        bot: Telegram bot instance
        chat_id: Target chat ID
        text: Message text (may exceed 4096 chars)
        max_length: Maximum length per message (default: 4000 for safety)
    """
    if len(text) <= max_length:
        await bot.send_message(chat_id=chat_id, text=text)
        return

    # Smart splitting: preserve paragraphs and code blocks
    chunks = []
    current_chunk = ""

    for line in text.split('\n'):
        # Check if adding this line would exceed limit
        if len(current_chunk) + len(line) + 1 > max_length:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk += ('\n' if current_chunk else '') + line

    # Add remaining chunk
    if current_chunk:
        chunks.append(current_chunk)

    # Send chunks with indicators
    logger.info(f"Splitting message into {len(chunks)} parts")
    for i, chunk in enumerate(chunks, 1):
        prefix = f"[Part {i}/{len(chunks)}]\n" if len(chunks) > 1 else ""
        await bot.send_message(chat_id=chat_id, text=prefix + chunk)
