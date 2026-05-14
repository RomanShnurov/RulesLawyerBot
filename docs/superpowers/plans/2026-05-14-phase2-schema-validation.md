# Фаза 2: Schema Validation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Гарантировать валидные комбинации полей в `PipelineOutput` — LLM не сможет вернуть `FINAL_ANSWER` без `final_answer` и т.п. Невалидные комбинации перехватываются `@model_validator` и автоматически ретраятся через Phase 1 retry.

**Architecture:** Используем fallback-вариант из спеки (§2.2). Оставляем `PipelineOutput` плоским BaseModel с Optional-полями, добавляем `@model_validator(mode='after')` который проверяет соответствие `action_type` ↔ заполненные поля. SDK-уровень схема не меняется, prompt не меняется, handler.py / messages.py не трогаем. ValidationError от валидатора подхватывается ретраем Фазы 1.

**Tech Stack:** Pydantic 2.x `@model_validator`, pytest.

**Spec:** `docs/superpowers/specs/2026-05-14-agent-critical-fixes-design.md`, §2.

**Why this approach (not discriminated union):** Empirically verified that openai-agents SDK 0.6.1 crashes on `Annotated[Union[...], Field(discriminator=...)]` as `output_type` (`_type_to_str` doesn't handle `FieldInfo`). Wrapper pattern works but requires changing the LLM contract (extra `{"action": {...}}` nesting) and updating all prompt examples — exactly what Phase 3 wants to shrink. The spec explicitly allows this fallback (§2.2: "если SDK ругнётся через OpenRouter, fallback — оставить плоскую схему").

---

## Файловая структура

**Изменяемые файлы:**
- `src/rules_lawyer_bot/agent/schemas.py` — добавить `@model_validator(mode='after')` к `PipelineOutput`.

**Создаваемые файлы:**
- `tests/test_schemas.py` — тесты на валидацию комбинаций.

**НЕ трогаем:**
- `agent/definition.py` (system prompt не меняется)
- `pipeline/handler.py` (action_type matching работает как раньше)
- `handlers/messages.py` (isinstance проверка PipelineOutput не меняется)
- Существующие `test_integration.py` — должны проходить без изменений, т.к. валидные комбинации остаются валидными.

---

## Task 1: Добавить @model_validator на PipelineOutput

**Files:**
- Create: `tests/test_schemas.py`
- Modify: `src/rules_lawyer_bot/agent/schemas.py`

### Step 1: Написать падающие тесты

Создать `tests/test_schemas.py`:

```python
"""Tests for PipelineOutput schema validation.

Verifies that @model_validator rejects invalid combinations of
action_type and populated fields, so the LLM cannot return a
FINAL_ANSWER without final_answer, etc. Combined with Phase 1
retry, these ValidationErrors trigger automatic re-prompting.
"""
import pytest
from pydantic import ValidationError

from src.rules_lawyer_bot.agent.schemas import (
    ActionType,
    ClarificationRequest,
    FinalAnswer,
    GameCandidate,
    GameIdentification,
    PipelineOutput,
    SearchProgress,
)


# ===== CLARIFICATION_NEEDED =====


def test_clarification_needed_valid():
    """CLARIFICATION_NEEDED with clarification populated is valid."""
    output = PipelineOutput(
        action_type=ActionType.CLARIFICATION_NEEDED,
        clarification=ClarificationRequest(
            question="Какая игра?", options=[], context="no game"
        ),
        stage_reasoning="user did not specify a game",
    )
    assert output.action_type == ActionType.CLARIFICATION_NEEDED


def test_clarification_needed_without_clarification_rejected():
    """CLARIFICATION_NEEDED without clarification field is rejected."""
    with pytest.raises(ValidationError, match="clarification"):
        PipelineOutput(
            action_type=ActionType.CLARIFICATION_NEEDED,
            clarification=None,
            stage_reasoning="oops",
        )


# ===== GAME_SELECTION =====


def test_game_selection_valid():
    """GAME_SELECTION with clarification AND game_identification.candidates is valid."""
    output = PipelineOutput(
        action_type=ActionType.GAME_SELECTION,
        game_identification=GameIdentification(
            candidates=[
                GameCandidate(
                    english_name="Gloomhaven",
                    pdf_filename="Gloomhaven.pdf",
                    confidence=0.9,
                )
            ],
        ),
        clarification=ClarificationRequest(
            question="Which Gloomhaven?", options=["Gloomhaven", "JotL"], context="multi"
        ),
        stage_reasoning="multiple matches",
    )
    assert output.action_type == ActionType.GAME_SELECTION


def test_game_selection_without_clarification_rejected():
    """GAME_SELECTION without clarification is rejected."""
    with pytest.raises(ValidationError, match="clarification"):
        PipelineOutput(
            action_type=ActionType.GAME_SELECTION,
            game_identification=GameIdentification(
                candidates=[
                    GameCandidate(
                        english_name="X", pdf_filename="X.pdf", confidence=0.9
                    )
                ],
            ),
            clarification=None,
            stage_reasoning="oops",
        )


def test_game_selection_without_game_identification_rejected():
    """GAME_SELECTION without game_identification is rejected."""
    with pytest.raises(ValidationError, match="game_identification"):
        PipelineOutput(
            action_type=ActionType.GAME_SELECTION,
            game_identification=None,
            clarification=ClarificationRequest(
                question="?", options=[], context=""
            ),
            stage_reasoning="oops",
        )


def test_game_selection_empty_candidates_rejected():
    """GAME_SELECTION with empty candidates list is rejected."""
    with pytest.raises(ValidationError, match="candidates"):
        PipelineOutput(
            action_type=ActionType.GAME_SELECTION,
            game_identification=GameIdentification(candidates=[]),
            clarification=ClarificationRequest(
                question="?", options=[], context=""
            ),
            stage_reasoning="oops",
        )


# ===== SEARCH_IN_PROGRESS =====


def test_search_in_progress_valid():
    """SEARCH_IN_PROGRESS with search_progress is valid."""
    output = PipelineOutput(
        action_type=ActionType.SEARCH_IN_PROGRESS,
        search_progress=SearchProgress(
            game_name="X",
            pdf_file="X.pdf",
            search_terms=["attack"],
            found_relevant=False,
            needs_more_info=True,
            additional_question="Which character?",
        ),
        stage_reasoning="need more info",
    )
    assert output.action_type == ActionType.SEARCH_IN_PROGRESS


def test_search_in_progress_without_search_progress_rejected():
    """SEARCH_IN_PROGRESS without search_progress is rejected."""
    with pytest.raises(ValidationError, match="search_progress"):
        PipelineOutput(
            action_type=ActionType.SEARCH_IN_PROGRESS,
            search_progress=None,
            stage_reasoning="oops",
        )


# ===== FINAL_ANSWER =====


def test_final_answer_valid():
    """FINAL_ANSWER with final_answer is valid (game_identification optional)."""
    output = PipelineOutput(
        action_type=ActionType.FINAL_ANSWER,
        final_answer=FinalAnswer(answer="text", confidence=0.9),
        stage_reasoning="found it",
    )
    assert output.action_type == ActionType.FINAL_ANSWER


def test_final_answer_valid_with_game_identification():
    """FINAL_ANSWER may include game_identification."""
    output = PipelineOutput(
        action_type=ActionType.FINAL_ANSWER,
        game_identification=GameIdentification(
            identified_game="Gloomhaven", pdf_file="Gloomhaven.pdf"
        ),
        final_answer=FinalAnswer(answer="text", confidence=0.9),
        stage_reasoning="found it",
    )
    assert output.final_answer.answer == "text"


def test_final_answer_without_final_answer_rejected():
    """FINAL_ANSWER without final_answer field is rejected."""
    with pytest.raises(ValidationError, match="final_answer"):
        PipelineOutput(
            action_type=ActionType.FINAL_ANSWER,
            final_answer=None,
            stage_reasoning="oops",
        )
```

### Step 2: Run tests, observe failures

Run: `uv run pytest tests/test_schemas.py -v`
Expected: Most tests will FAIL because the current `PipelineOutput` accepts any combination — Optional fields with no validator. The valid-construction tests (`*_valid`) will PASS; the rejection tests will FAIL because no exception is raised.

### Step 3: Add @model_validator to PipelineOutput

In `src/rules_lawyer_bot/agent/schemas.py`:

Modify the imports at the top of the file:

```python
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator
```

Then, replace the existing `PipelineOutput` class (lines 115-154) with this version that adds the validator at the end:

```python
class PipelineOutput(BaseModel):
    """Unified output schema for multi-stage SGR pipeline.

    Uses action_type as discriminator to route bot responses.
    The @model_validator enforces that the populated fields match
    the action_type — LLM cannot return FINAL_ANSWER without
    final_answer, etc. ValidationError triggers automatic retry
    via the pipeline (see handlers/messages.py).
    """

    # Discriminator field - determines how bot handles the output
    action_type: ActionType = Field(
        description="Type of action: clarification_needed, game_selection, search_in_progress, or final_answer"
    )

    # Stage 1: Game identification result
    game_identification: Optional[GameIdentification] = Field(
        default=None,
        description="Game identification result (required for game_selection; optional for final_answer)",
    )

    # Clarification request (required when action_type is clarification_needed or game_selection)
    clarification: Optional[ClarificationRequest] = Field(
        default=None,
        description="Clarification request details (required when action_type is clarification_needed or game_selection)",
    )

    # Stage 3: Search progress (required when action_type is search_in_progress)
    search_progress: Optional[SearchProgress] = Field(
        default=None,
        description="Search progress info (required when action_type is search_in_progress)",
    )

    # Stage 4: Final answer (required when action_type is final_answer)
    final_answer: Optional[FinalAnswer] = Field(
        default=None,
        description="Complete formatted answer (required when action_type is final_answer)",
    )

    # Reasoning trace for debugging and logging
    stage_reasoning: str = Field(
        description="Explanation of current stage decision and next steps"
    )

    @model_validator(mode="after")
    def _enforce_action_type_invariants(self) -> "PipelineOutput":
        """Reject combinations where action_type does not match populated fields."""
        if self.action_type == ActionType.CLARIFICATION_NEEDED:
            if self.clarification is None:
                raise ValueError(
                    "action_type=clarification_needed requires 'clarification' field"
                )
        elif self.action_type == ActionType.GAME_SELECTION:
            if self.clarification is None:
                raise ValueError(
                    "action_type=game_selection requires 'clarification' field"
                )
            if self.game_identification is None:
                raise ValueError(
                    "action_type=game_selection requires 'game_identification' field"
                )
            if not self.game_identification.candidates:
                raise ValueError(
                    "action_type=game_selection requires non-empty 'game_identification.candidates'"
                )
        elif self.action_type == ActionType.SEARCH_IN_PROGRESS:
            if self.search_progress is None:
                raise ValueError(
                    "action_type=search_in_progress requires 'search_progress' field"
                )
        elif self.action_type == ActionType.FINAL_ANSWER:
            if self.final_answer is None:
                raise ValueError(
                    "action_type=final_answer requires 'final_answer' field"
                )
        return self
```

### Step 4: Run schema tests, verify all pass

Run: `uv run pytest tests/test_schemas.py -v`
Expected: All 10 tests PASS.

### Step 5: Run full test suite

Run: `uv run pytest tests/ -v`
Expected: All tests PASS, including existing `test_integration.py` (which constructs valid combinations).

If any existing test breaks, look carefully — it likely means that test was constructing an invalid combination that the validator now catches. Fix the test to use a valid combination, or report it as a real find.

### Step 6: Commit

```bash
git add src/rules_lawyer_bot/agent/schemas.py tests/test_schemas.py
git commit -m "feat(agent): enforce PipelineOutput action_type invariants via model_validator"
```

---

## Task 2: Smoke test that retry catches schema violations

This task verifies the end-to-end interaction: the validator's `ValueError` becomes a `ValidationError` at the SDK boundary, which Phase 1's retry catches.

**Files:**
- Modify: `tests/test_pipeline_resilience.py` (append)

### Step 1: Write the test

Append to `tests/test_pipeline_resilience.py`:

```python
@pytest.mark.asyncio
async def test_schema_violation_triggers_retry():
    """A PipelineOutput schema violation surfaces as ValidationError
    and is retried by _run_agent_with_retry.

    This proves end-to-end that the model_validator in Phase 2 plays
    correctly with the retry from Phase 1.
    """
    from pydantic import ValidationError as _VE

    from src.rules_lawyer_bot.agent.schemas import ActionType, PipelineOutput

    # Compute the actual ValidationError that PipelineOutput raises
    # when action_type=FINAL_ANSWER but final_answer is missing.
    try:
        PipelineOutput(
            action_type=ActionType.FINAL_ANSWER,
            final_answer=None,
            stage_reasoning="invalid",
        )
        raise AssertionError("Should have raised ValidationError")
    except _VE as schema_error:
        pass

    call_count = {"n": 0}

    def _make_stream_result():
        call_count["n"] += 1

        async def _stream():
            if call_count["n"] < 3:
                raise schema_error
            return
            yield  # makes this an async generator

        result = MagicMock()
        result.stream_events = _stream
        result.new_items = []
        result.final_output = "ok"
        return result

    with patch("src.rules_lawyer_bot.handlers.messages.Runner") as MockRunner:
        MockRunner.run_streamed.side_effect = lambda *a, **k: _make_stream_result()

        result = await _run_agent_with_retry(
            agent=MagicMock(), agent_input="q", session=MagicMock()
        )

        assert call_count["n"] == 3
        assert result.final_output == "ok"
```

### Step 2: Run the test

Run: `uv run pytest tests/test_pipeline_resilience.py::test_schema_violation_triggers_retry -v`
Expected: PASS. Confirms end-to-end interaction.

### Step 3: Commit

```bash
git add tests/test_pipeline_resilience.py
git commit -m "test: verify PipelineOutput schema violations trigger pipeline retry"
```

---

## Финальная проверка Фазы 2

- [ ] **Step 1: Полный прогон тестов**

Run: `uv run pytest tests/ -v`
Expected: всё зелёное, новые `test_schemas.py` (10 тестов) и обновлённый `test_pipeline_resilience.py` (7 тестов).

- [ ] **Step 2: Проверить git log**

Run: `git log --oneline -3`
Expected: видны 2 коммита Фазы 2:
- `feat(agent): enforce PipelineOutput action_type invariants via model_validator`
- `test: verify PipelineOutput schema violations trigger pipeline retry`

---

## Замечания для исполнителя

- **Зачем `mode="after"`:** валидатор должен видеть полностью построенный объект, чтобы проверять комбинации полей. `mode="before"` работает на сыром словаре и неудобен для типобезопасных проверок.
- **Поведение Pydantic с `Optional[X] = Field(default=None)`:** значение по умолчанию `None` остаётся доступным. Валидатор явно проверяет `is None`, чтобы отличить незаданное поле от пустой структуры.
- **`game_selection.candidates` пустой список:** это семантически невалидно (нечего выбирать), потому валидатор требует `candidates` быть непустым. Это явная защита от случая, когда модель сказала "выбери из вариантов", но вариантов не сгенерировала.
- **Почему не трогаем `definition.py` (промпт):** комбинации, которые модель должна возвращать, и так описаны в промпте. Валидатор лишь технический safety-net. Будущие правки промпта возможны в Фазе 3.
- **Почему сохраняем Optional:** SDK не примет non-Optional поля, которые модель НЕ всегда заполняет. Pydantic JSON schema всё ещё помечает их `nullable: true` — модель видит, что они опциональны на схема-уровне, но валидатор накладывает per-action_type инварианты после парсинга.

## Out of scope (отложено в Фазу 3 или out-of-scope полностью)

- Wrapper-pattern с `Union[ClarificationOutput, ...]` и discriminator (повышает type safety, но ломает контракт с моделью и увеличивает промпт).
- Отдельные классы `ClarificationOutput`/`FinalAnswerOutput`/etc. — текущая плоская схема + валидатор обеспечивает ту же гарантию с меньшим diff'ом.
- Обновление `handler.py` под `isinstance` — он работает корректно через `action_type` matching, переписывание ничего не даёт.
