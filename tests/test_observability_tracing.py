"""The Agents SDK's built-in api.openai.com trace exporter must be
neutralised in every branch.

Behind a proxy API key the SDK's default BackendSpanExporter 401s and
retries with backoff on every run. setup_langfuse_instrumentation() must:
  - disable SDK tracing entirely when Langfuse is off / unavailable;
  - drop only the SDK backend exporter when Langfuse is on (the Langfuse
    OTel path must survive).
"""

from unittest.mock import patch

from src.rules_lawyer_bot.utils import observability


def test_langfuse_off_disables_sdk_tracing_entirely():
    with patch.object(
        type(observability.settings),
        "tracing_enabled",
        property(lambda self: False),
    ), patch("agents.set_tracing_disabled") as disable_mock:
        result = observability.setup_langfuse_instrumentation()

    assert result is False
    disable_mock.assert_called_once_with(True)


def test_instrumentation_failure_disables_sdk_tracing():
    """If Logfire import/setup fails, there is no Langfuse consumer, so SDK
    tracing must still be turned off (not left 401-ing)."""
    with patch.object(
        type(observability.settings),
        "tracing_enabled",
        property(lambda self: True),
    ), patch.object(
        observability,
        "_disable_agents_sdk_default_tracing",
    ) as disable_mock, patch(
        "src.rules_lawyer_bot.utils.observability.base64.b64encode",
        side_effect=RuntimeError("boom"),
    ):
        result = observability.setup_langfuse_instrumentation()

    assert result is False
    disable_mock.assert_called_once()


def test_drop_backend_exporter_clears_sdk_processors():
    """_drop_agents_sdk_backend_exporter removes the default
    BatchTraceProcessor (api.openai.com) while leaving the Langfuse OTel
    path — which lives outside the SDK trace provider — untouched."""
    from agents.tracing import get_trace_provider

    observability._drop_agents_sdk_backend_exporter()

    mp = getattr(get_trace_provider(), "_multi_processor")
    assert list(getattr(mp, "_processors", [])) == []
