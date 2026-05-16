"""Budget integration in the Telegram message handler."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.rules_lawyer_bot.utils.budget import BudgetDecision


def _update(user_id=999, text="rules?"):
    upd = MagicMock()
    upd.effective_user.id = user_id
    upd.effective_user.username = "u"
    upd.effective_chat.id = 555
    upd.message.text = text
    upd.message.reply_text = AsyncMock()
    return upd


def _context():
    ctx = MagicMock()
    ctx.bot.send_chat_action = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_over_budget_blocks_before_agent_runs():
    from datetime import datetime, timezone

    from src.rules_lawyer_bot.handlers import messages

    upd, ctx = _update(), _context()
    blocked = BudgetDecision(
        False, "Дневной лимит запросов исчерпан (50).",
        datetime(2026, 5, 17, tzinfo=timezone.utc),
    )
    with patch.object(messages.settings, "budget_enabled", True), \
         patch.object(type(messages.settings), "admin_ids", property(lambda self: [])), \
         patch.object(
             messages.budget_tracker, "check",
             AsyncMock(return_value=blocked)
         ), \
         patch.object(
             messages.rate_limiter, "check_rate_limit",
             AsyncMock(return_value=(True, "")),
         ), \
         patch.object(
             messages, "_run_agent_with_retry", AsyncMock()
         ) as run_mock:
        await messages.handle_message(upd, ctx)

    run_mock.assert_not_called()
    upd.message.reply_text.assert_awaited_once()
    assert "лимит" in upd.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_admin_bypasses_budget_entirely():
    from src.rules_lawyer_bot.handlers import messages

    upd, ctx = _update(user_id=42), _context()
    check_mock = AsyncMock()
    with patch.object(messages.settings, "budget_enabled", True), \
         patch.object(type(messages.settings), "admin_ids", property(lambda self: [42])), \
         patch.object(messages.budget_tracker, "check", check_mock), \
         patch.object(
             messages.rate_limiter, "check_rate_limit",
             AsyncMock(return_value=(True, "")),
         ), \
         patch.object(
             messages, "_run_agent_with_retry",
             AsyncMock(side_effect=RuntimeError("stop here")),
         ):
        await messages.handle_message(upd, ctx)

    check_mock.assert_not_called()


@pytest.mark.asyncio
async def test_session_trimmed_after_answer():
    from src.rules_lawyer_bot.handlers import messages

    upd, ctx = _update(), _context()
    fake_session = MagicMock()
    result = MagicMock()
    result.final_output = None
    result.new_items = []
    result.context_wrapper.usage.total_tokens = 123

    with patch.object(messages.settings, "budget_enabled", False), \
         patch.object(type(messages.settings), "admin_ids", property(lambda self: [])), \
         patch.object(messages.settings, "session_max_turns", 7), \
         patch.object(
             messages.rate_limiter, "check_rate_limit",
             AsyncMock(return_value=(True, "")),
         ), \
         patch.object(
             messages, "get_user_session", return_value=fake_session
         ), \
         patch.object(
             messages, "_run_agent_with_retry",
             AsyncMock(return_value=result),
         ), \
         patch.object(
             messages, "send_long_message", AsyncMock()
         ), \
         patch.object(
             messages, "trim_session", AsyncMock()
         ) as trim_mock:
        await messages.handle_message(upd, ctx)

    trim_mock.assert_awaited_once_with(fake_session, 7)


@pytest.mark.asyncio
async def test_agent_timeout_replies_and_returns():
    """A timed-out agent run gives the user a clear message and the handler
    returns cleanly (so PTB can dispatch the next message)."""
    from src.rules_lawyer_bot.handlers import messages

    upd, ctx = _update(), _context()
    fake_session = MagicMock()

    with patch.object(messages.settings, "budget_enabled", False), \
         patch.object(type(messages.settings), "admin_ids", property(lambda self: [])), \
         patch.object(
             messages.rate_limiter, "check_rate_limit",
             AsyncMock(return_value=(True, "")),
         ), \
         patch.object(
             messages, "get_user_session", return_value=fake_session
         ), \
         patch.object(
             messages, "_run_agent_with_retry",
             AsyncMock(side_effect=TimeoutError()),
         ), \
         patch.object(messages, "trim_session", AsyncMock()) as trim_mock:
        await messages.handle_message(upd, ctx)

    upd.message.reply_text.assert_awaited_once()
    sent = upd.message.reply_text.call_args[0][0].lower()
    assert "долго" in sent or "превыс" in sent or "timeout" in sent
    # Session cleanup still runs in the finally block.
    trim_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_perf_summary_logged_only_when_enabled():
    """The [Perf] run summary line is emitted on a successful run iff
    settings.perf_logging is True, and never otherwise."""
    from src.rules_lawyer_bot.handlers import messages

    for flag, expect in ((True, True), (False, False)):
        upd, ctx = _update(), _context()
        fake_session = MagicMock()
        result = MagicMock()
        result.final_output = None
        result.new_items = []
        result.context_wrapper.usage.total_tokens = 123

        with patch.object(messages.settings, "budget_enabled", False), \
             patch.object(messages.settings, "perf_logging", flag), \
             patch.object(
                 type(messages.settings), "admin_ids",
                 property(lambda self: []),
             ), \
             patch.object(
                 messages.rate_limiter, "check_rate_limit",
                 AsyncMock(return_value=(True, "")),
             ), \
             patch.object(
                 messages, "get_user_session", return_value=fake_session
             ), \
             patch.object(
                 messages, "_run_agent_with_retry",
                 AsyncMock(return_value=result),
             ), \
             patch.object(messages, "send_long_message", AsyncMock()), \
             patch.object(messages, "trim_session", AsyncMock()), \
             patch.object(messages, "logger") as log_mock:
            await messages.handle_message(upd, ctx)

        summary_logged = any(
            call.args
            and isinstance(call.args[0], str)
            and call.args[0].startswith("[Perf] run summary")
            for call in log_mock.info.call_args_list
        )
        assert summary_logged is expect


@pytest.mark.asyncio
async def test_trim_failure_does_not_break_response():
    from src.rules_lawyer_bot.handlers import messages

    upd, ctx = _update(), _context()
    fake_session = MagicMock()
    result = MagicMock()
    result.final_output = None
    result.new_items = []

    with patch.object(messages.settings, "budget_enabled", False), \
         patch.object(type(messages.settings), "admin_ids", property(lambda self: [])), \
         patch.object(
             messages.rate_limiter, "check_rate_limit",
             AsyncMock(return_value=(True, "")),
         ), \
         patch.object(
             messages, "get_user_session", return_value=fake_session
         ), \
         patch.object(
             messages, "_run_agent_with_retry",
             AsyncMock(return_value=result),
         ), \
         patch.object(messages, "send_long_message", AsyncMock()), \
         patch.object(
             messages, "trim_session",
             AsyncMock(side_effect=RuntimeError("trim boom")),
         ):
        # Must not raise.
        await messages.handle_message(upd, ctx)
