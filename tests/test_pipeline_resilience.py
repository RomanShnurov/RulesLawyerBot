"""Tests for Runner max_turns, retry, and fallback behaviour."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from tenacity import wait_none

from src.rules_lawyer_bot.handlers import messages as messages_module
from src.rules_lawyer_bot.handlers.messages import _run_agent_with_retry


@pytest.fixture(autouse=True)
def _fast_retry(monkeypatch):
    """Replace exponential wait with no-wait for test speed."""
    monkeypatch.setattr(
        "src.rules_lawyer_bot.handlers.messages._RETRY_WAIT",
        wait_none(),
    )


@pytest.mark.asyncio
async def test_run_agent_passes_max_turns():
    """Runner.run_streamed receives max_turns=8."""
    with patch("src.rules_lawyer_bot.handlers.messages.Runner") as MockRunner:
        mock_result = MagicMock()

        # stream_events should be an async iterator that yields nothing
        async def _empty_stream():
            return
            yield  # unreachable, makes this an async generator

        mock_result.stream_events = _empty_stream
        mock_result.new_items = []
        mock_result.final_output = None
        MockRunner.run_streamed.return_value = mock_result

        session = MagicMock()
        await _run_agent_with_retry(agent=MagicMock(), agent_input="q", session=session)

        _args, kwargs = MockRunner.run_streamed.call_args
        assert kwargs.get("max_turns") == 8


@pytest.mark.asyncio
async def test_retry_on_validation_error_then_success():
    """ValidationError is retried; success on third attempt is returned."""
    call_count = {"n": 0}

    def _fake_stream(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise _make_validation_error()
        result = MagicMock()

        async def _empty_stream():
            return
            yield

        result.stream_events = _empty_stream
        result.new_items = []
        result.final_output = "ok"
        return result

    with patch("src.rules_lawyer_bot.handlers.messages.Runner") as MockRunner:
        MockRunner.run_streamed.side_effect = _fake_stream

        result = await _run_agent_with_retry(
            agent=MagicMock(), agent_input="q", session=MagicMock()
        )

        assert call_count["n"] == 3
        assert result.final_output == "ok"


@pytest.mark.asyncio
async def test_no_retry_on_file_not_found():
    """Business errors (FileNotFoundError) propagate immediately, no retry."""
    call_count = {"n": 0}

    def _fake_stream(*_args, **_kwargs):
        call_count["n"] += 1
        raise FileNotFoundError("missing.pdf")

    with patch("src.rules_lawyer_bot.handlers.messages.Runner") as MockRunner:
        MockRunner.run_streamed.side_effect = _fake_stream

        with pytest.raises(FileNotFoundError):
            await _run_agent_with_retry(
                agent=MagicMock(), agent_input="q", session=MagicMock()
            )

        assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_retry_exhausted_raises_final_error():
    """After 3 ValidationError attempts, the last error propagates."""
    with patch("src.rules_lawyer_bot.handlers.messages.Runner") as MockRunner:
        MockRunner.run_streamed.side_effect = lambda *a, **k: (_ for _ in ()).throw(
            _make_validation_error()
        )

        with pytest.raises(ValidationError):
            await _run_agent_with_retry(
                agent=MagicMock(), agent_input="q", session=MagicMock()
            )


@pytest.mark.asyncio
async def test_retry_on_validation_error_from_stream():
    """ValidationError raised from stream_events() is retried (the real path)."""
    call_count = {"n": 0}

    def _make_stream_result():
        call_count["n"] += 1

        async def _stream():
            if call_count["n"] < 3:
                raise _make_validation_error()
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


@pytest.mark.asyncio
async def test_retry_on_model_behavior_error_then_success():
    """The Agents SDK wraps a malformed structured-output ValidationError
    in ModelBehaviorError on the final-output path (not a bare
    pydantic.ValidationError). That is exactly the 'LLM returned malformed
    JSON' case the retry is meant to cover, so it MUST be retried."""
    from agents.exceptions import ModelBehaviorError

    call_count = {"n": 0}

    def _make_stream_result():
        call_count["n"] += 1

        async def _stream():
            if call_count["n"] < 3:
                raise ModelBehaviorError("Invalid JSON when parsing ...")
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


