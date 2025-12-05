# Implementation Plan: Board Game Rules Bot (OpenAI Agents SDK Version)

**Objective:** Refactor existing single-script prototype into a robust, containerized application using `openai-agents-sdk` and `ugrep`.

## 1. Architecture Overview
*   **Service A: App Container**
    *   **Framework:** `python-telegram-bot` (Async).
    *   **Brain:** OpenAI Agents SDK (`Agent`, `Runner`) connecting to `proxyapi.ru`.
    *   **Search:** `ugrep` (via `subprocess`).
    *   **State:** `SQLiteSession` (Local file for MVP context).
*   **Service B: Cache (Redis)**
    *   Used strictly for **Telegram Rate Limiting** and **Concurrency Locks** (to prevent CPU overload).
*   **Storage:**
    *   `/app/rules_pdfs`: Mounted volume for PDF files.
    *   `/app/data`: Mounted volume for SQLite DB and Logs.

## 2. Tech Stack
*   **Base Image:** `python:3.11-slim`
*   **System Dependencies:** `ugrep`, `poppler-utils`
*   **Python Libs:**
    *   `openai-agents-sdk` (Your specific library)
    *   `python-telegram-bot`
    *   `redis`
    *   `pypdf`
    *   `tenacity`

---

## 3. Directory Structure (Refactoring Target)
The Agent must move your code from `main.py` into this structure:

```text
boardgame-bot/
├── docker-compose.yml
├── Dockerfile
├── rules_pdfs/            # PDF Storage
├── data/                  # SQLite DB & Logs
└── src/
    ├── __init__.py
    ├── main.py            # Entry point (Telegram setup)
    ├── config.py          # Env vars
    ├── agent/
    │   ├── __init__.py
    │   ├── definition.py  # Agent(), Instructions, Model setup
    │   └── tools.py       # @function_tool definitions (search, read)
    └── utils/
        ├── __init__.py
        ├── logger.py      # Your logging setup
        ├── safety.py      # Semaphores & Rate Limiting (Redis)
        └── timer.py       # Your ScopeTimer class
```

---

## 4. Detailed Implementation Steps

### Phase 1: Infrastructure & Docker
**Goal:** Create a reproducible environment.

1.  **`Dockerfile`**:
    *   Install `ugrep` and `poppler-utils`.
    *   Set `ENV LANG C.UTF-8` (Critical for Russian filenames).
2.  **`docker-compose.yml`**:
    *   App service mounts `./rules_pdfs:/app/rules_pdfs` and `./data:/app/data`.
    *   Redis service (alpine).
    *   Env Vars: `TELEGRAM_TOKEN`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `REDIS_HOST`.

### Phase 2: Refactoring Core Logic
**Goal:** Move your existing code into the modular structure without breaking it.

1.  **`src/utils/timer.py`**: Move the `ScopeTimer` class here.
2.  **`src/agent/tools.py`**:
    *   Move `search_filenames`, `search_inside_file_ugrep`, `read_full_document` here.
    *   **Modification:** Wrap the `subprocess.run` call in `asyncio.to_thread` or ensure it doesn't block the Telegram heartbeat loop.
    *   **Optimization:** In `search_filenames`, use `path.glob` effectively but ensure it doesn't crash on 1000s of files.
3.  **`src/agent/definition.py`**:
    *   Move the `rules_agent` initialization here.
    *   **Prompt Engineering:** Keep your exact Russian/Regex prompt instructions. They are excellent.

### Phase 3: The Safety Layer (New Logic)
**Goal:** Prevent server freeze.

1.  **`src/utils/safety.py`**:
    *   Initialize a `Redis` client.
    *   Implement `check_rate_limit(user_id)`: Allow max 10 requests per minute.
    *   Implement a **Global Semaphore** for `ugrep`. Since `ugrep` is CPU intensive, limit to 4 concurrent searches.
    *   *Decorator:* Create a `@safe_execution` decorator that wraps tools with a `try/except` block to catch crashes and return a string error instead of killing the bot.

### Phase 4: Telegram Integration
**Goal:** Handle messages and splitting.

1.  **`src/main.py`**:
    *   Setup `ApplicationBuilder`.
    *   **Message Splitter:** The `handle_message` function MUST split the `result.final_output` into chunks of 4000 characters. Telegram rejects messages > 4096 chars.
    *   **Runner Loop:**
        ```python
        # Use existing Runner logic but add safety
        async with ugrep_semaphore:
             result = await Runner.run(rules_agent, user_text, session=session)
        ```

---

## 5. Strict Constraints for the Coding Agent

1.  **Preserve Prompts:** Do NOT change the `instructions` string in `rules_agent`. The logic regarding "Internal Knowledge" for game names and "Regex for Russian" is critical.
2.  **Non-Blocking:** The Telegram bot `handle_message` is `async`. Do not perform heavy file I/O or `subprocess.run` directly in the event loop. Use `await asyncio.to_thread(func)` for the synchronous tool execution if the SDK doesn't handle it automatically.
3.  **Message Chunking:** IMPLEMENT `split_message` utility. The bot WILL crash on long rules text without it.
4.  **Logging:** Keep the `file_handler` writing to `/app/data/app.log` so logs persist after container restarts.

---

## 6. Deployment Instructions

Once the code is generated:

1.  **Environment:**
    Create `.env`:
    ```ini
    TELEGRAM_TOKEN=123:ABC...
    OPENAI_API_KEY=sk-...
    OPENAI_BASE_URL=https://api.proxyapi.ru/openai/v1
    OPENAI_MODEL=gpt-5-nano
    REDIS_HOST=redis
    ```

2.  **Run:**
    ```bash
    docker-compose up --build -d
    ```

3.  **Verify:**
    Check logs: `docker-compose logs -f app`
