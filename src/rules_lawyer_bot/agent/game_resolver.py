"""Deterministic pre-agent game resolver.

Game identification over the <=241-PDF catalog is pure string matching, but
the LLM was doing it across up to 4 sequential proxy round-trips (~2-4s
each). This module resolves the common cases (clear hit / several close /
genuinely absent) deterministically before the agent runs, so the model is
reached only for the genuinely ambiguous residue.

Corpus = every games_index.json entry (english_name + russian_names) UNIONED
with every PDF filename stem (closes the 134-indexed / 241-on-disk gap). No
transliteration dependency: the index russian_names are the RU<->EN bridge.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from rapidfuzz import fuzz

from src.rules_lawyer_bot.agent.repository import (
    RulesRepository,
    get_default_repository,
)
from src.rules_lawyer_bot.config import settings
from src.rules_lawyer_bot.utils.logger import logger


@dataclass(frozen=True)
class _Entry:
    game: str
    pdf: str
    names: tuple[str, ...]


@dataclass
class ResolverResult:
    kind: Literal["resolved", "multiple", "absent", "ambiguous"]
    game: Optional[str] = None
    pdf: Optional[str] = None
    score: float = 0.0
    candidates: list[dict] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


def _normalize(s: str) -> str:
    """Lowercase + NFKC + whitespace-collapse. Cyrillic is preserved."""
    s = unicodedata.normalize("NFKC", s).casefold().strip()
    return " ".join(s.split())


_corpus_cache: list[_Entry] | None = None
_corpus_sig: tuple | None = None


def clear_corpus_cache() -> None:
    """Reset the module corpus cache (used by tests for isolation)."""
    global _corpus_cache, _corpus_sig
    _corpus_cache = None
    _corpus_sig = None


def _index_path() -> Path:
    return Path(settings.pdf_storage_path) / "games_index.json"


def _corpus_signature(repo: RulesRepository) -> tuple:
    idx = _index_path()
    idx_mtime = idx.stat().st_mtime if idx.exists() else 0.0
    return (idx_mtime, len(repo.list_pdf_files()), settings.pdf_storage_path)


def _build_corpus(repo: RulesRepository) -> list[_Entry]:
    entries: list[_Entry] = []
    seen: set[str] = set()

    idx = _index_path()
    if idx.exists():
        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {"games": []}
        for g in data.get("games", []):
            pdf_files = g.get("pdf_files") or []
            if not pdf_files:
                continue
            names = tuple(
                _normalize(n)
                for n in [g["english_name"], *g.get("russian_names", [])]
                if n
            )
            entries.append(
                _Entry(game=g["english_name"], pdf=pdf_files[0], names=names)
            )
            seen.update(pdf_files)

    for p in repo.list_pdf_files():
        if p.name in seen or p.name == "games_index.json":
            continue
        entries.append(_Entry(game=p.stem, pdf=p.name, names=(_normalize(p.stem),)))
    return entries


def _get_corpus(repo: RulesRepository) -> list[_Entry]:
    global _corpus_cache, _corpus_sig
    sig = _corpus_signature(repo)
    if _corpus_cache is None or sig != _corpus_sig:
        _corpus_cache = _build_corpus(repo)
        _corpus_sig = sig
        logger.debug("[Resolver] corpus rebuilt: %d entries", len(_corpus_cache))
    return _corpus_cache


def resolve(
    query: str,
    repo: RulesRepository | None = None,
    *,
    is_answer: bool = False,
) -> ResolverResult:
    """Resolve a user query to a library game without the LLM where possible.

    `is_answer=True` marks a reply to a clarification: only then is the
    text expected to BE a game title, so only then may the resolver
    proactively declare the game absent. On a fresh message a low score
    means "no game named here" (a generic rules question), NOT "this game
    does not exist" — that falls through to the agent.
    """
    if not settings.resolver_enabled:
        return ResolverResult(kind="ambiguous")

    repo = repo or get_default_repository()
    q = _normalize(query)
    if not q:
        return ResolverResult(kind="ambiguous")

    corpus = _get_corpus(repo)
    if not corpus:
        return ResolverResult(kind="ambiguous")

    scored: list[tuple[_Entry, float]] = []
    for e in corpus:
        best = 0.0
        for name in e.names:
            if not name:
                continue
            best = max(
                best,
                float(fuzz.token_set_ratio(q, name)),
                float(fuzz.partial_ratio(q, name)),
            )
        scored.append((e, best))
    scored.sort(key=lambda x: x[1], reverse=True)

    top_e, top = scored[0]
    second = scored[1][1] if len(scored) > 1 else 0.0

    # Band 1: confident unique hit -> resolve, LLM skips identification.
    if (
        top >= settings.resolver_resolve_threshold
        and (top - second) >= settings.resolver_gap_min
    ):
        return ResolverResult(
            kind="resolved", game=top_e.game, pdf=top_e.pdf, score=top
        )

    # Band 2: several close, mapping to different games -> deterministic
    # selection UI (no LLM).
    near = [
        (e, s)
        for e, s in scored
        if s >= settings.resolver_multi_threshold
        and (top - s) <= settings.resolver_gap_min
    ]
    if len({e.game for e, _ in near}) > 1:
        cands: list[dict] = []
        for e, s in near:
            if any(c["english_name"] == e.game for c in cands):
                continue
            cands.append(
                {
                    "english_name": e.game,
                    "pdf_filename": e.pdf,
                    "confidence": round(s / 100, 2),
                }
            )
            if len(cands) == 5:
                break
        return ResolverResult(kind="multiple", candidates=cands, score=top)

    # Band 3: nothing close -> absent, BUT only when the user is answering
    # a clarification (the text is then expected to be a title). A low
    # score on a FRESH message just means no game is named (a generic
    # rules question) — that must fall through to the agent, never be
    # answered "this game does not exist".
    if is_answer and top < settings.resolver_absent_threshold:
        sugg: list[str] = []
        for e, _ in scored[:3]:
            if e.game not in sugg:
                sugg.append(e.game)
        return ResolverResult(kind="absent", suggestions=sugg, score=top)

    return ResolverResult(kind="ambiguous", score=top)
