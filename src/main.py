import asyncio
import logging
import sys
import time
from pathlib import Path

import pypdf
from agents import (
    Agent,
    OpenAIChatCompletionsModel,
    Runner,
    SQLiteSession,
    function_tool,
    set_tracing_disabled,
)
from dotenv import load_dotenv
from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from src.config import settings
from src.utils.safety import BotError, rate_limiter, safe_execution, ugrep_semaphore

load_dotenv()

# --- CONFIGURATION ---
client = AsyncOpenAI(base_url=settings.openai_base_url, api_key=settings.openai_api_key)
set_tracing_disabled(disabled=True)

# Session database path
session_db_path = Path(settings.data_path) / "sessions" / "conversation.db"
session_db_path.parent.mkdir(parents=True, exist_ok=True)
session = SQLiteSession(str(session_db_path))

# --- LOGGING ---
logger = logging.getLogger()
log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
logger.setLevel(log_level)

formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# --- Console Handler ---
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(log_level)
console_handler.setFormatter(formatter)

# --- File Handler ---
log_file_path = Path(settings.data_path) / "app.log"
log_file_path.parent.mkdir(parents=True, exist_ok=True)
file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
file_handler.setLevel(log_level)
file_handler.setFormatter(formatter)


logger.addHandler(console_handler)
logger.addHandler(file_handler)

logger.propagate = False

logging.getLogger("httpcore").setLevel(logging.INFO)
logging.getLogger("telegram").setLevel(logging.INFO)


# --- PERFORMANCE TIMER ---
class ScopeTimer:
    def __init__(self, name="block"):
        self.name = name

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = time.perf_counter() - self.start
        logger.debug(f"{self.name}: {elapsed:.6f} sec")
        # вернём False, чтобы исключения не подавлялись
        return False


# --- TOOL DEFINITIONS ---
# The Agents SDK inspects type hints and docstrings to generate schemas.


@function_tool
@safe_execution
async def search_filenames(query: str) -> str:
    """
    Find the PDF filename in local storage based on a game name.
    """

    with ScopeTimer("search_filenames"):
        logger.debug(f"Search for filename: {query}")

        if not query or len(query) < 2:
            raise BotError(
                user_message="❌ Search query too short. Please use at least 2 characters.",
                log_details=f"Invalid query length: {len(query)}"
            )

        path = Path(settings.pdf_storage_path)
        matches = [
            f.name for f in path.glob("*.pdf") if query.lower() in f.name.lower()
        ]

        if not matches:
            logger.debug(f"No files found matching '{query}'.")
            raise BotError(
                user_message=f"📂 No games found matching '{query}'. Please check the spelling.",
                log_details=f"No PDFs found for query: {query}"
            )

        logger.debug("Found these files:\n" + "\n".join(matches[:5]))
        return "Found these files:\n" + "\n".join(matches[:5])


@function_tool
@safe_execution
async def search_inside_file_ugrep(filename: str, keywords: str) -> str:
    """
    FAST SEARCH: Use this to find specific rules inside a PDF file.
    """

    with ScopeTimer("search_inside_file_ugrep"):
        file_path = Path(settings.pdf_storage_path) / filename

        if not file_path.exists():
            logger.debug(f"File '{filename}' not found in storage.")
            raise FileNotFoundError(f"'{filename}'")

        if not keywords or len(keywords) < 2:
            raise BotError(
                user_message="❌ Keywords too short. Please use at least 2 characters.",
                log_details=f"Invalid keywords length: {len(keywords)}"
            )

        logger.debug(f"Search inside file with ugrep: {file_path}. Keywords: {keywords}")

        # Use semaphore to limit concurrent ugrep processes
        async with ugrep_semaphore:
            cmd = [
                "ugrep",
                "-i",
                "-n",
                "-E",
                "-Z",
                "-H",
                "--xml",
                "--filter=pdf:pdftotext - -",
                keywords,
                str(file_path),
            ]

            logger.info(f"Running command: {' '.join(cmd)}")

            try:
                # Add timeout and run async
                process = await asyncio.wait_for(
                    asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    ),
                    timeout=30.0
                )

                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=30.0
                )

                output = stdout.decode("utf-8", errors="ignore")

                if process.returncode != 0 and not output:
                    logger.debug(f"No matches found for '{keywords}' in {filename}.")
                    return f"🔍 No matches found for '{keywords}' in {filename}."

                logger.debug(f"Ugrep output length: {len(output)} chars")

                if len(output) > 10000:
                    return output[:10000] + "\n\n... [Truncated - results too long] ..."
                return output

            except FileNotFoundError:
                raise BotError(
                    user_message="🔧 Search tool not available. Using fallback method...",
                    log_details="ugrep not installed on server"
                )


