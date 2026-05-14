"""Tests for path traversal protection in agent tools."""
import json
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


@pytest.mark.asyncio
async def test_search_inside_file_ugrep_rejects_traversal(mock_settings):
    """search_inside_file_ugrep rejects traversal filename before reaching subprocess."""
    from src.rules_lawyer_bot.agent.tools import _search_inside_file_ugrep_impl

    # _search_inside_file_ugrep_impl has no @safe_execution decorator, so the
    # ValueError from _safe_pdf_path propagates raw — we must catch it here.
    with pytest.raises(ValueError, match="Invalid filename"):
        await _search_inside_file_ugrep_impl("../../etc/passwd", "root")


@pytest.mark.asyncio
async def test_read_full_document_rejects_traversal(mock_settings):
    """read_full_document integration: traversal filename triggers safe-execution error path.

    Calls read_full_document.on_invoke_tool — the same entry-point the agents
    framework uses at runtime — with a path-traversal filename.  _safe_pdf_path
    raises ValueError, which @safe_execution catches and converts to the generic
    "Something went wrong" string.  If someone replaced _safe_pdf_path with a
    bare Path join, the FileNotFoundError handler would fire instead and the
    assertion below would fail, catching the regression.
    """
    from src.rules_lawyer_bot.agent.tools import read_full_document

    result = await read_full_document.on_invoke_tool(
        None, json.dumps({"filename": "../../etc/passwd"})
    )

    # @safe_execution converts ValueError (from _safe_pdf_path) to the generic
    # error message.  A bare Path join would produce "📁 File not found" instead.
    assert "Something went wrong" in result


@pytest.mark.asyncio
async def test_search_inside_file_wraps_output_in_sandbox_tags(mock_settings, sample_pdf):
    """search_inside_file_ugrep wraps result in <tool_output> tags."""
    from src.rules_lawyer_bot.agent.tools import _search_inside_file_ugrep_impl

    pdf_dir = Path(mock_settings.pdf_storage_path)
    sample_pdf.rename(pdf_dir / "test.pdf")

    result = await _search_inside_file_ugrep_impl("test.pdf", "anything")

    assert result.startswith("<tool_output")
    assert result.rstrip().endswith("</tool_output>")
