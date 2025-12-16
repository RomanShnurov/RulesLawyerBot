"""Telegram command handlers.

Implements /start and /games commands.
"""

from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from src.config import settings
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
Привет, {user.first_name}!

Я — твой помощник по правилам настольных игр. Задавай любые вопросы о правилах!

**Как пользоваться:**
1. Задай вопрос о правилах (например, «Как работает движение в Gloomhaven?»)
2. Я найду ответ в PDF-рулбуках
3. Можешь задавать уточняющие вопросы — я помню контекст!

**Команды:**
- /start — Показать это сообщение
- /games — Список доступных игр (или поиск: /games <название>)

**Советы:**
- Названия игр лучше писать на английском (например, «Arkham Horror»)
- Русский текст в рулбуках тоже ищу с учётом морфологии
- Лимит: {settings.max_requests_per_minute} запросов в минуту

Напиши свой вопрос!
""".strip()

    await update.message.reply_text(welcome_message)


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
