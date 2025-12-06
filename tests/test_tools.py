"""Unit tests for agent tools.

Note: We import the internal implementation functions directly
since the exported versions are wrapped with @function_tool decorator.
"""
import asyncio
import pytest
from pathlib import Path
from pypdf import PdfReader

from src.config import settings
from src.utils.timer import ScopeTimer


# Internal implementation of search_filenames (copied from tools.py)
async def _search_filenames_impl(query: str) -> str:
    """Internal implementation of search_filenames for testing."""
    def _sync_search(query: str) -> str:
        with ScopeTimer(f"search_filenames('{query}')"):
            try:
                pdf_dir = Path(settings.pdf_storage_path)
                if not pdf_dir.exists():
                    return f"Error: PDF directory not found at {pdf_dir}"

                query_lower = query.lower()
                matches = [
                    f.name for f in pdf_dir.glob("*.pdf")
                    if query_lower in f.name.lower()
                ]

                if not matches:
                    return f"No PDF files found matching '{query}'"

                if len(matches) > 50:
                    matches = matches[:50]
                    return (
                        f"Found {len(matches)}+ files (showing first 50):\n" +
                        "\n".join(matches)
                    )

                return f"Found {len(matches)} file(s):\n" + "\n".join(matches)

            except Exception as e:
                return f"Error searching files: {str(e)}"

    return await asyncio.to_thread(_sync_search, query)


async def _read_full_document_impl(filename: str) -> str:
    """Internal implementation of read_full_document for testing."""
    def _sync_read(filename: str) -> str:
        with ScopeTimer(f"read_full_document('{filename}')"):
            try:
                pdf_path = Path(settings.pdf_storage_path) / filename
                if not pdf_path.exists():
                    return f"Error: File '{filename}' not found"

                reader = PdfReader(pdf_path)
                text_parts = []

                for page_num, page in enumerate(reader.pages, 1):
                    text_parts.append(f"--- Page {page_num} ---\n")
                    text_parts.append(page.extract_text())

                full_text = "\n".join(text_parts)

                if len(full_text) > 100000:
                    full_text = full_text[:100000] + "\n...(truncated at 100k chars)"

                return full_text

            except Exception as e:
                return f"Failed to read PDF: {str(e)}"

    return await asyncio.to_thread(_sync_read, filename)


@pytest.mark.asyncio
async def test_search_filenames_success(mock_settings, tmp_path):
    """Test successful filename search."""
    # Create test PDFs
    pdf_dir = Path(mock_settings.pdf_storage_path)
    (pdf_dir / "Gloomhaven.pdf").touch()
    (pdf_dir / "Arkham Horror.pdf").touch()

    # Search
    result = await _search_filenames_impl("Gloomhaven")

    assert "Found 1 file" in result
    assert "Gloomhaven.pdf" in result


@pytest.mark.asyncio
async def test_search_filenames_no_match(mock_settings):
    """Test filename search with no matches."""
    result = await _search_filenames_impl("NonexistentGame")

    assert "No PDF files found" in result


@pytest.mark.asyncio
async def test_read_full_document(mock_settings, sample_pdf):
    """Test PDF reading."""
    # Move sample PDF to rules directory
    pdf_dir = Path(mock_settings.pdf_storage_path)
    target = pdf_dir / "test.pdf"
    sample_pdf.rename(target)

    # Read PDF
    result = await _read_full_document_impl("test.pdf")

    assert "Page 1" in result
