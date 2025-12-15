"""Telegram command handlers.

Implements /start, /id, /health, /debug, and /games commands.
"""

from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from src.config import settings
from src.pipeline.state import toggle_debug_mode
from src.utils.logger import logger
from src.utils.telegram_helpers import send_long_message


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command.

    Args:
        update: Telegram update object
        context: Telegram context
    """
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) started bot")

    welcome_message = f"""
Welcome, {user.first_name}!

I'm your Board Game Rules Referee. Ask me anything about your board game rules!

**How to use:**
1. Ask a question about game rules (e.g., "How does movement work in Gloomhaven?")
2. I'll search through PDF rulebooks and provide answers
3. You can ask follow-up questions - I remember our conversation!

**Commands:**
- /start - Show this welcome message
- /games - List available rulebooks (or search: /games <name>)
- /id - Get your Telegram user ID
- /debug - Toggle verbose mode (see my reasoning process)

**Tips:**
- Use game names in English (e.g., "Arkham Horror" not "Ужас Аркхэма")
- For Russian text search, I'll use smart regex patterns
- Rate limit: {settings.max_requests_per_minute} requests per minute

Type your question to get started!
""".strip()

    await update.message.reply_text(welcome_message)


async def get_my_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /id command - show user's Telegram ID.

    Args:
        update: Telegram update object
        context: Telegram context
    """
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) requested their ID")

    await update.message.reply_text(
        f"👤 Your Telegram User ID: `{user.id}`\n\n"
        f"Name: {user.first_name} {user.last_name or ''}\n"
        f"Username: @{user.username or 'N/A'}",
        parse_mode="Markdown",
    )


async def health_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /health command for monitoring (admin only).

    Args:
        update: Telegram update object
        context: Telegram context
    """
    user = update.effective_user

    # Check if user is admin
    if not settings.admin_ids or user.id not in settings.admin_ids:
        logger.warning(
            f"Unauthorized /health attempt by user {user.id} ({user.username})"
        )
        await update.message.reply_text(
            "🚫 Unauthorized. This command is restricted to administrators."
        )
        return

    # Get bot_start_time from context.bot_data (set in main.py)
    bot_start_time = context.bot_data.get("start_time", datetime.now())
    uptime = (datetime.now() - bot_start_time).total_seconds()

    await update.message.reply_text(
        f"✅ Bot is healthy\n"
        f"⏱️ Uptime: {uptime:.0f}s\n"
        f"📊 Rate limit: {settings.max_requests_per_minute} req/min\n"
        f"👤 Your User ID: {user.id}"
    )


async def toggle_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /debug command - toggle verbose reasoning output.

    When enabled, shows the full SGR reasoning chain including:
    - How the question was understood
    - What searches were performed
    - Key findings from the rulebook
    - Additional context gathered

    Args:
        update: Telegram update object
        context: Telegram context
    """
    user = update.effective_user
    new_state = toggle_debug_mode(user.id)

    logger.info(f"User {user.id} ({user.username}) toggled debug mode: {new_state}")

    if new_state:
        await update.message.reply_text(
            "🔍 *Debug mode enabled*\n\n"
            "You will now see the full reasoning chain:\n"
            "• How I understood your question\n"
            "• What searches I performed\n"
            "• Key findings from the rulebook\n"
            "• Additional context gathered\n\n"
            "Use /debug again to disable.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "🔇 *Debug mode disabled*\n\n"
            "You will now see only the answer.\n"
            "Use /debug to enable verbose output.",
            parse_mode="Markdown",
        )


async def games_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show available games with optional search query.

    Usage:
        /games              - List all available games
        /games <query>      - Search for specific game (fuzzy matching)

    Examples:
        /games
        /games wingspan
        /games gloomy       - finds "Gloomhaven"

    Args:
        update: Telegram update object
        context: Telegram context
    """
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) requested game list via /games")

    # Extract search query from command args
    query = " ".join(context.args).strip() if context.args else ""

    try:
        pdf_dir = Path(settings.pdf_storage_path)
        if not pdf_dir.exists():
            await update.message.reply_text("⚠️ PDF library not found.")
            return

        # Get all PDF filenames (without .pdf extension)
        all_games = sorted([f.stem for f in pdf_dir.glob("*.pdf")])

        if not all_games:
            await update.message.reply_text("📚 The game library is currently empty.")
            return

        # If query provided: search with fuzzy matching
        if query:
            query_lower = query.lower()

            # Exact matches first, then partial matches
            exact_matches = [g for g in all_games if query_lower == g.lower()]
            partial_matches = [
                g for g in all_games
                if query_lower in g.lower() and g not in exact_matches
            ]

            matches = exact_matches + partial_matches

            if not matches:
                # No matches found - show closest alternatives (top 3)
                # Simple heuristic: count matching characters
                def match_score(game: str) -> int:
                    game_lower = game.lower()
                    return sum(1 for c in query_lower if c in game_lower)

                suggestions = sorted(all_games, key=match_score, reverse=True)[:3]

                response = f"❌ Игра '{query}' не найдена.\n\n"
                response += "💡 Возможно, вы имели в виду:\n"
                for i, game in enumerate(suggestions, 1):
                    response += f"{i}. 📖 {game}\n"
                response += f"\n🎮 Всего игр в библиотеке: {len(all_games)}"
                response += "\n\n💬 Используйте /games для просмотра всех игр"

                await update.message.reply_text(response)
                return

            # Found matches - show them
            if len(matches) == 1:
                response = f"✅ Найдена игра: *{matches[0]}*\n\n"
                response += "💬 Можете задать любой вопрос о правилах этой игры!"
            else:
                response = f"🔍 Найдено игр: {len(matches)}\n\n"
                for i, game in enumerate(matches[:10], 1):  # Show max 10
                    response += f"{i}. 📖 {game}\n"
                if len(matches) > 10:
                    response += f"\n... и еще {len(matches) - 10} игр"

            await update.message.reply_text(response, parse_mode="Markdown")
            return

        # No query: show all games
        response = f"🎮 *Доступные игры ({len(all_games)}):*\n\n"

        for i, game in enumerate(all_games, 1):
            response += f"{i}. 📖 {game}\n"

        response += "\n💡 *Как задать вопрос:*\n"
        response += 'Просто напишите: "Как работает движение в Dead Cells?"\n\n'
        response += "🔍 *Поиск игры:*\n"
        response += "Используйте /games <название> для поиска конкретной игры"

        await send_long_message(context.bot, update.effective_chat.id, response)

    except Exception as e:
        logger.exception(f"Error in games_command: {e}")
        await update.message.reply_text("⚠️ Ошибка при получении списка игр.")
