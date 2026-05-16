"""Tests for conversation-context trimming.

Reproduces the production 400: cumulative session history + large tool
outputs exceed the model's 131072-token window. The trimming filter must
bound every model call below budget while keeping the transcript
structurally valid (never orphan a tool result from its tool call).
"""

import pytest

from src.rules_lawyer_bot.utils.context_window import (
    build_context_trimming_filter,
    estimate_tokens,
    trim_model_input,
)


class _ModelInputData:
    """Mirror of agents.run.ModelInputData (duck-typed for the filter)."""

    def __init__(self, input, instructions):
        self.input = input
        self.instructions = instructions


class _CallModelData:
    """Mirror of agents.run.CallModelData."""

    def __init__(self, model_data):
        self.model_data = model_data
        self.agent = None
        self.context = None


def _user(text: str) -> dict:
    return {"role": "user", "content": text}


def _assistant(text: str) -> dict:
    return {"role": "assistant", "content": text}


def _huge_tool_output(n_chars: int) -> dict:
    # Cyrillic-heavy payload like a read_full_document result.
    return {"role": "tool", "content": "правила игры " * (n_chars // 12)}


def test_estimate_tokens_is_conservative_for_cyrillic():
    """Cyrillic must not be under-counted (it tokenizes worse than ASCII)."""
    # 3000 Cyrillic chars: a 4-char/token estimate would say ~750 and lie.
    items = [{"role": "user", "content": "а" * 3000}]
    assert estimate_tokens(items) >= 1000


def test_trim_keeps_everything_when_under_budget():
    md = _ModelInputData(
        input=[_user("hi"), _assistant("hello")],
        instructions="SYS",
    )
    out = trim_model_input(md, max_tokens=100_000)
    assert out.input == md.input
    assert out.instructions == "SYS"


def test_trim_drops_oldest_turns_when_over_budget():
    """A session with three turns where two old turns carry huge tool dumps
    must be trimmed below budget, keeping the most recent user message."""
    items = [
        _user("turn1: rules?"),
        _huge_tool_output(200_000),
        _assistant("turn1 answer"),
        _user("turn2: more rules?"),
        _huge_tool_output(200_000),
        _assistant("turn2 answer"),
        _user("turn3: final question"),
    ]
    md = _ModelInputData(input=items, instructions="SYS")

    out = trim_model_input(md, max_tokens=20_000)

    assert estimate_tokens(out.input) <= 20_000
    # The latest user message must survive trimming.
    assert out.input[-1] == _user("turn3: final question")
    # Instructions are never trimmed.
    assert out.instructions == "SYS"


def test_trim_cuts_only_at_user_boundaries():
    """The kept suffix must start with a user message so tool_call/
    tool_output pairs are never split (which would cause a new 400)."""
    items = [
        _user("q1"),
        _huge_tool_output(150_000),
        _assistant("a1"),
        _user("q2"),
        _huge_tool_output(150_000),
        _assistant("a2"),
        _user("q3"),
    ]
    md = _ModelInputData(input=items, instructions="SYS")

    out = trim_model_input(md, max_tokens=15_000)

    assert out.input[0].get("role") == "user"


def test_filter_callable_returns_model_input_data_shape():
    """build_context_trimming_filter returns a callable usable as
    RunConfig.call_model_input_filter."""
    flt = build_context_trimming_filter(max_tokens=15_000)

    big = [
        _user("q1"),
        _huge_tool_output(300_000),
        _assistant("a1"),
        _user("q2"),
    ]
    md = _ModelInputData(input=big, instructions="SYS")
    result = flt(_CallModelData(md))

    assert hasattr(result, "input")
    assert hasattr(result, "instructions")
    assert estimate_tokens(result.input) <= 15_000
    assert result.instructions == "SYS"


@pytest.mark.asyncio
async def test_run_agent_passes_context_trimming_filter():
    """_run_agent_with_retry must wire the trimming filter into RunConfig
    so every model call is bounded."""
    from unittest.mock import MagicMock, patch

    from tenacity import wait_none

    with patch(
        "src.rules_lawyer_bot.handlers.messages._RETRY_WAIT", wait_none()
    ), patch("src.rules_lawyer_bot.handlers.messages.Runner") as MockRunner:
        mock_result = MagicMock()

        async def _empty_stream():
            return
            yield

        mock_result.stream_events = _empty_stream
        mock_result.new_items = []
        mock_result.final_output = None
        MockRunner.run_streamed.return_value = mock_result

        from src.rules_lawyer_bot.handlers.messages import _run_agent_with_retry

        await _run_agent_with_retry(
            agent=MagicMock(), agent_input="q", session=MagicMock()
        )

        _args, kwargs = MockRunner.run_streamed.call_args
        run_config = kwargs.get("run_config")
        assert run_config is not None
        assert run_config.call_model_input_filter is not None


def test_run_config_ties_tracing_to_langfuse_state():
    """On the request path SDK tracing must be on iff Langfuse can consume
    it. tracing_disabled mirrors `not settings.tracing_enabled` so that
    with no Langfuse the SDK tracer doesn't 401-and-retry against
    api.openai.com with a proxy key on every run. Asserted as an invariant
    so it holds regardless of the local .env."""
    from src.rules_lawyer_bot.config import settings
    from src.rules_lawyer_bot.handlers.messages import _RUN_CONFIG

    assert _RUN_CONFIG.tracing_disabled == (not settings.tracing_enabled)


def test_perf_filter_delegates_to_trimming_unchanged():
    """The perf-logging wrapper must return exactly what the underlying
    trimming filter returns (same shape, still bounded), regardless of
    whether perf_logging is on."""
    from src.rules_lawyer_bot.config import settings
    from src.rules_lawyer_bot.handlers.messages import _perf_model_input_filter

    big = [
        _user("q1"),
        _huge_tool_output(300_000),
        _assistant("a1"),
        _user("q2"),
    ]

    original = settings.perf_logging
    try:
        for flag in (False, True):
            settings.perf_logging = flag
            md = _ModelInputData(input=list(big), instructions="SYS")
            result = _perf_model_input_filter(_CallModelData(md))
            assert hasattr(result, "input")
            assert hasattr(result, "instructions")
            assert result.instructions == "SYS"
            assert estimate_tokens(result.input) <= settings.max_context_tokens
    finally:
        settings.perf_logging = original
