"""Agent tool functions with async wrappers for blocking operations."""

import asyncio
import subprocess
from functools import wraps
from pathlib import Path
from typing import Callable, TypeVar

from agents import function_tool
from pypdf import PdfReader

from src.config import settings
from src.utils.logger import logger
from src.utils.timer import ScopeTimer

# Type variable for decorator
F = TypeVar("F", bound=Callable)


def async_tool(func: F) -> F:
    """Decorator to run synchronous tool functions in thread pool.

    CRITICAL: This prevents blocking the Telegram asyncio event loop
    when calling subprocess.run() or other blocking I/O.

    Args:
        func: Synchronous function to wrap

    Returns:
        Async function that runs in thread pool
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    return wrapper


@function_tool
@async_tool
def search_filenames(query: str) -> str:
    """Search for PDF files by filename in the rules library.

    Args:
        query: Search term (game name or part of filename)

    Returns:
        List of matching filenames or error message
    """
    with ScopeTimer(f"search_filenames('{query}')"):
        try:
            pdf_dir = Path(settings.pdf_storage_path)
            if not pdf_dir.exists():
                return f"Error: PDF directory not found at {pdf_dir}"

            # Case-insensitive search
            query_lower = query.lower()
            matches = [
                f.name for f in pdf_dir.glob("*.pdf") if query_lower in f.name.lower()
            ]

            if not matches:
                return f"No PDF files found matching '{query}'"

            # Limit results to avoid token overflow
            if len(matches) > 50:
                matches = matches[:50]
                return f"Found {len(matches)}+ files (showing first 50):\n" + "\n".join(
                    matches
                )

            return f"Found {len(matches)} file(s):\n" + "\n".join(matches)

        except Exception as e:
            logger.exception(f"Error in search_filenames: {e}")
            return f"Error searching files: {str(e)}"


@function_tool
@async_tool
def search_inside_file_ugrep(filename: str, keywords: str) -> str:
    """Search inside a PDF file using ugrep for fast regex matching.

    Args:
        filename: Name of the PDF file (must exist in rules_pdfs/)
        keywords: Search keywords or regex pattern

    Returns:
        Matching text snippets or error message
    """
    with ScopeTimer(f"search_inside_file_ugrep('{filename}', '{keywords}')"):
        try:
            pdf_path = Path(settings.pdf_storage_path) / filename
            if not pdf_path.exists():
                return f"Error: File '{filename}' not found"

            # Run ugrep with PDF filter
            # -i: case insensitive
            # --filter: convert PDF to text on-the-fly
            # -C 2: show 2 lines of context
            result = subprocess.run(
                [
                    "ugrep",
                    "-i",  # Case insensitive
                    "--filter=pdf:pdftotext - -",  # PDF text extraction
                    "-C",
                    "2",  # 2 lines of context
                    keywords,
                    str(pdf_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,  # Prevent hanging
            )

            if result.returncode == 0:
                output = result.stdout.strip()
                # Truncate to avoid token overflow
                if len(output) > 10000:
                    output = output[:10000] + "\n...(truncated)"
                return output if output else "No matches found"

            elif result.returncode == 1:
                return "No matches found"

            else:
                error = result.stderr.strip()
                logger.error(f"ugrep error: {error}")
                return f"Search error: {error}"

        except subprocess.TimeoutExpired:
            return "Search timed out (>30s). Please try more specific keywords."

        except FileNotFoundError:
            return (
                "Error: 'ugrep' tool not installed. "
                "Please install: apt-get install ugrep (Linux) or brew install ugrep (macOS)"
            )

        except Exception as e:
            logger.exception(f"Error in search_inside_file_ugrep: {e}")
            return f"Search failed: {str(e)}"


@function_tool
@async_tool
def read_full_document(filename: str) -> str:
    """Fallback: Read entire PDF content using pypdf library.

    Use this when ugrep fails or is unavailable.

    Args:
        filename: Name of the PDF file

    Returns:
        Full text content (truncated to 100k chars) or error message
    """
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

            # Truncate to avoid context overflow
            if len(full_text) > 100000:
                full_text = full_text[:100000] + "\n...(truncated at 100k chars)"

            return full_text

        except Exception as e:
            logger.exception(f"Error in read_full_document: {e}")
            return f"Failed to read PDF: {str(e)}"


@function_tool
@async_tool
def list_directory_tree(path: str = "", max_depth: int = 3) -> str:
    """List directory structure as a tree.

    Use this FIRST to understand the structure of the rules library
    before searching for specific files.

    Args:
        path: Subdirectory path relative to rules library (empty = root)
        max_depth: Maximum depth to display (default: 3)

    Returns:
        Tree-formatted directory structure showing folders and PDF files
    """
    with ScopeTimer(f"list_directory_tree('{path}', max_depth={max_depth})"):
        try:
            base_path = Path(settings.pdf_storage_path)
            target_path = base_path / path if path else base_path

            if not target_path.exists():
                return f"Error: Path '{path}' not found"

            if not target_path.is_dir():
                return f"Error: '{path}' is not a directory"

            lines = [f"{target_path.name}/"]
            _build_tree(target_path, lines, "", max_depth, 0)

            output = "\n".join(lines)

            logger.debug(f"Directory tree output: {output}")

            # Truncate to avoid token overflow
            if len(output) > 10000:
                output = output[:10000] + "\n...(truncated)"

            return output

        except Exception as e:
            logger.exception(f"Error in list_directory_tree: {e}")
            return f"Error listing directory: {str(e)}"


def _build_tree(
    directory: Path, lines: list[str], prefix: str, max_depth: int, current_depth: int
) -> None:
    """Recursively build tree structure.

    Args:
        directory: Current directory to list
        lines: List to append formatted lines
        prefix: Current indentation prefix
        max_depth: Maximum depth limit
        current_depth: Current recursion depth
    """
    if current_depth >= max_depth:
        return

    # Get items: directories first, then PDF files only
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
            _build_tree(item, lines, prefix + extension, max_depth, current_depth + 1)
        else:
            lines.append(f"{prefix}{connector}{item.name}")
