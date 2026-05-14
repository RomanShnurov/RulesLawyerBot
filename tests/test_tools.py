"""Unit tests for agent tools.

Note: We import the internal implementation functions directly
since the exported versions are wrapped with @function_tool decorator.

Removed in cleanup pass:
- _read_full_document_impl + test_read_full_document: production now uses
  pdftotext cache (not pypdf). Covered by tests/test_pdf_cache.py.
- _parallel_search_terms_impl + all parallel_search_terms tests: production
  wraps results in sandboxed JSON and calls _search_inside_file_ugrep_impl
  directly. Local mock-injection helper no longer reflects production.
  Covered by tests/test_pdf_cache.py::test_search_returns_page_numbers.
"""
import asyncio
import pytest
from pathlib import Path

from src.rules_lawyer_bot.config import settings
from src.rules_lawyer_bot.utils.timer import ScopeTimer


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


# Internal implementation of list_directory_tree for testing
async def _list_directory_tree_impl(path: str = "", max_depth: int = 3) -> str:
    """Internal implementation of list_directory_tree for testing."""
    def _sync_tree(path: str, max_depth: int) -> str:
        with ScopeTimer(f"list_directory_tree('{path}', max_depth={max_depth})"):
            try:
                base_path = Path(settings.pdf_storage_path)
                target_path = base_path / path if path else base_path

                if not target_path.exists():
                    return f"Error: Path '{path}' not found"

                if not target_path.is_dir():
                    return f"Error: '{path}' is not a directory"

                lines = [f"{target_path.name}/"]
                _build_tree_for_test(target_path, lines, "", max_depth, 0)

                output = "\n".join(lines)

                if len(output) > 10000:
                    output = output[:10000] + "\n...(truncated)"

                return output

            except Exception as e:
                return f"Error listing directory: {str(e)}"

    return await asyncio.to_thread(_sync_tree, path, max_depth)


def _build_tree_for_test(
    directory: Path,
    lines: list,
    prefix: str,
    max_depth: int,
    current_depth: int
) -> None:
    """Build tree structure helper for testing."""
    if current_depth >= max_depth:
        return

    items = []
    try:
        for item in sorted(directory.iterdir()):
            if item.is_dir():
                items.append((item, True))
            elif item.suffix.lower() == ".pdf":
                items.append((item, False))
    except PermissionError:
        lines.append(f"{prefix}[Permission denied]")
        return

    for i, (item, is_dir) in enumerate(items):
        is_last = i == len(items) - 1
        connector = "└── " if is_last else "├── "

        if is_dir:
            lines.append(f"{prefix}{connector}{item.name}/")
            extension = "    " if is_last else "│   "
            _build_tree_for_test(item, lines, prefix + extension, max_depth, current_depth + 1)
        else:
            lines.append(f"{prefix}{connector}{item.name}")


@pytest.mark.asyncio
async def test_list_directory_tree_empty(mock_settings):
    """Test tree on empty directory."""
    result = await _list_directory_tree_impl()

    # Should show root dir name
    assert "pdfs/" in result


@pytest.mark.asyncio
async def test_list_directory_tree_with_pdfs(mock_settings):
    """Test tree with PDF files."""
    pdf_dir = Path(mock_settings.pdf_storage_path)
    (pdf_dir / "Gloomhaven.pdf").touch()
    (pdf_dir / "Arkham Horror.pdf").touch()

    result = await _list_directory_tree_impl()

    assert "Gloomhaven.pdf" in result
    assert "Arkham Horror.pdf" in result


@pytest.mark.asyncio
async def test_list_directory_tree_nested(mock_settings):
    """Test tree with nested directories."""
    pdf_dir = Path(mock_settings.pdf_storage_path)

    # Create nested structure
    (pdf_dir / "Fantasy").mkdir()
    (pdf_dir / "Fantasy" / "Gloomhaven.pdf").touch()
    (pdf_dir / "Horror").mkdir()
    (pdf_dir / "Horror" / "Arkham.pdf").touch()

    result = await _list_directory_tree_impl()

    assert "Fantasy/" in result
    assert "Gloomhaven.pdf" in result
    assert "Horror/" in result
    assert "Arkham.pdf" in result


@pytest.mark.asyncio
async def test_list_directory_tree_max_depth(mock_settings):
    """Test tree respects max_depth limit."""
    pdf_dir = Path(mock_settings.pdf_storage_path)

    # Create deep structure
    (pdf_dir / "level1" / "level2" / "level3").mkdir(parents=True)
    (pdf_dir / "level1" / "level2" / "level3" / "deep.pdf").touch()

    # With depth 2, should not show level3
    result = await _list_directory_tree_impl(max_depth=2)

    assert "level1/" in result
    assert "level2/" in result
    # level3 should not appear (depth limit)
    assert "level3" not in result


@pytest.mark.asyncio
async def test_list_directory_tree_nonexistent_path(mock_settings):
    """Test tree with nonexistent path."""
    result = await _list_directory_tree_impl("nonexistent")

    assert "Error" in result
    assert "not found" in result


@pytest.mark.asyncio
async def test_list_directory_tree_ignores_non_pdf(mock_settings):
    """Test tree ignores non-PDF files."""
    pdf_dir = Path(mock_settings.pdf_storage_path)
    (pdf_dir / "game.pdf").touch()
    (pdf_dir / "readme.txt").touch()
    (pdf_dir / "image.png").touch()

    result = await _list_directory_tree_impl()

    assert "game.pdf" in result
    assert "readme.txt" not in result
    assert "image.png" not in result
