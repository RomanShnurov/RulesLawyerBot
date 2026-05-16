"""Agent tool functions with async wrappers for blocking operations."""

import asyncio
import json
import re as _re
import subprocess
from functools import wraps
from pathlib import Path
from typing import Callable, TypeVar

from agents import function_tool
from rapidfuzz import fuzz

from src.rules_lawyer_bot.agent.repository import (
    RulesRepository,
    get_default_repository,
)
from src.rules_lawyer_bot.config import settings
from src.rules_lawyer_bot.utils.logger import logger
from src.rules_lawyer_bot.utils.safety import safe_execution, ugrep_semaphore
from src.rules_lawyer_bot.utils.text_readability import document_is_unreadable
from src.rules_lawyer_bot.utils.timer import ScopeTimer


def _repo() -> RulesRepository:
    """Return the default repository. Indirection allows test injection."""
    return get_default_repository()

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


def _safe_pdf_path(filename: str) -> Path:
    """Validate filename and resolve to absolute path inside pdf_storage_path.

    Delegates to the default repository's get_pdf_path.
    """
    return _repo().get_pdf_path(filename)


def _get_pdf_text_cache(pdf_path: Path) -> Path:
    """Return path to cached text extraction of a PDF.

    The cache is `<pdf_storage_path>/.cache/<pdf_name>.txt`, generated via
    `pdftotext -layout` which preserves form-feed (`\\f`) characters between
    pages. The cache is regenerated when the PDF's mtime is newer than the
    cache's mtime.

    Args:
        pdf_path: Absolute Path to the source PDF (already validated
            via _safe_pdf_path).

    Returns:
        Path to the .txt cache file.

    Raises:
        subprocess.CalledProcessError: If pdftotext fails.
    """
    cache_dir = pdf_path.parent / ".cache"
    cache_dir.mkdir(exist_ok=True)
    cache_path = cache_dir / (pdf_path.name + ".txt")

    needs_regen = (
        not cache_path.exists()
        or cache_path.stat().st_mtime < pdf_path.stat().st_mtime
    )

    if needs_regen:
        logger.debug(f"Generating PDF text cache: {cache_path}")
        # Write to a temp file then rename atomically to avoid torn reads
        # under concurrent access.
        import tempfile
        import os as _os
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".tmp",
            dir=str(cache_dir),
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp_path = Path(tmp.name)
        try:
            subprocess.run(
                ["pdftotext", "-layout", str(pdf_path), str(tmp_path)],
                check=True,
                capture_output=True,
                timeout=60,
            )
            # os.replace is atomic on both POSIX and Windows (within same fs)
            _os.replace(str(tmp_path), str(cache_path))
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    return cache_path


def _annotate_with_pages(
    cache_path: Path,
    ugrep_output: str,
    context_lines: int = 10,
    max_results: int = 30,
) -> list[dict]:
    """Parse ugrep output (`-bn` format) and emit per-page excerpts.

    Args:
        cache_path: Path to the cached PDF text file.
        ugrep_output: stdout from `ugrep -bn ...` — lines of form
            `<line_no>:<byte_offset>:<line_text>`.
        context_lines: Number of lines to include before/after each match.
        max_results: Cap to avoid unbounded output.

    Returns:
        List of {"page": int, "excerpt": str} dicts, deduped by line number.
    """
    text_bytes = cache_path.read_bytes()
    text = text_bytes.decode("utf-8", errors="replace")
    text_lines = text.splitlines()

    results: list[dict] = []
    seen_lines: set[int] = set()

    for line in ugrep_output.splitlines():
        if not line or line.startswith("--"):
            continue
        m = _re.match(r"^(\d+):(\d+):(.*)$", line)
        if not m:
            continue
        line_no = int(m.group(1))
        byte_offset = int(m.group(2))
        if line_no in seen_lines:
            continue
        seen_lines.add(line_no)

        page = text_bytes[:byte_offset].count(b"\f") + 1

        start = max(0, line_no - context_lines - 1)
        end = min(len(text_lines), line_no + context_lines)
        excerpt = "\n".join(text_lines[start:end]).strip()

        results.append({"page": page, "excerpt": excerpt})
        if len(results) >= max_results:
            break

    return results


