import logging
import os
import subprocess
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

load_dotenv()

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.proxyapi.ru/openai/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-nano")

PDF_STORAGE_PATH = os.getenv("PDF_STORAGE_PATH", "./rules_pdfs")
DATA_PATH = os.getenv("DATA_PATH", "./data")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


client = AsyncOpenAI(base_url=OPENAI_BASE_URL, api_key=OPENAI_API_KEY)
set_tracing_disabled(disabled=True)

# Session database path
session_db_path = Path(DATA_PATH) / "sessions" / "conversation.db"
session_db_path.parent.mkdir(parents=True, exist_ok=True)
session = SQLiteSession(str(session_db_path))

# --- LOGGING ---
logger = logging.getLogger()
log_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
logger.setLevel(log_level)

formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# --- Console Handler ---
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(log_level)
console_handler.setFormatter(formatter)

# --- File Handler ---
log_file_path = Path(DATA_PATH) / "app.log"
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
def search_filenames(query: str) -> str:
    """
    Find the PDF filename in local storage based on a game name.
    """

    with ScopeTimer("search_filenames"):
        logger.debug(f"Search for filename: {query}")
        try:
            path = Path(PDF_STORAGE_PATH)
            matches = [
                f.name for f in path.glob("*.pdf") if query.lower() in f.name.lower()
            ]
            if not matches:
                logger.debug(f"No files found matching '{query}'.")
                return f"No files found matching '{query}'."
            logger.debug("Found these files:\n" + "\n".join(matches[:5]))
            return "Found these files:\n" + "\n".join(matches[:5])
        except Exception as e:
            return f"Error searching filenames: {str(e)}"


@function_tool
def search_inside_file_ugrep(filename: str, keywords: str) -> str:
    """
    FAST SEARCH: Use this to find specific rules inside a PDF file.
    """

    with ScopeTimer("search_inside_file_ugrep"):
        file_path = Path(PDF_STORAGE_PATH) / filename
        if not file_path.exists():
            logger.debug(f"Error: File '{filename}' not found in storage.")
            return f"Error: File '{filename}' not found in storage."

        logger.debug(
            f"Search inside file with ugrep: {file_path}. Keywords: {keywords}"
        )

        try:
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
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0 and not result.stdout:
                logger.debug(f"No matches found for '{keywords}' in {filename}.")
                return f"No matches found for '{keywords}' in {filename}."

            output = result.stdout
            logger.debug(f"Ugrep output: {output}")

            if len(output) > 10000:
                return output[:10000] + "\n... [Truncated results] ..."
            return output

        except FileNotFoundError:
            logger.error("Error: 'ugrep' is not installed on the server.")
            return "Error: 'ugrep' is not installed on the server."
        except Exception as e:
            logger.error(f"Error running ugrep: {str(e)}")
            return f"Error running ugrep: {str(e)}"


@function_tool
def read_full_document(filename: str) -> str:
    """
    Read the ENTIRE document. Use ONLY if ugrep fails.
    """

    with ScopeTimer("read_full_document"):
        logger.debug("Read full document, because ugrep fails(or other reason).")

        file_path = Path(PDF_STORAGE_PATH) / filename
        if not file_path.exists():
            logger.error(f"Error: File '{filename}' not found.")
            return f"Error: File '{filename}' not found."

        try:
            text_content = []
            with open(file_path, "rb") as f:
                reader = pypdf.PdfReader(f)
                for i, page in enumerate(reader.pages):
                    text = page.extract_text()
                    if text:
                        text_content.append(f"--- Page {i + 1} ---\n{text}")
            return "\n".join(text_content)[:100000]
        except Exception as e:
            logger.error(f"Error reading PDF: {str(e)}")
            return f"Error reading PDF: {str(e)}"


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
    tools=[search_filenames, search_inside_file_ugrep],
    model=OpenAIChatCompletionsModel(model=OPENAI_MODEL, openai_client=client),
)

# --- TELEGRAM HANDLERS ---


async def start_command(update: Update, context):
    await update.message.reply_text("Ready! Ask me about rules.")


async def handle_message(update: Update, context):
    user_text = update.message.text
    chat_id = update.effective_chat.id

    # Send typing action to show the bot is working
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        result = await Runner.run(rules_agent, user_text, session=session)
        logger.debug(f"Agent final output: {result.final_output}")
        if hasattr(result, "steps"):
            logger.debug(f"Agent steps: {len(result.steps) if result.steps else 0}")
            for i, step in enumerate(result.steps or []):
                logger.debug(f"Step {i}: {type(step).__name__}")

        await update.message.reply_text(result.final_output[:3500])

    except Exception as e:
        logger.error(f"Agent Error: {e}", exc_info=True)
        await update.message.reply_text("Sorry, I encountered an internal error.")


# --- MAIN ---


def main():
    """Main entry point for the bot."""
    # Ensure required directories exist
    Path(PDF_STORAGE_PATH).mkdir(parents=True, exist_ok=True)
    Path(DATA_PATH).mkdir(parents=True, exist_ok=True)

    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN environment variable is not set!")
        sys.exit(1)

    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY environment variable is not set!")
        sys.exit(1)

    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    )

    logger.info("Bot is running...")
    application.run_polling()


if __name__ == "__main__":
    main()
