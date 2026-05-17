"""Tests for the deterministic pre-agent game resolver."""

import json
from pathlib import Path

import pytest

from src.rules_lawyer_bot.agent import game_resolver
from src.rules_lawyer_bot.agent.repository import FileSystemRulesRepository


@pytest.fixture
def repo(mock_settings, monkeypatch):
    # Resolver knobs already exist on settings (config task); pin them so the
    # test is independent of future default changes.
    for name, val in {
        "resolver_enabled": True,
        "resolver_resolve_threshold": 90,
        "resolver_gap_min": 8,
        "resolver_multi_threshold": 75,
    }.items():
        monkeypatch.setattr(mock_settings, name, val, raising=False)

    pdf_dir = Path(mock_settings.pdf_storage_path)
    for fn in [
        "Wingspan.pdf",
        "Gloomhaven.pdf",
        "Gloomhaven JOTL.pdf",
        "Azul.pdf",
    ]:
        (pdf_dir / fn).write_bytes(b"%PDF-1.4")
    index = {
        "games": [
            {
                "english_name": "Wingspan",
                "russian_names": ["Крылья"],
                "pdf_files": ["Wingspan.pdf"],
            },
            {
                "english_name": "Gloomhaven",
                "russian_names": ["Мрачная гавань"],
                "pdf_files": ["Gloomhaven.pdf"],
            },
            {
                "english_name": "Gloomhaven: Jaws of the Lion",
                "russian_names": ["Львиный зев"],
                "pdf_files": ["Gloomhaven JOTL.pdf"],
            },
        ]
    }
    (pdf_dir / "games_index.json").write_text(
        json.dumps(index, ensure_ascii=False), encoding="utf-8"
    )
    game_resolver.clear_corpus_cache()
    return FileSystemRulesRepository(pdf_dir)


def test_resolved_exact_english(repo):
    r = game_resolver.resolve("Wingspan", repo=repo)
    assert r.kind == "resolved"
    assert r.game == "Wingspan" and r.pdf == "Wingspan.pdf"


def test_resolved_russian_name(repo):
    r = game_resolver.resolve("Крылья", repo=repo)
    assert r.kind == "resolved" and r.game == "Wingspan"


def test_resolved_inside_sentence(repo):
    r = game_resolver.resolve("сколько очков за птицу в Wingspan?", repo=repo)
    assert r.kind == "resolved" and r.game == "Wingspan"


def test_multiple_close_variants(repo):
    r = game_resolver.resolve("gloomhaven", repo=repo)
    assert r.kind == "multiple"
    names = {c["english_name"] for c in r.candidates}
    assert "Gloomhaven" in names and "Gloomhaven: Jaws of the Lion" in names


def test_unknown_title_is_ambiguous_not_absent(repo):
    # The resolver never declares a game absent: an unknown title falls
    # through to the agent (which states "not in library" honestly).
    r = game_resolver.resolve("Героям здесь не место", repo=repo)
    assert r.kind == "ambiguous"


def test_long_question_with_no_game_is_ambiguous(repo):
    r = game_resolver.resolve(
        "подскажи пожалуйста как именно нужно правильно подсчитывать "
        "финальные очки в конце партии",
        repo=repo,
    )
    assert r.kind == "ambiguous"


def test_disabled_returns_ambiguous(repo, monkeypatch):
    import src.rules_lawyer_bot.config as cfg

    monkeypatch.setattr(cfg.settings, "resolver_enabled", False, raising=False)
    game_resolver.clear_corpus_cache()
    r = game_resolver.resolve("Wingspan", repo=repo)
    assert r.kind == "ambiguous"


def test_normalize_collapses_and_casefolds():
    assert game_resolver._normalize("  Wing  SPAN  ") == "wing span"
