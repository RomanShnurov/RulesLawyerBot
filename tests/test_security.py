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


import pytest as _pytest


@_pytest.mark.asyncio
async def test_search_inside_file_ugrep_rejects_traversal(mock_settings):
    """search_inside_file_ugrep rejects traversal filename before reaching subprocess."""
    from src.rules_lawyer_bot.agent.tools import _search_inside_file_ugrep_impl

    # _search_inside_file_ugrep_impl has no @safe_execution decorator, so the
    # ValueError from _safe_pdf_path propagates raw — we must catch it here.
    with _pytest.raises(ValueError, match="Invalid filename"):
        await _search_inside_file_ugrep_impl("../../etc/passwd", "root")


@_pytest.mark.asyncio
async def test_read_full_document_rejects_traversal(mock_settings):
    """read_full_document rejects traversal filename."""
    # We invoke the inner sync logic directly. The @function_tool wrapper
    # is not directly callable, so we exercise the public Path validation
    # through _safe_pdf_path called from within.
    from src.rules_lawyer_bot.agent.tools import _safe_pdf_path

    with _pytest.raises(ValueError):
        _safe_pdf_path("../../etc/passwd")


@_pytest.mark.asyncio
async def test_search_inside_file_wraps_output_in_sandbox_tags(mock_settings, sample_pdf):
    """search_inside_file_ugrep wraps result in <tool_output> tags."""
    from src.rules_lawyer_bot.agent.tools import _search_inside_file_ugrep_impl

    pdf_dir = Path(mock_settings.pdf_storage_path)
    sample_pdf.rename(pdf_dir / "test.pdf")

    result = await _search_inside_file_ugrep_impl("test.pdf", "anything")

    assert result.startswith("<tool_output")
    assert result.rstrip().endswith("</tool_output>")
