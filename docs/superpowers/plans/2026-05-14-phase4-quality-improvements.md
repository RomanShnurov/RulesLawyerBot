# Фаза 4: Quality Improvements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть 4 nice-to-have пункта из отчёта ai-engineer: lazy agent singleton, few-shot examples модуль, fuzzy matching через rapidfuzz, RulesRepository слой (ограниченный scope).

**Architecture:** Каждый из 4 пунктов — независимый, идёт атомарным коммитом. Lazy singleton через `lru_cache`. Few-shot examples — новый pacakage `agent/prompts/`, по умолчанию выключен. Fuzzy через `rapidfuzz.fuzz.token_set_ratio` с порогом 65 и confidence в ответе. RulesRepository — Protocol + FileSystemRulesRepository, абстрагирующий ТОЛЬКО game index + PDF path discovery (subprocess-логика остаётся в `tools.py`).

**Tech Stack:** rapidfuzz>=3.0 (новая dep), functools.lru_cache, typing.Protocol, pytest.

**Spec:** `docs/superpowers/specs/2026-05-14-phase4-quality-improvements-design.md`.

---

## Файловая структура

**Изменяемые файлы:**
- `src/rules_lawyer_bot/agent/definition.py` — заменить import-time singleton на lazy factory; добавить опциональную инъекцию few-shot.
- `src/rules_lawyer_bot/agent/tools.py` — fuzzy matching в `find_game_by_name`; wire-up репозитория для game index / PDF path.
- `src/rules_lawyer_bot/handlers/messages.py` — `rules_agent` → `get_rules_agent()`.
- `src/rules_lawyer_bot/config.py` — поле `enable_few_shot_examples`.
- `pyproject.toml` — rapidfuzz dep.

**Создаваемые файлы:**
- `src/rules_lawyer_bot/agent/prompts/__init__.py`
- `src/rules_lawyer_bot/agent/prompts/examples.py`
- `src/rules_lawyer_bot/agent/repository.py`
- `tests/test_agent_factory.py`
- `tests/test_prompts_examples.py`
- `tests/test_repository.py`

---

## Task 1: Lazy agent singleton

**Files:**
- Modify: `src/rules_lawyer_bot/agent/definition.py`
- Modify: `src/rules_lawyer_bot/handlers/messages.py`
- Create: `tests/test_agent_factory.py`

### Step 1: Написать падающий тест

Создать `tests/test_agent_factory.py`:

```python
"""Tests for the lazy agent factory."""
from unittest.mock import patch

import pytest


def test_get_rules_agent_returns_agent():
    """get_rules_agent() returns an Agent instance."""
    from src.rules_lawyer_bot.agent.definition import get_rules_agent

    agent = get_rules_agent()
    assert agent is not None
    assert hasattr(agent, "instructions")


def test_get_rules_agent_caches_instance():
    """Successive calls return the same cached instance."""
    from src.rules_lawyer_bot.agent.definition import (
        _reset_agent_cache_for_tests,
        get_rules_agent,
    )

    _reset_agent_cache_for_tests()

    a1 = get_rules_agent()
    a2 = get_rules_agent()
    assert a1 is a2


def test_reset_clears_cache():
    """_reset_agent_cache_for_tests forces a fresh build on next call."""
    from src.rules_lawyer_bot.agent.definition import (
        _reset_agent_cache_for_tests,
        get_rules_agent,
    )

    a1 = get_rules_agent()
    _reset_agent_cache_for_tests()
    a2 = get_rules_agent()

    assert a1 is not a2


def test_create_agent_not_called_at_import():
    """Importing agent.definition does NOT call create_agent at module load.

    This is the core invariant: the agent must be lazy.
    """
    # Patch create_agent BEFORE re-import to spy on calls
    import importlib

    import src.rules_lawyer_bot.agent.definition as defn

    with patch.object(defn, "create_agent") as mock_create:
        importlib.reload(defn)
        # Even after reload, create_agent should NOT have been called.
        mock_create.assert_not_called()
```

### Step 2: Запустить — должны упасть

Run: `uv run pytest tests/test_agent_factory.py -v`
Expected: FAIL. `get_rules_agent` и `_reset_agent_cache_for_tests` не существуют.

