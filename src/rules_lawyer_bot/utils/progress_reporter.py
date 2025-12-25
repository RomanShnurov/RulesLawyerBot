"""Progress reporting for streaming agent execution.

Provides visual feedback to users during agent tool execution
by sending and updating a single Telegram message.
"""

import random
import time
from typing import Optional

from telegram import Bot, Message

from src.rules_lawyer_bot.utils.logger import logger


TOOL_STATUS_MESSAGES = {
    "list_directory_tree": [
        # Структура / Карта / Опись
        "📚 Гоблин-архивариус проводит инвентаризацию...",
        "🏰 Картограф зарисовывает план подземелья...",
        "🕯️ Освещаю факелом темные углы архива...",
        "📜 Пересчитываю свитки в королевской казне...",
        "🧹 Мимик притворяется папкой с документами...", # Немного юмора
        "👀 Бехолдер осматривает владения...",
        "🧝 Эльф-следопыт изучает местность...",
    ],
    "search_filenames": [
        # Поиск конкретного / Охота
        "🏹 Охотник взял след нужного файла...",
        "🔮 Палантир показывает скрытое...",
        "🧭 Компас Джека Воробья крутится...", # Если уместна поп-культура
        "🐺 Ведьмак ищет следы чудовища...",
        "🧙‍♂️ Гендальф: 'Я ищу того, кто понесет кольцо'...",
        "💎 Гном простукивает стены в поисках жилы...",
        "🐕 Призвал фамильяра для поиска...",
    ],
    "search_inside_file_ugrep": [
        # Глубокий анализ / Расшифровка / Grep
        "🏺 Археолог сдувает пыль с древних рун...",
        "🧐 Мейстер расшифровывает валирийский текст...",
        "⛏️ Дворфы копают слишком жадно и глубоко...", # Классика LOTR
        "✨ Расколдовываю невидимые чернила...",
        "👁️ Всевидящее око сканирует манускрипт...",
        "🧪 Алхимик выделяет суть из текста...",
        "🧩 Мудрец собирает мозаику истины...",
    ],
    "read_full_document": [
        # Чтение / Загрузка знаний
        "🧠 Поглощаю знания древних...",
        "📖 Волшебник запоминает заклинание 9-го уровня...",
        "🕰️ Летописец вносит данные в хроники...",
        "🧛 Граф перечитывает договор купли-продажи...",
        "📜 Бард разучивает новую балладу...",
        "🌌 Медитация для восполнения маны...",
        "🦉 Сова принесла письмо из Хогвартса...",
    ],
}

# Fallback for unknown tools
FALLBACK_STATUSES = [
    "🎲 Кидаю кубик на удачу (d20)...",
    "🐲 Здесь водятся драконы...",
    "⚔️ Полирую меч перед битвой...",
    "🌀 Портал открывается, ждите...",
    "🍺 Тавернщик протирает стаканы...", # Вместо цирка лучше таверна
    "☠️ Некромант поднимает... процессы...",
]

class ProgressReporter:
    """Manages progress message updates during streaming agent execution.

    Sends a single message that gets updated as tools are called,
    then deletes it after the final response is sent.
    """

    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        min_update_interval: float = 1.0,
    ):
        """Initialize progress reporter.

        Args:
            bot: Telegram bot instance
            chat_id: Chat ID to send messages to
            min_update_interval: Minimum seconds between message updates (debounce)
        """
        self.bot = bot
        self.chat_id = chat_id
        self.min_update_interval = min_update_interval

        self.progress_message: Optional[Message] = None
        self.current_status: str = ""
        self.last_update_time: float = 0
        self.last_sent_text: str = ""

    def _format_status(self) -> str:
        """Get current status message.

        Returns:
            Current status or default message
        """
        return self.current_status or "🔍 Обрабатываю запрос..."

    def _get_random_status(self, tool_name: str) -> str:
        """Get a random fun status message for the tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Random status message
        """
        statuses = TOOL_STATUS_MESSAGES.get(tool_name, FALLBACK_STATUSES)
        return random.choice(statuses)

    async def report_tool_call(self, tool_name: str, args: Optional[dict] = None) -> None:
        """Report that a tool is being called.

        Args:
            tool_name: Name of the tool being called
            args: Tool arguments (optional, for context)
        """
        # Get random fun status
        status = self._get_random_status(tool_name)

        # Add context from args if available (append to fun status)
        if args:
            if tool_name == "search_filenames" and "query" in args:
                query = args["query"]
                if len(query) > 20:
                    query = query[:17] + "..."
                status = f"{status[:-3]} «{query}»..."
            elif tool_name == "search_inside_file_ugrep":
                filename = args.get("filename", "")
                if filename:
                    short_name = filename.split("/")[-1].replace(".pdf", "")
                    if len(short_name) > 25:
                        short_name = short_name[:22] + "..."
                    status = f"{status[:-3]} ({short_name})..."
            elif tool_name == "read_full_document":
                filename = args.get("filename", "")
                if filename:
                    short_name = filename.split("/")[-1].replace(".pdf", "")
                    if len(short_name) > 25:
                        short_name = short_name[:22] + "..."
                    status = f"{status[:-3]} ({short_name})..."

        self.current_status = status
        await self._update_message()

    async def report_tool_result(self, tool_name: str, success: bool = True) -> None:
        """Report tool execution result.

        Args:
            tool_name: Name of the tool
            success: Whether the tool succeeded
        """
        # Update current status with result indicator
        if self.current_status:
            if success:
                self.current_status = f"{self.current_status} ✓"
            else:
                self.current_status = f"{self.current_status} ✗"
            await self._update_message()

    async def _update_message(self) -> None:
        """Update or create the progress message with debouncing."""
        current_time = time.time()

        # Skip update if too soon (debounce)
        if current_time - self.last_update_time < self.min_update_interval:
            return

        status_text = self._format_status()

        # Skip if text hasn't changed
        if status_text == self.last_sent_text:
            return

        try:
            # Send typing indicator to keep "bot is typing" visible
            # (Telegram cancels it after 5 seconds, so we refresh on every update)
            try:
                await self.bot.send_chat_action(chat_id=self.chat_id, action="typing")
            except Exception:
                pass  # Non-critical, don't fail on this

            if self.progress_message is None:
                # Create new message
                self.progress_message = await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=status_text,
                )
                logger.debug(f"Created progress message {self.progress_message.message_id}")
            else:
                # Edit existing message
                await self.progress_message.edit_text(text=status_text)
                logger.debug("Updated progress message")

            self.last_sent_text = status_text
            self.last_update_time = current_time

        except Exception as e:
            # Log but don't fail - progress updates are non-critical
            logger.warning(f"Failed to update progress message: {e}")

    async def finalize(self) -> None:
        """Delete the progress message after response is sent."""
        if self.progress_message is not None:
            try:
                await self.progress_message.delete()
                logger.debug(f"Deleted progress message {self.progress_message.message_id}")
            except Exception as e:
                # Log but don't fail - deletion is non-critical
                logger.warning(f"Failed to delete progress message: {e}")
            finally:
                self.progress_message = None
                self.current_status = ""
                self.last_sent_text = ""

    async def force_update(self) -> None:
        """Force update message ignoring debounce (for final status)."""
        self.last_update_time = 0
        await self._update_message()
