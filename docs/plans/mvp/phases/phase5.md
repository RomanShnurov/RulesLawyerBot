## Phase 5: Testing & Deployment (Day 7)

### 🎯 Goal
Validate functionality and deploy to production.

---

### Step 5.1: Test Configuration

**Create `tests/conftest.py`:**

```python
"""Pytest configuration and shared fixtures."""
import pytest
from pathlib import Path
from pypdf import PdfWriter


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Create a sample PDF for testing.

    Args:
        tmp_path: Pytest temporary directory

    Returns:
        Path to created PDF
    """
    pdf_path = tmp_path / "test_game.pdf"

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)

    with open(pdf_path, "wb") as f:
        writer.write(f)

    return pdf_path


@pytest.fixture
def mock_settings(tmp_path: Path, monkeypatch):
    """Override settings for testing.

    Args:
        tmp_path: Pytest temporary directory
        monkeypatch: Pytest monkeypatch fixture
    """
    from src.config import settings

    monkeypatch.setattr(settings, "pdf_storage_path", str(tmp_path / "pdfs"))
    monkeypatch.setattr(settings, "data_path", str(tmp_path / "data"))

    # Create directories
    Path(settings.pdf_storage_path).mkdir(parents=True, exist_ok=True)
    Path(settings.data_path).mkdir(parents=True, exist_ok=True)

    return settings
```

---

### Step 5.2: Tool Tests

**Create `tests/test_tools.py`:**

```python
"""Unit tests for agent tools."""
import pytest
from pathlib import Path

from src.agent.tools import search_filenames, read_full_document


@pytest.mark.asyncio
async def test_search_filenames_success(mock_settings, tmp_path):
    """Test successful filename search."""
    # Create test PDFs
    pdf_dir = Path(mock_settings.pdf_storage_path)
    (pdf_dir / "Gloomhaven.pdf").touch()
    (pdf_dir / "Arkham Horror.pdf").touch()

    # Search
    result = await search_filenames("Gloomhaven")

    assert "Found 1 file" in result
    assert "Gloomhaven.pdf" in result


@pytest.mark.asyncio
async def test_search_filenames_no_match(mock_settings):
    """Test filename search with no matches."""
    result = await search_filenames("NonexistentGame")

    assert "No PDF files found" in result


@pytest.mark.asyncio
async def test_read_full_document(mock_settings, sample_pdf):
    """Test PDF reading."""
    # Move sample PDF to rules directory
    pdf_dir = Path(mock_settings.pdf_storage_path)
    target = pdf_dir / "test.pdf"
    sample_pdf.rename(target)

    # Read PDF
    result = await read_full_document("test.pdf")

    assert "Page 1" in result
```

---

### Step 5.3: Integration Test

**Create `tests/test_integration.py`:**

```python
"""End-to-end integration tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.main import handle_message


@pytest.mark.asyncio
async def test_message_handling_with_rate_limit(monkeypatch):
    """Test that rate limiting works correctly."""
    # Mock dependencies
    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.message.text = "How does combat work?"

    mock_context = MagicMock()
    mock_context.bot.send_chat_action = AsyncMock()
    mock_context.bot.send_message = AsyncMock()

    # First request should succeed
    await handle_message(mock_update, mock_context)

    # Verify chat action was sent
    mock_context.bot.send_chat_action.assert_called_once()
```

---

### Step 5.4: Load Testing

**Manual load test script:**

```python
"""Load test script for concurrent users."""
import asyncio
import time
from telegram import Bot

async def simulate_user(bot: Bot, chat_id: int, message: str):
    """Simulate single user request."""
    start = time.time()
    await bot.send_message(chat_id=chat_id, text=message)
    duration = time.time() - start
    print(f"Request completed in {duration:.2f}s")

async def load_test(token: str, chat_id: int, num_users: int = 10):
    """Simulate multiple concurrent users."""
    bot = Bot(token=token)

    tasks = [
        simulate_user(bot, chat_id, f"Test message {i}")
        for i in range(num_users)
    ]

    start = time.time()
    await asyncio.gather(*tasks)
    total = time.time() - start

    print(f"\n✅ {num_users} requests completed in {total:.2f}s")
    print(f"Average: {total/num_users:.2f}s per request")

# Run: python tests/load_test.py
if __name__ == "__main__":
    TOKEN = "YOUR_TOKEN"
    CHAT_ID = 123456789
    asyncio.run(load_test(TOKEN, CHAT_ID, num_users=10))
```