### Step 3: Реализовать lazy factory в definition.py

В `src/rules_lawyer_bot/agent/definition.py`:

**3a.** В начало файла добавить импорт `functools.lru_cache` (если ещё нет). Найти строку `from pathlib import Path` и добавить рядом:

```python
from functools import lru_cache
```

**3b.** В конце файла (около строки 214) найти и **удалить**:

```python
# Global agent instance
rules_agent = create_agent()
```

**3c.** Вместо удалённого блока добавить:

```python
@lru_cache(maxsize=1)
def get_rules_agent() -> Agent:
    """Return the cached agent instance, creating it on first call.

    This is the public access point. Replaces the previous import-time
    `rules_agent = create_agent()` singleton, which made tests difficult
    and forced agent construction on any module import.
    """
    return create_agent()


def _reset_agent_cache_for_tests() -> None:
    """Reset the cached agent instance. Use ONLY in tests."""
    get_rules_agent.cache_clear()
```

### Step 4: Обновить `handlers/messages.py`

В `src/rules_lawyer_bot/handlers/messages.py`:

Заменить (около строки 23):

```python
from src.rules_lawyer_bot.agent.definition import get_user_session, rules_agent
```

на:

```python
from src.rules_lawyer_bot.agent.definition import get_rules_agent, get_user_session
```

Заменить использование (около строки 212):

```python
                    result = await _run_agent_with_retry(
                        agent=rules_agent,
                        agent_input=agent_input,
                        session=session,
                    )
```

на:

```python
                    result = await _run_agent_with_retry(
                        agent=get_rules_agent(),
                        agent_input=agent_input,
                        session=session,
                    )
```

### Step 5: Запустить тесты — должны пройти

Run: `uv run pytest tests/test_agent_factory.py tests/ -v`
Expected: все 4 новых теста PASS + 54 существующих PASS. Total: 58.

### Step 6: Commit

```bash
git add src/rules_lawyer_bot/agent/definition.py src/rules_lawyer_bot/handlers/messages.py tests/test_agent_factory.py
git commit -m "refactor(agent): lazy agent singleton via lru_cache factory"
```

---

## Task 2: Few-shot examples module

**Files:**
- Create: `src/rules_lawyer_bot/agent/prompts/__init__.py`
- Create: `src/rules_lawyer_bot/agent/prompts/examples.py`
- Modify: `src/rules_lawyer_bot/agent/definition.py` (add `with_examples` param)
- Modify: `src/rules_lawyer_bot/config.py` (add `enable_few_shot_examples`)
- Create: `tests/test_prompts_examples.py`

### Step 1: Создать `__init__.py`

Создать `src/rules_lawyer_bot/agent/prompts/__init__.py`:

```python
"""Optional prompt assets (few-shot examples, alternative instructions)."""
```

### Step 2: Написать падающие тесты

Создать `tests/test_prompts_examples.py`:

```python
"""Tests for optional few-shot examples module."""
import pytest


def test_examples_dict_has_expected_keys():
    """EXAMPLES contains the four canonical examples."""
    from src.rules_lawyer_bot.agent.prompts.examples import EXAMPLES

    assert "discovery" in EXAMPLES
    assert "found_answer" in EXAMPLES
    assert "multi_game_select" in EXAMPLES
    assert "react_cycle" in EXAMPLES
    for key, val in EXAMPLES.items():
        assert isinstance(val, str), f"{key}: examples must be strings"
        assert len(val) > 0, f"{key}: example must be non-empty"


def test_render_examples_returns_markdown_section():
    """render_examples returns a markdown-formatted block."""
    from src.rules_lawyer_bot.agent.prompts.examples import render_examples

    rendered = render_examples()
    assert "## EXAMPLES" in rendered
    assert "```json" in rendered
    assert "### discovery" in rendered
    assert "### found_answer" in rendered


def test_render_examples_filters_by_keys():
    """render_examples(keys=[...]) only includes selected examples."""
    from src.rules_lawyer_bot.agent.prompts.examples import render_examples

    rendered = render_examples(keys=["discovery"])
    assert "### discovery" in rendered
    assert "### found_answer" not in rendered