def _unreadable_payload(tool_name: str) -> str:
    """Sandboxed no_match telling the agent the rulebook is unreadable.

    Returned deterministically for every search/read against a document
    whose whole text layer is broken-font gibberish, so the agent
    escalates to the user in one turn instead of looping every keyword to
    MaxTurns on a document that can never yield an answer.
    """
    return _sandbox(
        tool_name,
        json.dumps(
            {
                "status": "no_match",
                "data": [],
                "meta": {"reason": "unreadable_text_layer"},
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


def _sandbox(tool_name: str, payload: str) -> str:
    """Wrap tool output in sandbox tags so the LLM treats content as untrusted data.

    The system prompt instructs the model not to follow instructions found
    inside <tool_output> blocks. This is a defence against prompt injection
    via PDF content.
    """
    return f'<tool_output source="{tool_name}">\n{payload}\n</tool_output>'


@function_tool
@safe_execution
@async_tool
def find_game_by_name(query: str) -> str:
    """Find game information by Russian or English name using fuzzy matching.

    Uses rapidfuzz.token_set_ratio for tolerance to typos, word reordering,
    and partial matches. Threshold is 65/100. Results are sorted by
    confidence DESC and include the `confidence` field (score / 100).

    Args:
        query: Game name in Russian, English, or transliteration

    Returns:
        JSON string with matching game(s) information including confidence.
    """
    with ScopeTimer(f"find_game_by_name('{query}')"):
        index_path = Path(settings.pdf_storage_path) / "games_index.json"

        if not index_path.exists():
            logger.warning(f"Games index not found at {index_path}")
            return json.dumps({
                "found": False,
                "error": "Games index not configured. Using fallback search.",
                "suggestion": "Create games_index.json in rules_pdfs/"
            }, ensure_ascii=False)

        try:
            with open(index_path, encoding="utf-8") as f:
                index_data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load games index: {e}")
            return json.dumps({
                "found": False,
                "error": f"Failed to load games index: {str(e)}"
            }, ensure_ascii=False)

        # Repository serves as a smoke check that the index is readable.
        # Fuzzy matching scans the full index regardless of substring hits.
        all_games = index_data.get("games", [])

        query_stripped = query.strip()
        threshold = 65

        scored: list[tuple[dict, int]] = []
        for game in all_games:
            names = [game["english_name"]] + game.get("russian_names", [])
            best = max(
                (fuzz.token_set_ratio(query_stripped, name) for name in names),
                default=0,
            )
            if best >= threshold:
                scored.append((game, best))

        scored.sort(key=lambda x: x[1], reverse=True)

        if not scored:
            return json.dumps({
                "found": False,
                "query": query,
                "suggestion": "Try search_filenames() or list_directory_tree()"
            }, ensure_ascii=False)

        def _with_confidence(game: dict, score: int) -> dict:
            return {**game, "confidence": round(score / 100, 2)}

        if len(scored) == 1:
            game, score = scored[0]
            return json.dumps({
                "found": True,
                "match_type": "exact" if score >= 90 else "fuzzy",
                "game": _with_confidence(game, score),
            }, ensure_ascii=False, indent=2)

        return json.dumps({
            "found": True,
            "match_type": "multiple",
            "games": [_with_confidence(g, s) for g, s in scored],
        }, ensure_ascii=False, indent=2)


@function_tool
@safe_execution
@async_tool
def search_filenames(query: str) -> str:
    """Search for PDF files by filename in the rules library.

    Args:
        query: Search term (game name or part of filename)

    Returns:
        List of matching filenames or error message
    """
    with ScopeTimer(f"search_filenames('{query}')"):
        pdfs = _repo().list_pdf_files()

        # Case-insensitive search
        query_lower = query.lower()
        matches = [
            p.name for p in pdfs if query_lower in p.name.lower()
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


async def _search_inside_file_ugrep_impl(
    filename: str, keywords: str, fuzzy: bool = False
) -> str:
    """Internal implementation of ugrep search, returning sandboxed JSON.

    Separated from the @function_tool wrapper so other tools
    (e.g. parallel_search_terms) can call it directly.
    """
    with ScopeTimer(f"search_inside_file_ugrep('{filename}', '{keywords}')"):
        pdf_path = _safe_pdf_path(filename)
        if not pdf_path.exists():
            raise FileNotFoundError(f"'{filename}'")

        cache_path = _get_pdf_text_cache(pdf_path)

        # If the whole text layer is broken (font with no ToUnicode CMap →
        # pdftotext emits single-letter gibberish), no keyword can ever
        # yield a usable excerpt. Tell the agent up front so it escalates
        # to the user instead of looping every term to MaxTurns.
        if document_is_unreadable(
            cache_path.read_text(encoding="utf-8", errors="replace")
        ):
            return _unreadable_payload("search_inside_file_ugrep")

        # Run ugrep against the cached text with byte offsets + line numbers
        cmd = [
            "ugrep",
            "-%",  # Boolean query mode (space=AND, |=OR, -=NOT)
            "-i",  # Case insensitive
            "-bn",  # byte offset + line number per match
            "--no-group-separator",
            keywords,
            str(cache_path),
        ]
        if fuzzy:
            cmd.insert(2, "-Z")

        logger.debug("Searching with ugrep command: " + " ".join(cmd))

        async with ugrep_semaphore:
            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

        if result.returncode == 0:
            matches = _annotate_with_pages(cache_path, result.stdout)
            payload = {
                "status": "ok",
                "data": matches,
                "meta": {
                    "truncated": False,
                    "total_matches": len(matches),
                    "shown": len(matches),
                },
            }
        elif result.returncode == 1:
            payload = {
                "status": "no_match",
                "data": [],
                "meta": {"total_matches": 0, "shown": 0},
            }
        else:
            error = result.stderr.strip()
            logger.error(f"ugrep error: {error}")
            payload = {
                "status": "error",
                "data": [],
                "meta": {"message": error},
            }

        return _sandbox(
            "search_inside_file_ugrep",
            json.dumps(payload, ensure_ascii=False, indent=2),
        )


@function_tool
@safe_execution
async def search_inside_file_ugrep(
    filename: str, keywords: str, fuzzy: bool = False
) -> str:
    """Search inside a PDF file using ugrep with Boolean pattern support.

    Args:
        filename: Name of the PDF file (must exist in rules_pdfs/)
        keywords: Search keywords with Boolean logic support:
                  - Space-separated terms use AND: "attack armor" finds both
                  - Pipe | means OR: "move|teleport" finds either
                  - Dash - means NOT: "attack -ranged" excludes ranged
                  - Combine: "attack|strike armor -magic"
                  - Quotes for exact phrases: '"end of turn"'
        fuzzy: Enable fuzzy matching to handle typos (default: False)

    Returns:
        Matching text snippets with context or error message

    Examples:
        search_inside_file_ugrep("game.pdf", "combat damage")
        search_inside_file_ugrep("game.pdf", "move|teleport enemy")
        search_inside_file_ugrep("game.pdf", "attack -ranged")
        search_inside_file_ugrep("game.pdf", "movment", fuzzy=True)
    """
    return await _search_inside_file_ugrep_impl(filename, keywords, fuzzy)


@function_tool
@safe_execution
async def parallel_search_terms(filename: str, terms: list[str], fuzzy: bool = False) -> str:
    """Search for multiple terms in parallel within a PDF.

    Returns sandboxed JSON: {status, data: {term: {status, data, meta}}, meta}.
    Each per-term entry has the same shape as search_inside_file_ugrep.
    """
    with ScopeTimer(f"parallel_search_terms('{filename}', {len(terms)} terms)"):
        if not terms:
            return _sandbox(
                "parallel_search_terms",
                json.dumps(
                    {"status": "error", "data": {}, "meta": {"message": "No terms"}},
                    ensure_ascii=False,
                ),
            )

        if len(terms) > 10:
            logger.warning(f"Too many terms ({len(terms)}), limiting to 10")
            terms = terms[:10]

        logger.info(f"Launching {len(terms)} parallel searches in '{filename}'")

        tasks = [
            _search_inside_file_ugrep_impl(filename, term, fuzzy=fuzzy)
            for term in terms
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        per_term: dict[str, dict] = {}
        for term, raw in zip(terms, raw_results):
            if isinstance(raw, Exception):
                per_term[term] = {
                    "status": "error",
                    "data": [],
                    "meta": {"message": str(raw)},
                }
            else:
                # raw is a sandboxed JSON string; unwrap and parse
                inner_start = raw.find(">\n") + 2
                inner_end = raw.rfind("\n</tool_output>")
                try:
                    per_term[term] = json.loads(raw[inner_start:inner_end])
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"parallel_search_terms: failed to parse sandboxed result for term '{term}': {e}"
                    )
                    per_term[term] = {
                        "status": "error",
                        "data": [],
                        "meta": {"message": "could not parse per-term result"},
                    }

        payload = {
            "status": "ok",
            "data": per_term,
            "meta": {"terms_searched": len(terms)},
        }

        return _sandbox(
            "parallel_search_terms",
            json.dumps(payload, ensure_ascii=False, indent=2),
        )


@function_tool
@safe_execution
@async_tool
def read_full_document(filename: str) -> str:
    """Fallback: Read entire PDF content using pdftotext cache.

    Use this when ugrep fails or you need full context.

    Returns sandboxed JSON: {status, data: [{page, text}], meta}.
    """
    with ScopeTimer(f"read_full_document('{filename}')"):
        pdf_path = _safe_pdf_path(filename)
        if not pdf_path.exists():
            raise FileNotFoundError(f"'{filename}'")

        cache_path = _get_pdf_text_cache(pdf_path)
        full_text = cache_path.read_text(encoding="utf-8", errors="replace")

        # Same broken-text-layer guard as the search tools: a wholly
        # unreadable document is a dead end — say so once instead of
        # dumping gibberish the agent will loop on.
        if document_is_unreadable(full_text):
            return _unreadable_payload("read_full_document")

        pages_text = full_text.split("\f")

        # Build per-page data; truncate aggressively to avoid context overflow
        data = [
            {"page": i + 1, "text": text}
            for i, text in enumerate(pages_text)
            if text.strip()
        ]

        # Soft cap: a single full-document dump must not be able to fill
        # the model's context window (especially for Cyrillic, which
        # tokenizes inefficiently). Targeted search tools are preferred.
        max_chars = settings.max_full_document_chars
        total_chars = 0
        truncated = False
        kept: list[dict] = []
        for entry in data:
            if total_chars + len(entry["text"]) > max_chars:
                truncated = True
                break
            kept.append(entry)
            total_chars += len(entry["text"])

        payload = {
            "status": "ok",
            "data": kept,
            "meta": {
                "truncated": truncated,
                "total_pages": len(data),
                "shown_pages": len(kept),
            },
        }

        return _sandbox(
            "read_full_document",
            json.dumps(payload, ensure_ascii=False, indent=2),
        )


@function_tool
@safe_execution
@async_tool
def list_directory_tree(path: str = "", max_depth: int = 3) -> str:
    """List directory structure as a tree.

    Use this FIRST to:
    1. Discover all available games when user asks "what games do you have?"
    2. Understand the structure of the rules library before searching

    Args:
        path: Subdirectory path relative to rules library (empty = root)
        max_depth: Maximum depth to display (default: 3)

    Returns:
        - For root-level call with small library (<20 PDFs): Clean numbered game list
        - Otherwise: Tree-formatted directory structure showing folders and PDFs
    """
    with ScopeTimer(f"list_directory_tree('{path}', max_depth={max_depth})"):
        base_path = Path(settings.pdf_storage_path)
        target_path = base_path / path if path else base_path

        if not target_path.exists():
            return f"Error: Path '{path}' not found"

        if not target_path.is_dir():
            return f"Error: '{path}' is not a directory"

        # Smart formatting for game discovery at root level
        if path == "" and target_path == base_path:
            pdf_files = sorted([p.stem for p in _repo().list_pdf_files()])

            # Small library: return clean numbered list for discovery
            if len(pdf_files) <= 20:
                output = f"Available games ({len(pdf_files)}):\n"
                output += "\n".join(f"{i+1}. {name}" for i, name in enumerate(pdf_files))

                logger.debug(f"Game discovery list: {output}")
                return output

        # Default tree structure for navigation or large libraries
        lines = [f"{target_path.name}/"]
        _build_tree(target_path, lines, "", max_depth, 0)

        output = "\n".join(lines)

        logger.debug(f"Directory tree output: {output}")

        # Truncate to avoid token overflow
        if len(output) > 10000:
            output = output[:10000] + "\n...(truncated)"

        return output


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
