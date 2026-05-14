"""Abstraction layer for game metadata and PDF file access.

Provides a Protocol (RulesRepository) with two implementations:
- FileSystemRulesRepository: reads from settings.pdf_storage_path.
- InMemoryRulesRepository: for tests, no filesystem dependency.

Scope is limited to operations that don't involve subprocess (pdftotext,
ugrep) - those remain in tools.py because the cost of abstracting them
exceeds the testability benefit.
"""
import json
from pathlib import Path
from typing import Protocol


class RulesRepository(Protocol):
    """Abstract source of game metadata and PDF files."""

    def find_game_by_query(self, query: str) -> list[dict]:
        """Return matching games from the index. Pure data access (no fuzzy logic)."""
        ...

    def list_pdf_files(self) -> list[Path]:
        """Return all PDF paths in the library."""
        ...

    def get_pdf_path(self, filename: str) -> Path:
        """Resolve a PDF filename to a validated absolute Path.

        Raises ValueError on path traversal or non-PDF extension.
        """
        ...


class FileSystemRulesRepository:
    """Default repository: reads from a base PDF storage directory."""

    def __init__(self, base_path: Path):
        self.base_path = Path(base_path).resolve()

    def find_game_by_query(self, query: str) -> list[dict]:
        """Substring match against games_index.json (case-insensitive).

        NOTE: This is a simple substring match used as the foundation for
        higher-level fuzzy matching in tools.find_game_by_name. Fuzzy
        ranking lives at the tool layer, not the repository layer, so
        the repository stays focused on data access.
        """
        index_path = self.base_path / "games_index.json"
        if not index_path.exists():
            return []
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

        q = query.lower().strip()
        matches: list[dict] = []
        for game in data.get("games", []):
            if q in game["english_name"].lower():
                matches.append(game)
                continue
            for ru in game.get("russian_names", []):
                if q in ru.lower():
                    matches.append(game)
                    break
        return matches

    def list_pdf_files(self) -> list[Path]:
        return sorted(self.base_path.glob("*.pdf"))

    def get_pdf_path(self, filename: str) -> Path:
        candidate = (self.base_path / filename).resolve()
        if not candidate.is_relative_to(self.base_path):
            raise ValueError(f"Invalid filename: {filename!r}")
        if candidate.suffix.lower() != ".pdf":
            raise ValueError(f"Invalid filename: {filename!r}")
        return candidate


class InMemoryRulesRepository:
    """In-memory repository for tests.

    Args:
        games: List of game dicts (same shape as games_index.json entries).
        pdfs: Mapping of filename -> bytes content. The bytes are not used
            for the Protocol methods but model the storage.
    """

    def __init__(
        self,
        games: list[dict] | None = None,
        pdfs: dict[str, bytes] | None = None,
    ):
        self._games = games or []
        self._pdfs = pdfs or {}

    def find_game_by_query(self, query: str) -> list[dict]:
        q = query.lower().strip()
        matches: list[dict] = []
        for game in self._games:
            if q in game["english_name"].lower():
                matches.append(game)
                continue
            for ru in game.get("russian_names", []):
                if q in ru.lower():
                    matches.append(game)
                    break
        return matches

    def list_pdf_files(self) -> list[Path]:
        return [Path(name) for name in self._pdfs]

    def get_pdf_path(self, filename: str) -> Path:
        if filename not in self._pdfs:
            raise ValueError(f"Invalid filename: {filename!r}")
        if not filename.lower().endswith(".pdf"):
            raise ValueError(f"Invalid filename: {filename!r}")
        return Path(filename)


def get_default_repository() -> RulesRepository:
    """Build the default repository from settings."""
    from src.rules_lawyer_bot.config import settings
    return FileSystemRulesRepository(Path(settings.pdf_storage_path))
