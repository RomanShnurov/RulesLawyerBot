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

    Returns:
        Mocked settings instance
    """
    from src.config import settings

    monkeypatch.setattr(settings, "pdf_storage_path", str(tmp_path / "pdfs"))
    monkeypatch.setattr(settings, "data_path", str(tmp_path / "data"))

    # Create directories
    Path(settings.pdf_storage_path).mkdir(parents=True, exist_ok=True)
    Path(settings.data_path).mkdir(parents=True, exist_ok=True)

    return settings
