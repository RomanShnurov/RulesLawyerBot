"""Tests for path traversal protection in agent tools."""
from pathlib import Path

import pytest

from src.rules_lawyer_bot.agent.tools import _safe_pdf_path


def test_safe_pdf_path_accepts_valid_filename(mock_settings):
    """Normal PDF filename inside pdf_storage_path is accepted."""
    base = Path(mock_settings.pdf_storage_path)
    (base / "Gloomhaven.pdf").touch()

    result = _safe_pdf_path("Gloomhaven.pdf")

    assert result == (base / "Gloomhaven.pdf").resolve()


def test_safe_pdf_path_rejects_traversal_relative(mock_settings):
    """Relative traversal `../etc/passwd` is rejected."""
    with pytest.raises(ValueError, match="Invalid filename"):
        _safe_pdf_path("../../../etc/passwd")


def test_safe_pdf_path_rejects_traversal_within_pdf_dir(mock_settings):
    """Even traversal that resolves inside base must be rejected if it escapes via ..."""
    with pytest.raises(ValueError, match="Invalid filename"):
        _safe_pdf_path("../../some_other.pdf")


def test_safe_pdf_path_rejects_absolute_path(mock_settings):
    """Absolute path outside pdf_storage_path is rejected."""
    with pytest.raises(ValueError, match="Invalid filename"):
        _safe_pdf_path("/etc/passwd")


def test_safe_pdf_path_rejects_non_pdf_extension(mock_settings):
    """Non-PDF extensions are rejected even inside base."""
    base = Path(mock_settings.pdf_storage_path)
    (base / "evil.txt").touch()

    with pytest.raises(ValueError, match="Invalid filename"):
        _safe_pdf_path("evil.txt")


def test_safe_pdf_path_rejects_no_extension(mock_settings):
    """File without extension rejected."""
    with pytest.raises(ValueError, match="Invalid filename"):
        _safe_pdf_path("README")


def test_safe_pdf_path_case_insensitive_extension(mock_settings):
    """`.PDF` (uppercase) is accepted."""
    base = Path(mock_settings.pdf_storage_path)
    (base / "Game.PDF").touch()

    result = _safe_pdf_path("Game.PDF")

    assert result.suffix.lower() == ".pdf"