@function_tool
@safe_execution
async def read_full_document(filename: str) -> str:
    """
    Read the ENTIRE document. Use ONLY if ugrep fails.
    """

    with ScopeTimer("read_full_document"):
        logger.debug("Read full document, because ugrep fails (or other reason).")

        file_path = Path(settings.pdf_storage_path) / filename

        if not file_path.exists():
            logger.error(f"File '{filename}' not found.")
            raise FileNotFoundError(f"'{filename}'")

        # Check file size
        file_size = file_path.stat().st_size
        if file_size > 100_000_000:  # 100MB limit
            raise BotError(
                user_message="📄 File too large to process. Please contact administrator.",
                log_details=f"File size {file_size} exceeds 100MB limit for {filename}"
            )

        text_content = []
        with open(file_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            total_pages = len(reader.pages)

            for i, page in enumerate(reader.pages):
                text = page.extract_text()
                if text:
                    text_content.append(f"--- Page {i + 1}/{total_pages} ---\n{text}")

        full_text = "\n".join(text_content)
        logger.debug(f"Extracted {len(full_text)} characters from {total_pages} pages")

        if len(full_text) > 100000:
            return full_text[:100000] + "\n\n... [Truncated - document too long] ..."
        return full_text


# --- AGENT CONFIGURATION ---

rules_agent = Agent(
    name="Board Game Referee",
    instructions=(
        "You are an expert board game rules referee with encyclopedic knowledge of game editions. "
        "You can speak multiple languages (English, Russian, etc.).\n\n"
        "YOUR GOAL: Find the correct PDF and answer the user's question.\n\n"
        "CRITICAL SEARCH INSTRUCTIONS:\n"
        "1. The PDF files in your storage are almost always named using the ORIGINAL ENGLISH TITLE.\n"
        "2. If a user gives a localized name (e.g., Russian 'Схватка в стиле фэнтези'), "
        "   you MUST use your internal knowledge to identify the original English name "
        "   (which is 'Super Fantasy Brawl') BEFORE calling the search tool.\n"
        "3. Always search for the English name first.\n\n"
        "WORKFLOW:\n"
        "1. Identify the game name and User's Language.\n"
        "2. Convert localized game name -> English Filename Query.\n"
        "3. Call 'search_filenames(query=EnglishName)'.\n"
        "4. Call 'read_document'.\n"
        "5. Answer the user IN THEIR OWN LANGUAGE based on the text you read."
        "\nSEARCH INSTRUCTIONS FOR RUSSIAN LANGUAGE:\n"
        "1. The user asks in Russian. The PDF text is in Russian.\n"
        "2. Russian language has complex morphology (cases, endings). Searching for exact words often fails.\n"
        "3. When using 'search_inside_file_ugrep', NEVER search for a single word like 'перемещение'.\n"
        "4. ALWAYS construct a REGEX query that includes:\n"
        "   - The root of the word (e.g., 'перемещ' for 'перемещение/перемещать').\n"
        "   - Synonyms joined by OR operator '|'.\n"
        "   - Example: If user asks about 'movement', search for: 'перемещ|движен|ход|бег'.\n"
        "5. Be creative with synonyms relevant to board games."
    ),
    tools=[search_filenames, search_inside_file_ugrep, read_full_document],
    model=OpenAIChatCompletionsModel(model=settings.openai_model, openai_client=client),
)

# --- TELEGRAM HANDLERS ---


async def start_command(update: Update, context):
    await update.message.reply_text("Ready! Ask me about rules.")


async def handle_message(update: Update, context):
    user_text = update.message.text
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # 1. Check rate limit FIRST
    allowed, message = await rate_limiter.check_rate_limit(user_id)
    if not allowed:
        logger.warning(f"Rate limit exceeded for user {user_id}")
        await update.message.reply_text(f"⚠️ {message}")
        return

    # 2. Send typing action to show the bot is working
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        # 3. Run agent (tools have @safe_execution)
        result = await Runner.run(rules_agent, user_text, session=session)
        logger.debug(f"Agent final output: {result.final_output}")
        if hasattr(result, "steps"):
            logger.debug(f"Agent steps: {len(result.steps) if result.steps else 0}")
            for i, step in enumerate(result.steps or []):
                logger.debug(f"Step {i}: {type(step).__name__}")

        # 4. Send response (truncate to Telegram's limit)
        await update.message.reply_text(result.final_output[:3500])

    except Exception as e:
        logger.error(f"Agent Error: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Sorry, I encountered an internal error. Please try again or contact support."
        )


# --- MAIN ---


def main():
    """Main entry point for the bot."""
    # Ensure required directories exist
    Path(settings.pdf_storage_path).mkdir(parents=True, exist_ok=True)
    Path(settings.data_path).mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("RulesLawyerBot starting...")
    logger.info(f"Model: {settings.openai_model}")
    logger.info(f"Rate limit: {settings.max_requests_per_minute} req/min per user")
    logger.info(f"Max concurrent searches: {settings.max_concurrent_searches}")
    logger.info(f"PDF storage: {settings.pdf_storage_path}")
    logger.info("=" * 60)

    application = ApplicationBuilder().token(settings.telegram_token).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    )

    logger.info("Bot is running and ready to receive messages...")
    application.run_polling()


if __name__ == "__main__":
    main()
