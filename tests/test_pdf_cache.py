"""Tests for PDF text cache (pdftotext + mtime invalidation)."""
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from pypdf import PdfWriter

from src.rules_lawyer_bot.agent.tools import _get_pdf_text_cache


def _make_pdf(path: Path, num_pages: int = 1) -> None:
    """Create a minimal PDF with the given page count."""
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=200, height=200)
    with open(path, "wb") as f:
        writer.write(f)


def test_cache_created_on_first_call(mock_settings):
    """First call to _get_pdf_text_cache generates the .txt file."""
    pdf_dir = Path(mock_settings.pdf_storage_path)
    pdf_path = pdf_dir / "test.pdf"
    _make_pdf(pdf_path, num_pages=3)

    cache_path = _get_pdf_text_cache(pdf_path)

    assert cache_path.exists()
    assert cache_path.parent.name == ".cache"
    assert cache_path.name == "test.pdf.txt"


def test_cache_contains_form_feeds_between_pages(mock_settings):
    """Cache content has \\f (0x0c) markers between pages."""
    pdf_dir = Path(mock_settings.pdf_storage_path)
    pdf_path = pdf_dir / "multi.pdf"
    _make_pdf(pdf_path, num_pages=3)

    cache_path = _get_pdf_text_cache(pdf_path)

    text = cache_path.read_text(encoding="utf-8", errors="replace")
    assert text.count("\f") >= 2  # 3 pages → at least 2 separators


def test_cache_reused_when_pdf_unchanged(mock_settings):
    """Second call does not invoke pdftotext if cache mtime >= pdf mtime."""
    pdf_dir = Path(mock_settings.pdf_storage_path)
    pdf_path = pdf_dir / "stable.pdf"
    _make_pdf(pdf_path, num_pages=1)

    # First call creates the cache
    _get_pdf_text_cache(pdf_path)

    # Second call should NOT call pdftotext
    with patch("src.rules_lawyer_bot.agent.tools.subprocess.run") as mock_run:
        _get_pdf_text_cache(pdf_path)
        mock_run.assert_not_called()


def test_cache_regenerated_when_pdf_newer(mock_settings):
    """If PDF mtime > cache mtime, cache is regenerated."""
    pdf_dir = Path(mock_settings.pdf_storage_path)
    pdf_path = pdf_dir / "updated.pdf"
    _make_pdf(pdf_path, num_pages=1)

    cache_path = _get_pdf_text_cache(pdf_path)
    cache_mtime_before = cache_path.stat().st_mtime

    # Touch PDF to make it newer than the cache
    time.sleep(0.05)
    future = time.time() + 60  # 60s in the future
    os.utime(pdf_path, (future, future))

    cache_path = _get_pdf_text_cache(pdf_path)

    assert cache_path.stat().st_mtime > cache_mtime_before


def test_cache_dir_created_if_missing(mock_settings):
    """`.cache/` subdirectory is created on demand."""
    pdf_dir = Path(mock_settings.pdf_storage_path)
    pdf_path = pdf_dir / "first.pdf"
    _make_pdf(pdf_path, num_pages=1)

    cache_dir = pdf_dir / ".cache"
    assert not cache_dir.exists()

    _get_pdf_text_cache(pdf_path)

    assert cache_dir.is_dir()


import json as _json


@pytest.mark.asyncio
async def test_search_returns_page_numbers(mock_settings):
    """search_inside_file_ugrep returns page numbers in its JSON output."""
    from src.rules_lawyer_bot.agent.tools import _search_inside_file_ugrep_impl

    pdf_dir = Path(mock_settings.pdf_storage_path)
    pdf_path = pdf_dir / "story.pdf"
    _make_pdf(pdf_path, num_pages=3)

    # Pre-populate the cache so we control the page content exactly
    cache_dir = pdf_dir / ".cache"
    cache_dir.mkdir(exist_ok=True)
    cache_path = cache_dir / "story.pdf.txt"
    cache_path.write_text(
        "Page one talks about attack rules.\fPage two covers defense.\fPage three is end of game.\f",
        encoding="utf-8",
    )

    # Make the cache newer than the PDF so it is used
    future = time.time() + 60
    os.utime(cache_path, (future, future))

    result_raw = await _search_inside_file_ugrep_impl("story.pdf", "defense")

    # Result is wrapped by _sandbox; extract JSON payload
    assert result_raw.startswith("<tool_output")
    inner_start = result_raw.find(">\n") + 2
    inner_end = result_raw.rfind("\n</tool_output>")
    payload = _json.loads(result_raw[inner_start:inner_end])

    assert payload["status"] == "ok"
    assert len(payload["data"]) >= 1
    match = payload["data"][0]
    assert match["page"] == 2
    assert "defense" in match["excerpt"].lower()


@pytest.mark.asyncio
async def test_search_no_match_returns_empty_data(mock_settings):
    """No matches yields status=no_match and empty data."""
    from src.rules_lawyer_bot.agent.tools import _search_inside_file_ugrep_impl

    pdf_dir = Path(mock_settings.pdf_storage_path)
    pdf_path = pdf_dir / "story.pdf"
    _make_pdf(pdf_path, num_pages=1)

    cache_dir = pdf_dir / ".cache"
    cache_dir.mkdir(exist_ok=True)
    cache_path = cache_dir / "story.pdf.txt"
    cache_path.write_text("nothing relevant here", encoding="utf-8")
    future = time.time() + 60
    os.utime(cache_path, (future, future))

    result_raw = await _search_inside_file_ugrep_impl("story.pdf", "nonexistentterm")
    inner_start = result_raw.find(">\n") + 2
    inner_end = result_raw.rfind("\n</tool_output>")
    payload = _json.loads(result_raw[inner_start:inner_end])

    assert payload["status"] == "no_match"
    assert payload["data"] == []
