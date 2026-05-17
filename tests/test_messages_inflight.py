"""Per-user in-flight lock + orphan-turn sweep wiring in handle_message."""

import asyncio
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.rules_lawyer_bot.handlers import messages


def _update(user_id, text="rules?"):
    upd = MagicMock()
    upd.effective_user.id = user_id
    upd.effective_user.username = "u"
    upd.effective_chat.id = 555
    upd.message.text = text
    upd.message.reply_text = AsyncMock()
    return upd


def _context():
    ctx = MagicMock()
    ctx.user_data = {}
    ctx.bot.send_chat_action = AsyncMock()
    return ctx


@pytest.fixture(autouse=True)
def _clear_locks():
    messages._user_run_locks.clear()
    yield
    messages._user_run_locks.clear()


def _common_patches(run_mock, sweep=None):
    """Patch everything _process_message touches before/around the run so
    the test exercises only the in-flight gate. Pass `sweep` to substitute
    the drop_trailing_unanswered_user_turn mock explicitly."""
    prog = MagicMock()
    prog.finalize = AsyncMock()
    prog.report_tool_call = AsyncMock()
    prog.force_update = AsyncMock()
    return [
        patch.object(messages.settings, "budget_enabled", False),
        patch.object(
            messages.rate_limiter,
            "check_rate_limit",
            AsyncMock(return_value=(True, "")),
        ),
        patch.object(
            messages.game_resolver,
            "resolve",
            lambda *_a, **_k: types.SimpleNamespace(kind="ambiguous"),
        ),
        patch.object(messages, "get_user_session", lambda _uid: MagicMock()),
        patch.object(
            messages,
            "drop_trailing_unanswered_user_turn",
            sweep if sweep is not None else AsyncMock(return_value=False),
        ),
        patch.object(messages, "ProgressReporter", lambda *_a, **_k: prog),
        patch.object(messages, "trim_session", AsyncMock()),
        patch.object(messages, "send_long_message", AsyncMock()),
        patch.object(messages, "_run_agent_with_retry", run_mock),
    ]


@pytest.mark.asyncio
async def test_second_concurrent_message_is_dropped_with_notice():
    started = asyncio.Event()
    release = asyncio.Event()

    async def _blocking_run(*_a, **_k):
        started.set()
        await release.wait()
        r = MagicMock()
        r.new_items = []
        r.final_output = None
        return r

    run_mock = AsyncMock(side_effect=_blocking_run)
    patches = _common_patches(run_mock)
    for p in patches:
        p.start()
    try:
        first = asyncio.create_task(messages.handle_message(_update(42), _context()))
        await asyncio.wait_for(started.wait(), timeout=2)  # lock held now

        upd2 = _update(42)
        await messages.handle_message(upd2, _context())

        upd2.message.reply_text.assert_awaited_once()
        assert "обрабат" in upd2.message.reply_text.call_args[0][0].lower()
        assert run_mock.await_count == 1  # second run never started

        release.set()
        await asyncio.wait_for(first, timeout=2)
        assert run_mock.await_count == 1
    finally:
        for p in patches:
            p.stop()


@pytest.mark.asyncio
async def test_pre_run_orphan_sweep_is_called_before_agent():
    sweep = AsyncMock(return_value=True)

    async def _quick_run(*_a, **_k):
        # The pre-run sweep MUST have already run by the time the agent
        # is invoked; this assertion fails the test if ordering regresses.
        assert sweep.await_count == 1
        r = MagicMock()
        r.new_items = []
        r.final_output = None
        return r

    run_mock = AsyncMock(side_effect=_quick_run)
    patches = _common_patches(run_mock, sweep=sweep)
    for p in patches:
        p.start()
    try:
        await messages.handle_message(_update(7), _context())
        sweep.assert_awaited_once()
        assert run_mock.await_count == 1
    finally:
        for p in patches:
            p.stop()


@pytest.mark.asyncio
async def test_reactive_orphan_sweep_on_timeout():
    """When the agent run times out, the except-TimeoutError branch
    sweeps the just-orphaned user turn (reactive path) and the user gets
    the timeout response."""
    sweep = AsyncMock(return_value=True)

    async def _timeout_run(*_a, **_k):
        raise TimeoutError("agent stream inactive or absolute ceiling exceeded")

    run_mock = AsyncMock(side_effect=_timeout_run)
    upd = _update(99)
    patches = _common_patches(run_mock, sweep=sweep)
    for p in patches:
        p.start()
    try:
        await messages.handle_message(upd, _context())
        sweep.assert_awaited()  # reactive cleanup ran
        upd.message.reply_text.assert_awaited_once()
        assert upd.message.reply_text.call_args[0][0] == messages.AGENT_TIMEOUT_RESPONSE
        assert run_mock.await_count == 1  # TimeoutError is not retried here
    finally:
        for p in patches:
            p.stop()