def test_create_agent_with_examples_flag():
    """create_agent(with_examples=True) appends EXAMPLES to instructions."""
    from src.rules_lawyer_bot.agent.definition import create_agent

    agent_plain = create_agent()
    agent_with = create_agent(with_examples=True)

    assert len(agent_with.instructions) > len(agent_plain.instructions)
    assert "## EXAMPLES" in agent_with.instructions


def test_create_agent_default_no_examples():
    """create_agent() without with_examples does NOT include examples."""
    from src.rules_lawyer_bot.agent.definition import create_agent

    agent = create_agent()
    assert "## EXAMPLES" not in agent.instructions
```

### Step 3: Запустить — должны упасть

Run: `uv run pytest tests/test_prompts_examples.py -v`
Expected: FAIL — module не существует.

### Step 4: Создать `examples.py`

Создать `src/rules_lawyer_bot/agent/prompts/examples.py`:

```python
"""Optional few-shot examples for the system prompt.

These are NOT injected by default. If the LLM starts producing malformed
outputs in production, enable them via settings.enable_few_shot_examples
(see definition.create_agent).
"""

EXAMPLES: dict[str, str] = {
    "discovery": """{
  "action_type": "final_answer",
  "final_answer": {
    "answer": "🎮 In my library: 1. Dead Cells 2. Gloomhaven 3. Wingspan. Ask me anything about these games!",
    "confidence": 1.0
  },
  "stage_reasoning": "User asked for game list. Called list_directory_tree(), formatted as numbered list."
}""",
    "found_answer": """{
  "action_type": "final_answer",
  "game_identification": {
    "identified_game": "Super Fantasy Brawl",
    "pdf_file": "Super Fantasy Brawl.pdf"
  },
  "final_answer": {
    "answer": "📖 \\"Attack: spend 2 AP, choose a target in range, declare attack.\\"\\n📍 Section: Combat, Page 12\\n💡 In short: Attacking costs 2 Action Points and requires a target in range.",
    "confidence": 0.9
  },
  "stage_reasoning": "Found complete attack rules on page 12 via ugrep search."
}""",
    "multi_game_select": """{
  "action_type": "game_selection",
  "game_identification": {
    "candidates": [
      {"english_name": "Gloomhaven", "pdf_filename": "Gloomhaven.pdf", "confidence": 0.9},
      {"english_name": "Gloomhaven: Jaws of the Lion", "pdf_filename": "Gloomhaven JOTL.pdf", "confidence": 0.85}
    ]
  },
  "clarification": {
    "question": "Which Gloomhaven game?",
    "options": ["Gloomhaven", "Gloomhaven: Jaws of the Lion"],
    "context": "Multiple Gloomhaven variants in library"
  },
  "stage_reasoning": "User said 'gloomhaven' but multiple versions match."
}""",
    "react_cycle": """{
  "action_type": "final_answer",
  "final_answer": {
    "answer": "📖 \\"Brown powers activate when you play a bird.\\"\\n📍 Section: Brown Powers, Page 8",
    "confidence": 0.9
  },
  "stage_reasoning": "ACTION 1: search('коричнев|корич') → no_match (PDF is English). ACTION 2: search('brown power') → found on page 8. Adapted from Russian to English query."
}""",
}


def render_examples(keys: list[str] | None = None) -> str:
    """Render selected examples as a markdown section for prompt injection.

    Args:
        keys: List of example names to render. If None, renders all.

    Returns:
        Markdown-formatted string with EXAMPLES section header.
    """
    selected = EXAMPLES if keys is None else {k: EXAMPLES[k] for k in keys}
    lines = ["## EXAMPLES (reference, do not copy verbatim)", ""]
    for name, text in selected.items():
        lines.append(f"### {name}")
        lines.append("```json")
        lines.append(text)
        lines.append("```")
        lines.append("")
    return "\n".join(lines)
