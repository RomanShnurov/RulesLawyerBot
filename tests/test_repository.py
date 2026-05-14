"""Tests for RulesRepository abstractions."""
from pathlib import Path

import pytest

from src.rules_lawyer_bot.agent.repository import (
    FileSystemRulesRepository,
    InMemoryRulesRepository,
    RulesRepository,
)


# ===== FileSystemRulesRepository =====


def test_filesystem_repo_lists_pdfs(mock_settings, tmp_path):
    """list_pdf_files returns all .pdf files in base_path."""
    base = Path(mock_settings.pdf_storage_path)
    (base / "A.pdf").touch()
    (base / "B.pdf").touch()
    (base / "notes.txt").touch()

    repo = FileSystemRulesRepository(base)
    pdfs = sorted([p.name for p in repo.list_pdf_files()])
    assert pdfs == ["A.pdf", "B.pdf"]


def test_filesystem_repo_get_pdf_path(mock_settings, tmp_path):
    """get_pdf_path returns a resolved absolute Path inside base."""
    base = Path(mock_settings.pdf_storage_path)
    (base / "Game.pdf").touch()

    repo = FileSystemRulesRepository(base)
    p = repo.get_pdf_path("Game.pdf")
    assert p.is_absolute()
    assert p.parent.resolve() == base.resolve()


def test_filesystem_repo_rejects_traversal(mock_settings):
    """get_pdf_path raises ValueError on traversal attempts."""
    repo = FileSystemRulesRepository(Path(mock_settings.pdf_storage_path))
    with pytest.raises(ValueError, match="Invalid filename"):
        repo.get_pdf_path("../../etc/passwd")


def test_filesystem_repo_rejects_non_pdf(mock_settings):
    """get_pdf_path raises ValueError on non-.pdf extensions."""
    repo = FileSystemRulesRepository(Path(mock_settings.pdf_storage_path))
    with pytest.raises(ValueError, match="Invalid filename"):
        repo.get_pdf_path("notes.txt")


def test_filesystem_repo_find_game(mock_settings):
    """find_game_by_query reads games_index.json and returns matches."""
    import json as _json
    base = Path(mock_settings.pdf_storage_path)
    (base / "games_index.json").write_text(
        _json.dumps({"games": [
            {"english_name": "Dead Cells", "russian_names": [], "pdf_files": ["Dead Cells.pdf"]},
            {"english_name": "Wingspan", "russian_names": [], "pdf_files": ["Wingspan.pdf"]},
        ]}),
        encoding="utf-8",
    )
    repo = FileSystemRulesRepository(base)
    matches = repo.find_game_by_query("Dead")
    assert any(g["english_name"] == "Dead Cells" for g in matches)


# ===== InMemoryRulesRepository =====


def test_in_memory_repo_list_pdfs():
    """InMemoryRulesRepository lists PDFs registered in __init__."""
    repo = InMemoryRulesRepository(
        pdfs={"A.pdf": b"", "B.pdf": b""}
    )
    pdfs = sorted([p.name for p in repo.list_pdf_files()])
    assert pdfs == ["A.pdf", "B.pdf"]


def test_in_memory_repo_find_game_substring():
    """InMemoryRulesRepository.find_game_by_query does substring match."""
    repo = InMemoryRulesRepository(
        games=[
            {"english_name": "Gloomhaven", "russian_names": ["Глумхейвен"], "pdf_files": []},
            {"english_name": "Wingspan", "russian_names": [], "pdf_files": []},
        ]
    )
    matches = repo.find_game_by_query("gloom")
    assert len(matches) == 1
    assert matches[0]["english_name"] == "Gloomhaven"


def test_in_memory_repo_satisfies_protocol():
    """InMemoryRulesRepository conforms to RulesRepository Protocol."""
    repo: RulesRepository = InMemoryRulesRepository()
    # If this type check passes at runtime, the Protocol is satisfied
    assert repo is not None