@pytest.mark.asyncio
async def test_max_turns_exceeded_not_retried():
    """MaxTurnsExceeded propagates without retry."""
    from agents.exceptions import MaxTurnsExceeded

    call_count = {"n": 0}

    def _fake_stream(*_args, **_kwargs):
        call_count["n"] += 1
        raise MaxTurnsExceeded("max turns")

    with patch("src.rules_lawyer_bot.handlers.messages.Runner") as MockRunner:
        MockRunner.run_streamed.side_effect = _fake_stream

        with pytest.raises(MaxTurnsExceeded):
            await _run_agent_with_retry(
                agent=MagicMock(), agent_input="q", session=MagicMock()
            )

        assert call_count["n"] == 1


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
    schema_error = None
    try:
        PipelineOutput(
            action_type=ActionType.FINAL_ANSWER,
            final_answer=None,
            stage_reasoning="invalid",
        )
        raise AssertionError("Should have raised ValidationError")
    except _VE as e:
        schema_error = e

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


@pytest.mark.asyncio
async def test_agent_run_times_out_and_is_not_retried():
    """A stalled stream is bounded by a wall-clock timeout.

    A model/proxy that accepts the request but never finishes streaming
    raises none of the retriable errors, so without an explicit deadline
    the coroutine hangs forever and (with PTB sequential dispatch) freezes
    the whole bot. The wall-clock timeout must fire, raise TimeoutError,
    and NOT be retried (retrying a stalled model just triples the wait).
    """
    call_count = {"n": 0}

    def _hanging_result(*_args, **_kwargs):
        call_count["n"] += 1
        result = MagicMock()

        async def _stream():
            await asyncio.sleep(5)
            return
            yield  # makes this an async generator

        result.stream_events = _stream
        result.new_items = []
        result.final_output = None
        return result

    with (
        patch.object(messages_module.settings, "agent_run_timeout_seconds", 0.05),
        patch("src.rules_lawyer_bot.handlers.messages.Runner") as MockRunner,
    ):
        MockRunner.run_streamed.side_effect = _hanging_result

        with pytest.raises(TimeoutError):
            await _run_agent_with_retry(
                agent=MagicMock(), agent_input="q", session=MagicMock()
            )

    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_run_agent_initialises_perf_state():
    """_run_agent_with_retry seeds the per-run perf ContextVar so the
    model-input filter and the summary log have bookkeeping to read.
    attempts is bumped once per (successful) attempt."""
    from src.rules_lawyer_bot.handlers.messages import _perf_state

    with patch("src.rules_lawyer_bot.handlers.messages.Runner") as MockRunner:
        mock_result = MagicMock()

        async def _empty_stream():
            return
            yield

        mock_result.stream_events = _empty_stream
        mock_result.new_items = []
        mock_result.final_output = None
        MockRunner.run_streamed.return_value = mock_result

        await _run_agent_with_retry(
            agent=MagicMock(), agent_input="q", session=MagicMock()
        )

    state = _perf_state.get()
    assert state is not None
    assert state["attempts"] == 1
    assert "start" in state and "last" in state
    assert state["turn"] == 0  # Runner mocked -> filter never invoked


def test_inactivity_timeout_default_and_below_ceiling():
    """The per-stream-event inactivity budget exists, defaults to 45s,
    and is strictly below the absolute wall-clock ceiling."""
    from src.rules_lawyer_bot.config import settings

    assert settings.agent_stream_inactivity_timeout_seconds == 45
    assert (
        settings.agent_stream_inactivity_timeout_seconds
        < settings.agent_run_timeout_seconds
    )


def _make_validation_error() -> ValidationError:
    """Construct a real ValidationError for raising."""
    from pydantic import BaseModel

    class _Schema(BaseModel):
        x: int

    try:
        _Schema(x="not-an-int")  # type: ignore[arg-type]
    except ValidationError as e:
        return e
    raise AssertionError("ValidationError was not raised")