```

### Step 5: Добавить `with_examples` параметр в `create_agent`

В `src/rules_lawyer_bot/agent/definition.py`, найти сигнатуру `def create_agent()` (около строки 28) и заменить на:

```python
def create_agent(with_examples: bool = False) -> Agent:
    """Create the board game referee agent with tools.

    Args:
        with_examples: If True, append few-shot examples to instructions.
            Default False (see prompts/examples.py).

    Returns:
        Configured Agent instance
    """
```

Затем в конце `instructions = """...""".strip()` (перед `agent = Agent(...)`) добавить:

```python
    if with_examples:
        from src.rules_lawyer_bot.agent.prompts.examples import render_examples
        instructions = instructions + "\n\n" + render_examples()
```

Обновить `get_rules_agent`, чтобы пробрасывать config-флаг. Заменить (созданное в Task 1):

```python
@lru_cache(maxsize=1)
def get_rules_agent() -> Agent:
    """..."""
    return create_agent()
```

на:

```python
@lru_cache(maxsize=1)
def get_rules_agent() -> Agent:
    """Return the cached agent instance, creating it on first call."""
    from src.rules_lawyer_bot.config import settings
    return create_agent(with_examples=settings.enable_few_shot_examples)
```

### Step 6: Добавить config flag

В `src/rules_lawyer_bot/config.py`, в классе `Settings`, после `bgg_api_token` добавить:

```python
    # Few-shot examples (optional prompt feature)
    enable_few_shot_examples: bool = Field(
        default=False,
        description="If True, inject few-shot examples into the system prompt"
    )
```

### Step 7: Запустить тесты — должны пройти

Run: `uv run pytest tests/test_prompts_examples.py tests/test_prompt.py -v`
Expected: все 5 новых + 6 prompt-тестов PASS. Заметка: `test_prompt_size_under_budget` НЕ должен сломаться, потому что default `create_agent()` (без `with_examples=True`) не инклудит примеры.

Run: `uv run pytest tests/ -v`
Expected: всё PASS, total ≈ 63.

### Step 8: Commit

```bash
git add src/rules_lawyer_bot/agent/prompts/ src/rules_lawyer_bot/agent/definition.py src/rules_lawyer_bot/config.py tests/test_prompts_examples.py
git commit -m "feat(agent): optional few-shot examples module (opt-in via config)"
```

---

## Task 3: Fuzzy matching in `find_game_by_name`

**Files:**
- Modify: `pyproject.toml` (add rapidfuzz dep)
- Modify: `src/rules_lawyer_bot/agent/tools.py` (`find_game_by_name`)
- Modify: `tests/test_tools.py` (add new tests, possibly remove old substring-based tests if any)

### Step 1: Добавить rapidfuzz

Run: `uv add 'rapidfuzz>=3.0.0'`
Expected: rapidfuzz появляется в `dependencies`, `uv.lock` обновляется.

### Step 2: Verify import

Run: `uv run python -c "from rapidfuzz import fuzz; print(fuzz.token_set_ratio('hello world', 'world hello'))"`
Expected: `100`.

### Step 3: Написать падающие тесты

Добавить в `tests/test_tools.py` (в конец файла) следующий блок:

```python
# ===== Fuzzy matching tests for find_game_by_name =====

