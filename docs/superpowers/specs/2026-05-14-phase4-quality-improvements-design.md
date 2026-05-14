# Дизайн: Фаза 4 — Quality Improvements

**Дата:** 2026-05-14
**Статус:** Утверждён
**Скоуп:** `src/rules_lawyer_bot/agent/`, `src/rules_lawyer_bot/handlers/messages.py`, `tests/`

## Контекст

После выполнения Фаз 1–3 (security, schema validation, page-aware search + prompt v2) остались nice-to-have пункты из отчёта `ai-engineer`:

1. **Singleton агента** — `rules_agent = create_agent()` на import-time мешает тестируемости.
2. **Few-shot примеры в отдельном файле** — после shrink'а Фазы 3 их в промпте нет; инфраструктура для будущего опционального использования.
3. **Fuzzy matching в `find_game_by_name`** — substring match даёт ложные срабатывания, нет confidence.
4. **`RulesRepository` слой** — для тестируемости и подмены источника PDF.

Каждый пункт — независимый, можно сделать атомарным коммитом. Объединяем в одну фазу.

## §1. Lazy agent singleton

**Проблема:** в `src/rules_lawyer_bot/agent/definition.py:214` есть `rules_agent = create_agent()` — выполняется на import. Это:
- Делает невозможным горячее переконфигурирование агента в тестах.
- Блокирует тесты, которые хотят подменить `create_agent()`.
- Заставляет тратить ресурсы на создание агента при любом импорте модуля.

**Решение.** Заменить на ленивую фабрику:

```python
from functools import lru_cache

@lru_cache(maxsize=1)
def get_rules_agent() -> Agent:
    """Return the cached agent instance, creating it on first call."""
    return create_agent()


def _reset_agent_cache_for_tests() -> None:
    """Reset cached agent instance. Use only in tests."""
    get_rules_agent.cache_clear()
```

Удалить `rules_agent = create_agent()`. В `src/rules_lawyer_bot/handlers/messages.py` заменить `from ... import rules_agent` на `from ... import get_rules_agent`, использовать `get_rules_agent()` вместо `rules_agent`.

Тесты добавляют autouse-fixture, дёргающий `_reset_agent_cache_for_tests()` перед каждым тестом, чтобы конфигурация была свежей.

## §2. Few-shot examples module

**Проблема:** в Фазе 3 промпт сжат до 115 строк, длинные JSON-примеры удалены. Если в проде LLM начнёт ошибаться в форматах, у нас нет готовой инфраструктуры для опциональной инъекции примеров.

**Решение.** Создать `src/rules_lawyer_bot/agent/prompts/__init__.py` и `src/rules_lawyer_bot/agent/prompts/examples.py`:

```python
# examples.py
"""Optional few-shot examples for the system prompt.

These are NOT injected by default. If the LLM starts producing malformed
outputs in production, enable them via settings.enable_few_shot_examples
(see definition.create_agent).
"""

EXAMPLES: dict[str, str] = {
    "discovery": "...",        # "what games do you have?" → final_answer with list
    "found_answer": "...",     # specific rules question → final_answer with quote
    "multi_game_select": "..." # ambiguous game name → game_selection
    "react_cycle": "...",      # adaptive search example
}


def render_examples(keys: list[str] | None = None) -> str:
    """Render selected examples as a markdown section for prompt injection."""
    selected = EXAMPLES if keys is None else {k: EXAMPLES[k] for k in keys}
    lines = ["## EXAMPLES (reference, do not copy verbatim)\n"]
    for name, text in selected.items():
        lines.append(f"### {name}\n```json\n{text}\n```\n")
    return "\n".join(lines)
```

В `definition.py`: добавить опциональный аргумент `with_examples: bool = False` в `create_agent()`. Когда `True`, аппендим `render_examples()` к instructions. По умолчанию выключено.

Добавить в `config.py` поле `enable_few_shot_examples: bool = False`. Использовать его при дефолтном создании агента.

