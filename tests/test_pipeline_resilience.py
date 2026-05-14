"""Tests for Runner max_turns, retry, and fallback behaviour."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from src.rules_lawyer_bot.handlers.messages import _run_agent_with_retry


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
        MockRunner.run_streamed.side_effect = lambda *a, **k: (_ for _ in ()).throw(_make_validation_error())

        with pytest.raises(ValidationError):
            await _run_agent_with_retry(
                agent=MagicMock(), agent_input="q", session=MagicMock()
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
