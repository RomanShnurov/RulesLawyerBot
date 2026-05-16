"""Pytest configuration and shared fixtures."""
import atexit
import logging
import os
import shutil
import tempfile

# Redirect ALL bot data (app.log, budget.db, per-user session DBs) into a
# throwaway directory BEFORE the bot package is imported. Both
# config.Settings() and logger.setup_logging() run at import time and read
# DATA_PATH, so the override must happen at conftest module load — pytest
# imports conftest before any test module imports src.rules_lawyer_bot.
# Without this, every `pytest` run appends test noise to the real
# ./data/app.log (and writes test budget/session DBs into ./data).
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="rlb-test-data-")
os.environ["DATA_PATH"] = _TEST_DATA_DIR
atexit.register(shutil.rmtree, _TEST_DATA_DIR, ignore_errors=True)

import pytest  # noqa: E402
from pathlib import Path  # noqa: E402

from pypdf import PdfWriter  # noqa: E402


def pytest_unconfigure(config) -> None:
    """Remove the throwaway data dir at session end.

    The bot logger holds app.log open, so on Windows the file must be
    released before rmtree can delete the directory. atexit alone is not
    enough: logging.shutdown is registered earlier and runs LAST (LIFO),
    so the handle is still open when an atexit-based cleanup fires.
    """
    for handler in list(logging.getLogger("boardgame_bot").handlers):
        if isinstance(handler, logging.FileHandler):
            handler.close()
            logging.getLogger("boardgame_bot").removeHandler(handler)
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)


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

    Returns:
        Mocked settings instance
    """
    from src.rules_lawyer_bot.config import settings

    monkeypatch.setattr(settings, "pdf_storage_path", str(tmp_path / "pdfs"))
    monkeypatch.setattr(settings, "data_path", str(tmp_path / "data"))

    # Create directories
    Path(settings.pdf_storage_path).mkdir(parents=True, exist_ok=True)
    Path(settings.data_path).mkdir(parents=True, exist_ok=True)

    return settings
