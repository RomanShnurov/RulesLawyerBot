"""OpenAI Agent definition and session management."""
from pathlib import Path

from agents import Agent, OpenAIChatCompletionsModel, SQLiteSession, set_tracing_disabled
from openai import AsyncOpenAI

from src.agent.tools import read_full_document, search_filenames, search_inside_file_ugrep
from src.config import settings
from src.utils.logger import logger

# Disable tracing for production
set_tracing_disabled(disabled=True)


def create_agent() -> Agent:
    """Create the board game referee agent with tools.

    Returns:
        Configured Agent instance
    """
    # Initialize OpenAI client with custom base URL
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url
    )

    model = OpenAIChatCompletionsModel(
        model=settings.openai_model,
        openai_client=client
    )

    # Agent instructions (PRESERVED from original implementation)
    instructions = """
You are a Board Game Referee bot.

**Tools:**
1. `search_filenames(query)` - Find PDF files by game name
2. `search_inside_file_ugrep(filename, keywords)` - Fast regex search inside PDF
3. `read_full_document(filename)` - Read entire PDF (fallback)

**Rules for filename search:**
- PDF files are named using **ORIGINAL ENGLISH** game titles
- If user provides localized name (e.g., Russian "Схватка в стиле фэнтези"),
  translate to English ("Super Fantasy Brawl") before searching
- Use internal knowledge of popular game names

**Rules for text search (Russian language):**
- Use **REGEX patterns with word roots and synonyms** due to complex morphology
- Example: For "movement" use: `перемещ|движен|ход|бег`
- Example: For "attack" use: `атак|удар|бой|сраж`
- This handles: перемещение, переместить, движение, передвижение, ход, etc.

**Response format:**
1. Acknowledge the question
2. Use tools to find information
3. Provide clear, cited answer with page numbers if available
4. If information not found, suggest checking specific sections or offer general knowledge

**Internal game knowledge:**
Store common game name translations:
- "Схватка в стиле фэнтези" → "Super Fantasy Brawl"
- "Время приключений" → "Time of Adventure"
- "Ужас Аркхэма" → "Arkham Horror"
(Expand as needed)
""".strip()

    agent = Agent(
        name="Board Game Referee",
        model=model,
        instructions=instructions,
        tools=[
            search_filenames,
            search_inside_file_ugrep,
            read_full_document
        ]
    )

    logger.info("Agent created successfully")
    return agent


def get_user_session(user_id: int) -> SQLiteSession:
    """Get or create SQLite session for a specific user.

    IMPORTANT: Each user gets isolated session to prevent database locks.

    Args:
        user_id: Telegram user ID

    Returns:
        SQLiteSession instance for this user
    """
    session_dir = Path(settings.session_db_dir)
    session_dir.mkdir(parents=True, exist_ok=True)

    session_id = f"conversation_{user_id}"
    db_path = session_dir / f"{user_id}.db"

    logger.debug(f"Loading session for user {user_id}: {db_path}")

    return SQLiteSession(
        session_id=session_id,
        db_path=str(db_path)
    )


# Global agent instance
rules_agent = create_agent()