Тесты: examples module импортируется, `render_examples` производит ожидаемую структуру, `create_agent(with_examples=True)` склеивает промпт длиннее.

## §3. Fuzzy matching в `find_game_by_name`

**Проблема:** текущая реализация в `tools.py:96-114` использует `query in name.lower()` — substring. Запрос "cells" возвращает ВСЕ игры со словом "cells", запрос "клетки" не находит "Мёртвые клетки" из-за падежей.

**Решение.** Использовать `rapidfuzz.fuzz.token_set_ratio` (учитывает разный порядок слов и подмножества):

```python
from rapidfuzz import fuzz, process

def _score_game(query: str, game: dict) -> int:
    """Return the best fuzzy match score across all names of a game."""
    names = [game["english_name"]] + game.get("russian_names", [])
    scores = [fuzz.token_set_ratio(query, name) for name in names]
    return max(scores) if scores else 0


# In find_game_by_name:
THRESHOLD = 65
scored = [(g, _score_game(query, g)) for g in games]
matches = [(g, s) for g, s in scored if s >= THRESHOLD]
matches.sort(key=lambda x: x[1], reverse=True)
```

Возвращаемый JSON получает поле `confidence` (`score / 100`) на каждом матче. Промпт уже умеет работать с confidence (используется в `PipelineOutput.final_answer.confidence`).

**Зависимость:** добавить `rapidfuzz>=3.0.0` в `pyproject.toml`.

**Тесты:**
- Точное совпадение → confidence ≈ 1.0
- Опечатка (1 буква) → confidence ≥ 0.85
- Частичное совпадение слова → confidence ≥ 0.70
- Похожее, но другое слово → не возвращается (`<65`)
- Старый ложно-положительный кейс "cells" → проверить, что НЕ возвращает Wingspan по слову "cells" (если такого варианта названия нет)
- Сортировка по убыванию score

## §4. `RulesRepository` слой (ограниченный scope)

**Проблема:** `tools.py` напрямую читает файлы, индекс игр, директории. Тестам приходится моделировать всю файловую систему через `tmp_path` + `mock_settings`. Сложно подменять источник PDF (например, на S3 в будущем).

**Решение.** Создать `src/rules_lawyer_bot/agent/repository.py` с Protocol и реализациями. **Ограничиваем scope:** абстрагируем ТОЛЬКО легко-абстрагируемые операции. Subprocess-логика (`pdftotext`, `ugrep`) остаётся в `tools.py` — её абстракция стоит больше, чем даёт.

```python
# repository.py
from pathlib import Path
from typing import Protocol


class RulesRepository(Protocol):
    """Abstract source of game metadata and PDF files."""

    def find_game_by_query(self, query: str) -> list[dict]:
        """Return matching games from the index. Pure data access."""
        ...

    def list_pdf_files(self) -> list[Path]:
        """Return all PDF paths in the library."""
        ...

    def get_pdf_path(self, filename: str) -> Path:
        """Resolve a PDF filename to a validated absolute Path.

        Raises ValueError on path traversal attempts.
        """
        ...


class FileSystemRulesRepository:
    """Default repository: reads from settings.pdf_storage_path."""

    def __init__(self, base_path: Path):
        self.base_path = Path(base_path).resolve()

    def find_game_by_query(self, query: str) -> list[dict]:
        # Reads games_index.json, applies fuzzy match (delegates to §3 logic)
        ...

    def list_pdf_files(self) -> list[Path]:
        return sorted(self.base_path.glob("*.pdf"))

    def get_pdf_path(self, filename: str) -> Path:
        # Replaces _safe_pdf_path - same logic, now on the repository
        ...


def get_default_repository() -> RulesRepository:
    """Build the default repository from settings."""
    from src.rules_lawyer_bot.config import settings
    return FileSystemRulesRepository(Path(settings.pdf_storage_path))
```