@pytest.fixture
def games_index_fixture(mock_settings):
    """Create a games_index.json with 3 games."""
    import json as _json
    pdf_dir = Path(mock_settings.pdf_storage_path)
    index_path = pdf_dir / "games_index.json"
    index_path.write_text(
        _json.dumps({
            "games": [
                {
                    "english_name": "Dead Cells",
                    "russian_names": ["Мёртвые клетки"],
                    "pdf_files": ["Dead Cells.pdf"],
                    "tags": ["roguelike"],
                },
                {
                    "english_name": "Wingspan",
                    "russian_names": ["Крылья"],
                    "pdf_files": ["Wingspan.pdf"],
                    "tags": ["engine-building"],
                },
                {
                    "english_name": "Gloomhaven",
                    "russian_names": ["Глумхейвен"],
                    "pdf_files": ["Gloomhaven.pdf"],
                    "tags": ["dungeon-crawl"],
                },
            ]
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    return index_path


@pytest.mark.asyncio
async def test_find_game_exact_english(games_index_fixture):
    """Exact English name match returns high confidence."""
    import json as _json
    from src.rules_lawyer_bot.agent.tools import find_game_by_name

    raw = await find_game_by_name.on_invoke_tool(
        None, _json.dumps({"query": "Dead Cells"})
    )
    result = _json.loads(raw)
    assert result["found"] is True
    game = result.get("game") or result["games"][0]
    assert game["english_name"] == "Dead Cells"
    assert game.get("confidence", 0) >= 0.9


@pytest.mark.asyncio
async def test_find_game_typo(games_index_fixture):
    """Single-letter typo still matches above threshold."""
    import json as _json
    from src.rules_lawyer_bot.agent.tools import find_game_by_name

    raw = await find_game_by_name.on_invoke_tool(
        None, _json.dumps({"query": "Dead Cels"})  # missing one 'l'
    )
    result = _json.loads(raw)
    assert result["found"] is True


@pytest.mark.asyncio
async def test_find_game_russian(games_index_fixture):
    """Russian name matches the russian_names entry."""
    import json as _json
    from src.rules_lawyer_bot.agent.tools import find_game_by_name

    raw = await find_game_by_name.on_invoke_tool(
        None, _json.dumps({"query": "Мёртвые клетки"})
    )
    result = _json.loads(raw)
    assert result["found"] is True
    game = result.get("game") or result["games"][0]
    assert game["english_name"] == "Dead Cells"


@pytest.mark.asyncio
async def test_find_game_no_false_positive(games_index_fixture):
    """An unrelated query returns found=False, no false matches."""
    import json as _json
    from src.rules_lawyer_bot.agent.tools import find_game_by_name

    raw = await find_game_by_name.on_invoke_tool(
        None, _json.dumps({"query": "Monopoly"})
    )
    result = _json.loads(raw)
    assert result["found"] is False


@pytest.mark.asyncio
async def test_find_game_results_sorted_by_confidence(games_index_fixture):
    """When multiple match, results are sorted by confidence DESC."""
    import json as _json
    from src.rules_lawyer_bot.agent.tools import find_game_by_name

    raw = await find_game_by_name.on_invoke_tool(
        None, _json.dumps({"query": "haven"})  # might match Gloomhaven only
    )
    result = _json.loads(raw)
    if result["found"] and "games" in result:
        confidences = [g["confidence"] for g in result["games"]]
        assert confidences == sorted(confidences, reverse=True)
```

### Step 4: Запустить — старые тесты могут пройти, новые упадут

Run: `uv run pytest tests/test_tools.py -v`
Expected: новые тесты падают (нет поля `confidence` в выдаче, или не нашли typo).

### Step 5: Реализовать fuzzy matching

В `src/rules_lawyer_bot/agent/tools.py`, в начало файла добавить импорт rapidfuzz:

```python
from rapidfuzz import fuzz
```

Найти функцию `find_game_by_name` (около строк 73-115) и заменить её **тело** (но не декораторы и сигнатуру) на:

```python
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

        query_stripped = query.strip()
        threshold = 65

        scored: list[tuple[dict, int]] = []
        for game in index_data.get("games", []):
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
```

### Step 6: Запустить — должны пройти

Run: `uv run pytest tests/test_tools.py -v`
Expected: все новые fuzzy-тесты PASS. Старые тесты (если использовали substring и попадали по случайному совпадению) могут начать вести себя иначе — если падают, проверить, что новое поведение корректно.

Run: `uv run pytest tests/ -v`
Expected: все тесты PASS.

### Step 7: Commit

```bash
git add pyproject.toml uv.lock src/rules_lawyer_bot/agent/tools.py tests/test_tools.py
git commit -m "feat(agent): fuzzy game name matching via rapidfuzz with confidence scores"
```

---

## Task 4: RulesRepository (ограниченный scope)

**Files:**
- Create: `src/rules_lawyer_bot/agent/repository.py`
- Modify: `src/rules_lawyer_bot/agent/tools.py` (wire-up через `_get_default_repo()`)
- Create: `tests/test_repository.py`

### Step 1: Написать падающие тесты

Создать `tests/test_repository.py`:

```python
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
    # If this type check passes, the Protocol is satisfied
    assert repo is not None
```

### Step 2: Запустить — должны упасть на импорте

Run: `uv run pytest tests/test_repository.py -v`
Expected: FAIL — модуль repository не существует.

### Step 3: Создать `repository.py`

Создать `src/rules_lawyer_bot/agent/repository.py`:

```python
"""Abstraction layer for game metadata and PDF file access.

Provides a Protocol (RulesRepository) with two implementations:
- FileSystemRulesRepository: reads from settings.pdf_storage_path.
- InMemoryRulesRepository: for tests, no filesystem dependency.

Scope is limited to operations that don't involve subprocess (pdftotext,
ugrep) — those remain in tools.py because the cost of abstracting them
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
```

### Step 4: Запустить — все тесты репозитория должны пройти

Run: `uv run pytest tests/test_repository.py -v`
Expected: все 8 тестов PASS.

### Step 5: Wire-up репозитория в `tools.py`

В `src/rules_lawyer_bot/agent/tools.py` добавить ленивый аксессор и переиспользовать его. После импортов добавить:

```python
from src.rules_lawyer_bot.agent.repository import get_default_repository, RulesRepository


def _repo() -> RulesRepository:
    """Return the default repository. Indirection allows test injection."""
    return get_default_repository()
```

Заменить `_safe_pdf_path` (старая функция):

```python
def _safe_pdf_path(filename: str) -> Path:
    """Validate filename and resolve to absolute path inside pdf_storage_path.

    Delegates to the default repository's get_pdf_path.
    """
    return _repo().get_pdf_path(filename)
```

В `find_game_by_name` заменить блок чтения индекса и substring-scoring (от `index_path = Path(...)` до `return json.dumps(...)`) — НЕ заменяем fuzzy логику из Task 3. Только источник данных. Найти строки:

```python
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

        query_stripped = query.strip()
        threshold = 65

        scored: list[tuple[dict, int]] = []
        for game in index_data.get("games", []):
            names = [game["english_name"]] + game.get("russian_names", [])
            best = max(
                (fuzz.token_set_ratio(query_stripped, name) for name in names),
                default=0,
            )
            if best >= threshold:
                scored.append((game, best))
```

Заменить на (НЕ меняем оставшуюся часть функции — sort + dispatch):

```python
        repo = _repo()
        candidates = repo.find_game_by_query(query)

        # If repository returned a candidate list, re-score with rapidfuzz
        # for confidence and dedup. If empty, fall back to scanning all games
        # via the raw index (some queries may not substring-match but still
        # fuzzy-match — e.g. typos).
        all_games: list[dict]
        if candidates:
            all_games = candidates
        else:
            # Fallback: load the full index from the filesystem to handle
            # typos that don't substring-match. The repository's index path
            # is hidden behind the abstraction, so we go back to the raw
            # index here. This is the only place that still touches the
            # index file directly; acceptable for the limited-scope
            # repository.
            index_path = Path(settings.pdf_storage_path) / "games_index.json"
            if not index_path.exists():
                logger.warning(f"Games index not found at {index_path}")
                return json.dumps({
                    "found": False,
                    "error": "Games index not configured.",
                    "suggestion": "Create games_index.json in rules_pdfs/"
                }, ensure_ascii=False)
            try:
                with open(index_path, encoding="utf-8") as f:
                    all_games = json.loads(f.read()).get("games", [])
            except Exception as e:
                logger.error(f"Failed to load games index: {e}")
                return json.dumps({
                    "found": False,
                    "error": f"Failed to load games index: {str(e)}"
                }, ensure_ascii=False)

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
```

(Остаток `find_game_by_name` — `scored.sort(...)`, `if not scored:`, итд — оставляем без изменений.)

В `list_directory_tree` и `search_filenames` — заменить прямой `Path(settings.pdf_storage_path).glob("*.pdf")` на `_repo().list_pdf_files()`. Найти в `search_filenames` (около строк 165-185):

```python
        pdf_dir = Path(settings.pdf_storage_path)
        if not pdf_dir.exists():
            return f"Error: PDF directory not found at {pdf_dir}"

        # Case-insensitive search
        query_lower = query.lower()
        matches = [
            f.name for f in pdf_dir.glob("*.pdf") if query_lower in f.name.lower()
        ]
```

Заменить на:

```python
        pdfs = _repo().list_pdf_files()

        # Case-insensitive search
        query_lower = query.lower()
        matches = [
            p.name for p in pdfs if query_lower in p.name.lower()
        ]
```

В `list_directory_tree`, найти блок (около строк 416-420):

```python
        # Smart formatting for game discovery at root level
        if path == "" and target_path == base_path:
            pdf_files = sorted([f.stem for f in target_path.glob("*.pdf")])
```

Заменить только `target_path.glob("*.pdf")` (один вызов) на `_repo().list_pdf_files()`. Получится:

```python
        # Smart formatting for game discovery at root level
        if path == "" and target_path == base_path:
            pdf_files = sorted([p.stem for p in _repo().list_pdf_files()])
```

### Step 6: Запустить полный набор тестов

Run: `uv run pytest tests/ -v`
Expected: всё PASS, ~71 тест.

### Step 7: Commit

```bash
git add src/rules_lawyer_bot/agent/repository.py src/rules_lawyer_bot/agent/tools.py tests/test_repository.py
git commit -m "feat(agent): RulesRepository abstraction for game index and PDF path access"
```

---

## Финальная проверка Фазы 4

- [ ] **Step 1: Полный прогон**

Run: `uv run pytest tests/ -v`
Expected: всё зелёное. ~72 теста (54 + 4 factory + 5 examples + 5 fuzzy + 8 repository ≈ 76 — точное число зависит от того, потерялись ли какие-то старые тесты).

- [ ] **Step 2: Git log**

Run: `git log --oneline -6`
Expected: 4 коммита Фазы 4 (factory, examples, fuzzy, repository).

- [ ] **Step 3: Smoke**

Run:
```
uv run python -c "from src.rules_lawyer_bot.agent.definition import get_rules_agent; a = get_rules_agent(); print(f'{a.instructions.count(chr(10))+1} lines, examples included: {\"## EXAMPLES\" in a.instructions}')"
```
Expected: `~115 lines, examples included: False`.

---

## Замечания для исполнителя

### Порядок задач

Tasks 1 → 2 → 3 → 4. Каждая зависит от предыдущих ТОЛЬКО косвенно (стабильные коммиты на main). Если хочется параллелить — нельзя, все они трогают одни и те же файлы.

### Зачем в `find_game_by_name` остался прямой доступ к индексу (Task 4 Step 5)

Repository.find_game_by_query делает substring-match. Fuzzy-логика (Task 3) живёт на уровне тула. Если substring ничего не вернул, fuzzy всё ещё может найти typo-вариант. Поэтому в fallback'е загружаем полный индекс и прогоняем fuzz через все игры.

Альтернатива — дать репозиторию метод `get_all_games() -> list[dict]`, и тогда тул делает fuzz по списку. Это чище. Если у исполнителя есть время, можно сделать так — но в плане я оставил минимальный вариант, чтобы не разрастаться.

### Тестирование `_reset_agent_cache_for_tests`

`functools.lru_cache.cache_clear()` — это валидный API, безопасен между тестами. Если нужно, в `conftest.py` можно добавить autouse-fixture:

```python
@pytest.fixture(autouse=True)
def _reset_agent_cache():
    try:
        from src.rules_lawyer_bot.agent.definition import _reset_agent_cache_for_tests
        _reset_agent_cache_for_tests()
    except ImportError:
        pass
```

Но для этих тестов хватит ручного вызова в самих тестах (Task 1, тест `test_reset_clears_cache`).

### Что не делается

- Не двигаем subprocess/ugrep/pdftotext в репозиторий. Это отдельная следующая итерация если понадобится.
- Не пытаемся встроить few-shot examples в реальный workflow (только инфраструктура).
- Не переписываем существующие test_tools.py тесты под `InMemoryRulesRepository` — оставляем существующие тесты на FileSystem repo. Новый тест в test_repository.py демонстрирует InMemory паттерн для будущих тестов.
