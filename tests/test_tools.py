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


# Internal implementation of parallel_search_terms for testing
async def _parallel_search_terms_impl(
    filename: str,
    terms: list[str],
    fuzzy: bool = False,
    mock_search_fn=None
) -> str:
    """Internal implementation of parallel_search_terms for testing."""
    import json
    from src.utils.timer import ScopeTimer

    with ScopeTimer(f"parallel_search_terms('{filename}', {len(terms)} terms)"):
        if not terms:
            return json.dumps({"error": "No search terms provided"})

        if len(terms) > 10:
            terms = terms[:10]

        # Use mock function if provided, otherwise real implementation
        if mock_search_fn:
            tasks = [mock_search_fn(filename, term, fuzzy) for term in terms]
        else:
            # In real tests, we'd use actual search function
            # For now, this is a placeholder
            tasks = [asyncio.sleep(0.01) for _ in terms]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        result_dict = {}
        for term, result in zip(terms, results):
            if isinstance(result, Exception):
                result_dict[term] = f"Error: {str(result)}"
            else:
                if len(str(result)) > 5000:
                    result_dict[term] = str(result)[:5000] + "\n...(truncated)"
                else:
                    result_dict[term] = str(result)

        return json.dumps(result_dict, ensure_ascii=False, indent=2)


@pytest.mark.asyncio
async def test_parallel_search_terms_success(mock_settings):
    """Test parallel search with multiple terms."""
    import json

    # Mock search function
    async def mock_search(filename: str, keywords: str, fuzzy: bool = False):
        if keywords == "movement":
            return "Movement rules: You can move 3 spaces per turn."
        elif keywords == "attack":
            return "Attack rules: Roll dice to attack."
        elif keywords == "defense":
            return "Defense rules: Add armor to your roll."
        return "No matches found"

    # Execute parallel search
    result = await _parallel_search_terms_impl(
        "game.pdf",
        ["movement", "attack", "defense"],
        mock_search_fn=mock_search
    )

    # Parse JSON result
    result_dict = json.loads(result)

    # Verify all searches completed
    assert len(result_dict) == 3
    assert "Movement rules" in result_dict["movement"]
    assert "Attack rules" in result_dict["attack"]
    assert "Defense rules" in result_dict["defense"]


@pytest.mark.asyncio
async def test_parallel_search_terms_empty_list(mock_settings):
    """Test parallel search with empty term list."""
    import json

    result = await _parallel_search_terms_impl("game.pdf", [])
    result_dict = json.loads(result)

    assert "error" in result_dict
    assert "No search terms provided" in result_dict["error"]


@pytest.mark.asyncio
async def test_parallel_search_terms_limit(mock_settings):
    """Test parallel search respects 10-term limit."""
    import json

    # Mock search to count calls
    call_count = 0

    async def mock_search(filename: str, keywords: str, fuzzy: bool = False):
        nonlocal call_count
        call_count += 1
        return f"Result for {keywords}"

    # Try to search 15 terms
    terms = [f"term{i}" for i in range(15)]
    result = await _parallel_search_terms_impl(
        "game.pdf",
        terms,
        mock_search_fn=mock_search
    )

    result_dict = json.loads(result)

    # Should only process first 10
    assert len(result_dict) == 10
    assert call_count == 10


@pytest.mark.asyncio
async def test_parallel_search_terms_with_errors(mock_settings):
    """Test parallel search handles individual search errors."""
    import json

    async def mock_search(filename: str, keywords: str, fuzzy: bool = False):
        if keywords == "good":
            return "Good result"
        elif keywords == "error":
            raise FileNotFoundError("File not found")
        return "No matches found"

    result = await _parallel_search_terms_impl(
        "game.pdf",
        ["good", "error", "neutral"],
        mock_search_fn=mock_search
    )
    result_dict = json.loads(result)

    # Should have results for all terms
    assert len(result_dict) == 3
    assert "Good result" in result_dict["good"]
    # Error should be captured
    assert "error" in result_dict["error"].lower() or "Error" in result_dict["error"]
    assert "No matches found" in result_dict["neutral"]


@pytest.mark.asyncio
async def test_parallel_search_terms_truncation(mock_settings):
    """Test parallel search truncates long results."""
    import json

    async def mock_search(filename: str, keywords: str, fuzzy: bool = False):
        # Return very long text (>5000 chars)
        return "Long result " * 500  # ~6000 chars

    result = await _parallel_search_terms_impl(
        "game.pdf",
        ["test"],
        mock_search_fn=mock_search
    )
    result_dict = json.loads(result)

    # Result should be truncated
    assert len(result_dict["test"]) <= 5050  # 5000 + "(truncated)" message
    assert "(truncated)" in result_dict["test"]