В `tools.py`:
- `_safe_pdf_path(filename)` становится `_get_default_repo().get_pdf_path(filename)` или просто использует `_get_default_repo()` напрямую.
- `find_game_by_name(query)` → `_get_default_repo().find_game_by_query(query)` + JSON-форматирование.
- `list_directory_tree()` → `_get_default_repo().list_pdf_files()` + tree-форматирование.
- `search_filenames(query)` → `_get_default_repo().list_pdf_files()` + фильтр.
- `_search_inside_file_ugrep_impl`, `read_full_document`, `parallel_search_terms` — продолжают использовать `_safe_pdf_path` через repository, но subprocess-логика остаётся локальной.

В тестах создаём `InMemoryRulesRepository`:

```python
# tests/test_repository.py
class InMemoryRulesRepository:
    def __init__(self, games: list[dict] = None, pdfs: dict[str, bytes] = None):
        self._games = games or []
        self._pdfs = pdfs or {}

    def find_game_by_query(self, query: str) -> list[dict]:
        # simple substring match for tests
        ...

    def list_pdf_files(self) -> list[Path]:
        return [Path(name) for name in self._pdfs]

    def get_pdf_path(self, filename: str) -> Path:
        ...
```

**Не делаем:** не пытаемся абстрагировать поиск/чтение PDF — там subprocess, кэш, page-detection. Эта часть остаётся integration-testable через реальные `tmp_path` + fixture `sample_pdf`.

**Тесты:**
- Репозиторий: find_game_by_query, list_pdf_files, get_pdf_path.
- Path traversal: `get_pdf_path("../etc/passwd")` → ValueError.
- Интеграция: один тест в `test_tools.py`, который инъектирует `InMemoryRulesRepository` в `find_game_by_name` (если архитектура позволяет) или показывает паттерн.

## Файлы

| Файл | §1 | §2 | §3 | §4 |
|---|---|---|---|---|
| `agent/definition.py` | lazy factory | `with_examples` arg | — | — |
| `agent/prompts/__init__.py` | — | новый | — | — |
| `agent/prompts/examples.py` | — | новый | — | — |
| `agent/tools.py` | — | — | rapidfuzz | repo wiring |
| `agent/repository.py` | — | — | — | новый |
| `handlers/messages.py` | get_rules_agent | — | — | — |
| `config.py` | — | enable flag | — | — |
| `pyproject.toml` | — | — | rapidfuzz dep | — |
| `tests/test_agent_factory.py` | новый | — | — | — |
| `tests/test_prompts_examples.py` | — | новый | — | — |
| `tests/test_tools.py` | — | — | extend | — |
| `tests/test_repository.py` | — | — | — | новый |

## Зависимости

- `rapidfuzz>=3.0.0` — новая dep для fuzzy matching.

## Out of scope

- Полная абстракция subprocess (pdftotext, ugrep) — отдельная задача, если понадобится cloud-backed PDFs.
- Активация few-shot examples в проде — оставлено выключенным; включаем если smoke-test покажет деградацию форматов.
- Семантический кэш ответов (Redis) — отдельная задача.

## Риски

| Риск | Mitigation |
|---|---|
| Rapidfuzz threshold 65 слишком строгий → пропускаем валидные игры | Тесты на типичные запросы; настраивается константой в одном месте |
| Lazy singleton ломает существующий код, импортирующий `rules_agent` | Один импорт в messages.py, мигрируется механически |
| Repository wiring добавляет boilerplate без реальной пользы | Тест с `InMemoryRulesRepository` демонстрирует пользу; если не получится — оставляем `FileSystemRulesRepository` как простой класс без Protocol-абстракции |

## Критерии готовности

1. Все новые тесты проходят.
2. Все 54 существующих теста проходят.
3. Каждый из 4 пунктов — атомарный коммит.
4. Смоук: `uv run python -c "from src.rules_lawyer_bot.agent.definition import get_rules_agent; print(get_rules_agent().instructions[:100])"` работает.
