"""Telegram message handler with agent integration.

Implements the main message processing flow with multi-stage pipeline
and streaming progress updates.
"""

import asyncio
import contextlib
import json
import re
import time
from contextvars import ContextVar
from typing import Optional

from agents import Runner, RunResultStreaming
from agents.exceptions import MaxTurnsExceeded, ModelBehaviorError
from agents.run import RunConfig
from openai import APIConnectionError, APITimeoutError
from pydantic import ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from telegram import Update
from telegram.ext import ContextTypes

from src.rules_lawyer_bot.agent import game_resolver
from src.rules_lawyer_bot.agent.definition import get_rules_agent, get_user_session
from src.rules_lawyer_bot.agent.schemas import PipelineOutput
from src.rules_lawyer_bot.config import settings
from src.rules_lawyer_bot.utils.budget import budget_tracker
from src.rules_lawyer_bot.utils.conversation_state import ConversationStage
from src.rules_lawyer_bot.utils.retention import (
    drop_trailing_clarification,
    trim_session,
)
from src.rules_lawyer_bot.pipeline.handler import (
    build_game_selection_keyboard,
    handle_pipeline_output,
)
from src.rules_lawyer_bot.pipeline.state import get_conversation_state
from src.rules_lawyer_bot.utils.context_window import (
    build_context_trimming_filter,
    estimate_tokens,
)
from src.rules_lawyer_bot.utils.logger import logger
from src.rules_lawyer_bot.utils.progress_reporter import ProgressReporter
from src.rules_lawyer_bot.utils.request_context import bind_request_context
from src.rules_lawyer_bot.utils.safety import rate_limiter
from src.rules_lawyer_bot.utils.telegram_helpers import send_long_message

# Blocklist patterns to prevent prompt injection and off-topic abuse
# Case-insensitive matching
BLOCKLIST_PATTERNS: list[str] = [
    # Prompt injection attempts
    r"ignore\s+(all\s+|previous\s+)?instructions",
    r"forget\s+(your\s+)?(all\s+|previous\s+)?instructions",
    r"disregard\s+(all\s+|previous\s+)?instructions",
    r"new\s+instructions",
    r"system\s*prompt",
    r"you\s+are\s+now",
    r"act\s+as\s+(a\s+)?(?!rules)",  # "act as" but not "act as rules lawyer"
    r"pretend\s+(to\s+be|you\s+are)",
    r"roleplay\s+as",
    # Requests to write code
    r"(write|generate|create)\s+(me\s+)?(a\s+)?(python|code|script|program)",
    r"напиши\s+(мне\s+)?(код|скрипт|программу)",
    # Jailbreak attempts
    r"dan\s+mode",
    r"jailbreak",
    r"bypass\s+(restrictions|filters|rules)",
]

# Compile patterns for performance
_BLOCKLIST_REGEX = re.compile(
    "|".join(f"({p})" for p in BLOCKLIST_PATTERNS), re.IGNORECASE
)

BLOCKLIST_RESPONSE = (
    "🎲 Я — помощник по правилам настольных игр. "
    "Задайте вопрос о правилах какой-нибудь игры!"
)


def _check_blocklist(text: str) -> bool:
    """Check if text matches any blocklist pattern.

    Args:
        text: User message text

    Returns:
        True if message should be blocked, False otherwise
    """
    return bool(_BLOCKLIST_REGEX.search(text))


# ModelBehaviorError: the Agents SDK wraps a malformed structured-output
# ValidationError in ModelBehaviorError on the final-output path
# (agents/util/_json.py), so a bare ValidationError never surfaces there.
# A weaker model intermittently emits a PipelineOutput with the wrong
# field names / missing required fields; a retry usually yields a valid
# one. Without this it escapes to the generic error handler instead of
# being retried (then RETRY_EXHAUSTED_RESPONSE after 3 attempts).
#
# RateLimitError intentionally omitted: a 1-4s exponential backoff is too
# short to clear a real rate limit, and we lack Retry-After header parsing.
# Better to fail fast and let the user retry manually.
_RETRIABLE_ERRORS = (
    ValidationError,
    ModelBehaviorError,
    APIConnectionError,
    APITimeoutError,
)


RETRY_EXHAUSTED_RESPONSE = (
    "⚠️ Не удалось обработать запрос. Попробуйте переформулировать вопрос."
)

MAX_TURNS_RESPONSE = (
    "🔄 Запрос оказался слишком сложным — агент превысил лимит шагов. "
    "Попробуйте задать более конкретный вопрос."
)

AGENT_TIMEOUT_RESPONSE = (
    "⏱️ Запрос обрабатывался слишком долго и был прерван. "
    "Попробуйте переформулировать вопрос или повторить позже."
)

_RETRY_WAIT = wait_exponential(multiplier=1, min=1, max=4)

# Grace given to a cancelled drain task to unwind after
# result.cancel("immediate") before we ABANDON it. The SDK's
# stream_events() finally awaits the detached _run_impl_task with no
# timeout (result.py:339-342), so we must never block on the drain task
# indefinitely — abandoning is the only escape. See
# docs/superpowers/specs/2026-05-17-inactivity-watchdog-design.md.
_ABANDON_GRACE_SECONDS = 5.0


def _swallow_task_result(task: "asyncio.Task") -> None:
    """Done-callback: retrieve an abandoned task's outcome so asyncio does
    not log 'Task exception was never retrieved' for a zombie drain."""
    if task.cancelled():
        return
    with contextlib.suppress(Exception):
        task.exception()


async def _drain_with_watchdog(result: RunResultStreaming) -> None:
    """Drain result.stream_events() under an inactivity + absolute-ceiling
    watchdog, cancelling and ABANDONING the run on stall.

    Why a separate task + external cancel: Runner.run_streamed spawns the
    real work as a detached background task. stream_events() swallows a
    CancelledError delivered to the consumer (result.py:322) then, in its
    finally, awaits that frozen detached task with no timeout
    (result.py:339-342). So an asyncio.wait_for around the drain can never
    fire. The only working mechanism is to run the drain in its own task
    and, from OUTSIDE it, call result.cancel("immediate") (synchronous
    producer kill, result.py:283-290) then abandon the drain task.
    """
    loop = asyncio.get_running_loop()
    started = loop.time()
    last_event = started

    async def _drain() -> None:
        nonlocal last_event
        async for _event in result.stream_events():
            last_event = loop.time()

    drain_task = asyncio.create_task(_drain())
    drain_task.add_done_callback(_swallow_task_result)
    inactivity = float(settings.agent_stream_inactivity_timeout_seconds)
    ceiling = float(settings.agent_run_timeout_seconds)
    try:
        while True:
            now = loop.time()
            remaining = min(
                inactivity - (now - last_event),
                ceiling - (now - started),
            )
            if remaining > 0:
                await asyncio.wait({drain_task}, timeout=remaining)
            if drain_task.done():
                drain_task.result()  # re-raise retriable / SDK error if any
                return
            now = loop.time()
            stalled = (now - last_event) >= inactivity
            over_ceiling = (now - started) >= ceiling
            if not (stalled or over_ceiling):
                # event(s) arrived during the wait; neither budget expired
                # — loop back and wait again
                continue
            logger.warning(
                "Agent run aborted (%s): inactive %.1fs, total %.1fs; "
                "cancelling + abandoning",
                "inactivity" if stalled else "absolute ceiling",
                now - last_event,
                now - started,
            )
            try:
                result.cancel("immediate")  # sync, non-blocking
            except Exception:
                logger.exception("result.cancel() failed")
            drain_task.cancel()
            await asyncio.wait({drain_task}, timeout=_ABANDON_GRACE_SECONDS)
            if not drain_task.done():
                logger.warning(
                    "Drain task did not stop within %.0fs grace; "
                    "abandoning zombie (httpx read-timeout will reap it)",
                    _ABANDON_GRACE_SECONDS,
                )
            raise TimeoutError("agent stream inactive or absolute ceiling exceeded")
    finally:
        if not drain_task.done():
            drain_task.cancel()


# Per-run perf state. A ContextVar is isolated per asyncio task, so with
# concurrent_updates=True one user's turn counter never bleeds into
# another's. Holds {turn, attempts, start, last} where start/last are
# time.perf_counter() readings. None outside an instrumented run.
_perf_state: ContextVar[Optional[dict]] = ContextVar("agent_perf_state", default=None)


# The real trimming filter (pure, unit-tested in test_context_window.py).
_trim_filter = build_context_trimming_filter(max_tokens=settings.max_context_tokens)


def _summarize_tail(items, max_items: int = 4, max_chars: int = 600) -> str:
    """Compact, log-safe repr of the last few transcript items.

    Diagnostic only (gated by perf_logging). The tail of the model input on
    turn N contains the tool outputs and assistant decisions from turns
    1..N-1 — enough to see whether search returned no_match/ok and why the
    model keeps looping instead of answering.
    """
    try:
        tail = items[-max_items:]
    except Exception:
        return "<unreadable>"
    parts = []
    for it in tail:
        try:
            blob = json.dumps(it, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            blob = str(it)
        if len(blob) > max_chars:
            blob = blob[:max_chars] + f"…(+{len(blob) - max_chars} chars)"
        parts.append(blob)
    return " | ".join(parts)


def _perf_model_input_filter(call_data):
    """Logging wrapper around the context-trimming filter.

    The Agents SDK invokes ``call_model_input_filter`` before *every* model
    call — i.e. once per ReAct turn. That makes it the natural choke point
    to measure per-turn cadence and prompt size without touching the pure
    trimming logic. When perf_logging is on we log one line per turn, then
    delegate to the real filter unchanged.
    """
    if settings.perf_logging:
        state = _perf_state.get()
        if state is not None:
            now = time.perf_counter()
            state["turn"] += 1
            delta = now - state["last"]
            state["last"] = now
            items: list = []
            try:
                items = call_data.model_data.input
                est = estimate_tokens(items)
                n_items = len(items)
            except Exception:
                est, n_items = -1, -1
            logger.info(
                "[Perf] model turn %d: prev turn +%.2fs, input≈%d est_tokens, %d items",
                state["turn"],
                delta,
                est,
                n_items,
            )
            if n_items > 0:
                logger.info(
                    "[Perf] turn %d tail: %s",
                    state["turn"],
                    _summarize_tail(items),
                )
    return _trim_filter(call_data)


# Bound every model call (including each internal ReAct turn) to a token
# budget so accumulated session history + large tool outputs cannot exceed
# the model's context window. Stateless — safe to build once.
#
# tracing_disabled: the Agents SDK enables tracing by default and its
# BackendSpanExporter POSTs spans to a hardcoded https://api.openai.com
# endpoint with OPENAI_API_KEY. With a proxy key that is not a real OpenAI
# key this 401s and retries with backoff on every run. When Langfuse is not
# configured we have no use for SDK traces, so disable them for the request
# path entirely.
_RUN_CONFIG = RunConfig(
    call_model_input_filter=_perf_model_input_filter,
    tracing_disabled=not settings.tracing_enabled,
)


async def _run_agent_with_retry(agent, agent_input: str, session) -> RunResultStreaming:
    """Run the agent with bounded retries on transient/structured failures.

    Retries on ValidationError / ModelBehaviorError / OpenAI network
    errors. MaxTurnsExceeded and TimeoutError are NOT retried (re-running
    a stalled model just multiplies the wait).

    The drain runs under _drain_with_watchdog, which bounds it by an
    inactivity budget AND an absolute wall-clock ceiling and aborts via
    cancel + abandon. The old outer asyncio.wait_for is removed: the
    Agents SDK neutralizes it (see the design spec).
    """
    # Seed per-run perf state BEFORE any task is created: the shared dict
    # is mutated in place by the perf model-input filter from inside the
    # SDK's detached task context; rebinding via .set() would not
    # propagate. perf_logging only gates emission, not bookkeeping.
    now = time.perf_counter()
    _perf_state.set({"turn": 0, "attempts": 0, "start": now, "last": now})

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=_RETRY_WAIT,
        retry=retry_if_exception_type(_RETRIABLE_ERRORS),
        reraise=True,
    ):
        with attempt:
            state = _perf_state.get()
            if state is not None:
                state["attempts"] += 1
            result = Runner.run_streamed(
                starting_agent=agent,
                input=agent_input,
                session=session,
                max_turns=8,
                run_config=_RUN_CONFIG,
            )
            # Drain inside its own task under the watchdog. A stored
            # ValidationError/ModelBehaviorError surfaces here (re-raised
            # by drain_task.result()) so AsyncRetrying still retries it.
            await _drain_with_watchdog(result)
            return result
    # Unreachable: AsyncRetrying(reraise=True) either returns or re-raises.
    raise AssertionError("retry loop exited without a result")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all text messages using multi-stage pipeline.

    Flow:
    1. Check rate limit
    2. Get conversation state
    3. Build context-aware input
    4. Stream agent execution with progress updates
    5. Route output based on type (pipeline/reasoned answer/fallback)

    Args:
        update: Telegram update object
        context: Telegram context
    """
    if (
        update.effective_user is None
        or update.message is None
        or update.effective_chat is None
        or update.message.text is None
    ):
        return
    user = update.effective_user
    message = update.message
    chat = update.effective_chat
    message_text = update.message.text

    # Bind request context BEFORE the first log call so user_id/chat_id
    # are attached to every record from this task. ContextVars + Sentry
    # SDK 2.x asyncio scope isolation keep concurrent requests separated.
    bind_request_context(user.id, user.username, chat.id)

    logger.info(f"User {user.id}: {message_text[:100]}")

    # Create root span for Langfuse trace with input/output
    # See: https://langfuse.com/faq/all/empty-trace-input-and-output
    tracer = None
    if settings.tracing_enabled:
        try:
            from opentelemetry import trace as otel_trace

            tracer = otel_trace.get_tracer(__name__)
        except Exception as e:
            logger.debug(f"Failed to initialize tracer: {e}")

    # Check rate limit (outside trace to avoid unnecessary spans)
    allowed, rate_limit_msg = await rate_limiter.check_rate_limit(user.id)
    if not allowed:
        await message.reply_text(f"⏳ {rate_limit_msg}")
        return

    # Per-user budget (admins exempt entirely; check fails open internally)
    if settings.budget_enabled and user.id not in settings.admin_ids:
        decision = await budget_tracker.check(user.id)
        if not decision.allowed:
            logger.info(f"Budget block for user {user.id}: {decision.reason}")
            retry = (
                f"\nЛимит вернётся: {decision.retry_at:%Y-%m-%d %H:%M UTC}"
                if decision.retry_at
                else ""
            )
            await message.reply_text(f"🚫 {decision.reason}{retry}")
            return

    # Check blocklist patterns (outside trace to avoid unnecessary spans)
    if _check_blocklist(message_text):
        logger.warning(
            f"Blocklist triggered for user {user.id}: {message_text[:50]}..."
        )
        await message.reply_text(BLOCKLIST_RESPONSE)
        return

    # Helper to run the main processing logic
    async def _process_message():
        """Main processing logic wrapped in root span for Langfuse tracing."""
        # Get conversation state
        conv_state = get_conversation_state(context, user.id)

        # P2: is this message an ANSWER to a clarification we asked?
        answering_clarification = (
            conv_state.stage == ConversationStage.AWAITING_CLARIFICATION
        )
        pending_q = conv_state.pending_question
        if answering_clarification:
            conv_state.reset_pending()

        # P1: deterministic pre-agent resolver. Skip it when a game is
        # already sticky (a follow-up question is not a game name) UNLESS
        # this is a clarification answer (expected to be a title).
        run_resolver = (not conv_state.has_game_context()) or answering_clarification
        decision = (
            game_resolver.resolve(message_text)
            if run_resolver
            else game_resolver.ResolverResult(kind="ambiguous")
        )

        if decision.kind == "multiple":
            logger.info(
                "[Resolver] multiple (%d candidates) for %r",
                len(decision.candidates),
                message_text[:60],
            )
            conv_state.stage = ConversationStage.AWAITING_GAME_SELECTION
            conv_state.game_candidates = [
                {
                    "english_name": c["english_name"],
                    "pdf_filename": c["pdf_filename"],
                }
                for c in decision.candidates
            ]
            keyboard = build_game_selection_keyboard(conv_state.game_candidates)
            await message.reply_text(
                "🎮 Какую именно игру вы имеете в виду?",
                reply_markup=keyboard,
            )
            return "resolver: multiple"

        if decision.kind == "resolved":
            assert decision.game is not None and decision.pdf is not None
            conv_state.set_game(decision.game, decision.pdf)
            logger.info(
                "[Resolver] resolved %r -> %s (score=%.0f)",
                message_text[:60],
                decision.game,
                decision.score,
            )

        # Build context-aware input for agent
        agent_input = message_text
        if conv_state.has_game_context():
            agent_input = (
                f"[Context: Current game is '{conv_state.current_game}', "
                f"PDF: '{conv_state.current_pdf}']\n\n"
                f"User question: {message_text}"
            )
            logger.debug(f"[Pipeline] Injected game context: {conv_state.current_game}")
        elif answering_clarification and pending_q:
            agent_input = (
                f'[The user was previously asked: "{pending_q}". Their '
                f'answer: "{message_text}". Re-resolve the game from this '
                f"answer and proceed; do NOT repeat the previous "
                f"clarification.]\n\n{message_text}"
            )
            logger.debug("[Pipeline] Reframed clarification answer")

        # Send typing indicator
        await context.bot.send_chat_action(chat_id=chat.id, action="typing")

        # Create progress reporter for streaming updates
        progress = ProgressReporter(context.bot, chat.id)

        session = None
        try:
            # Get user-specific session
            logger.debug(f"[Perf] Getting session for user {user.id}")
            session = get_user_session(user.id)
            if answering_clarification:
                try:
                    await drop_trailing_clarification(session)
                except Exception:
                    logger.exception("drop_trailing_clarification failed")
            logger.debug("[Perf] Session loaded, starting agent run")

            # Run agent with streaming + bounded retries
            logger.debug("[Perf] Starting agent run with _run_agent_with_retry")
            try:
                result = await _run_agent_with_retry(
                    agent=get_rules_agent(),
                    agent_input=agent_input,
                    session=session,
                )
            except MaxTurnsExceeded:
                logger.warning(f"MaxTurnsExceeded for user {user.id}")
                await progress.finalize()
                await message.reply_text(MAX_TURNS_RESPONSE)
                return MAX_TURNS_RESPONSE
            except TimeoutError as e:
                logger.warning("Agent run timed out for user %s: %s", user.id, e)
                await progress.finalize()
                await message.reply_text(AGENT_TIMEOUT_RESPONSE)
                return AGENT_TIMEOUT_RESPONSE
            except _RETRIABLE_ERRORS as e:
                # With tenacity reraise=True, the last retriable error
                # propagates here after attempts are exhausted.
                logger.warning(
                    f"Retry exhausted for user {user.id}: {type(e).__name__}"
                )
                await progress.finalize()
                await message.reply_text(RETRY_EXHAUSTED_RESPONSE)
                return RETRY_EXHAUSTED_RESPONSE

            # Record budget usage for the completed run (admins exempt).
            if settings.budget_enabled and user.id not in settings.admin_ids:
                usage = getattr(getattr(result, "context_wrapper", None), "usage", None)
                total_tokens = getattr(usage, "total_tokens", 0) or 0
                await budget_tracker.record(user.id, total_tokens)

            # One-line perf summary for latency diagnostics. Decomposes
            # "slow" into many-turns vs slow-per-turn (proxy/schema). turns
            # is the number of model calls (filter invocations); compare
            # against a single-call latency on the same model elsewhere to
            # isolate the proxy constant.
            if settings.perf_logging:
                pstate = _perf_state.get() or {}
                run_seconds = (
                    time.perf_counter() - pstate["start"] if "start" in pstate else -1.0
                )
                tool_calls = sum(
                    1 for it in result.new_items if it.type == "tool_call_item"
                )
                psum_usage = getattr(
                    getattr(result, "context_wrapper", None), "usage", None
                )
                psum_tokens = getattr(psum_usage, "total_tokens", 0) or 0
                logger.info(
                    "[Perf] run summary: total=%.2fs attempts=%d "
                    "turns≈%d tool_calls=%d total_tokens=%d",
                    run_seconds,
                    pstate.get("attempts", 0),
                    pstate.get("turn", 0),
                    tool_calls,
                    psum_tokens,
                )

            # Replay progress events from completed stream (we drained it
            # inside _run_agent_with_retry to surface ValidationError;
            # for live progress reporting we now iterate result.new_items).
            for item in result.new_items:
                if item.type == "tool_call_item":
                    tool_name = getattr(item, "name", None)
                    if tool_name is None and hasattr(item, "raw_item"):
                        tool_name = getattr(item.raw_item, "name", "unknown")
                    args = None
                    if hasattr(item, "raw_item") and hasattr(
                        item.raw_item, "arguments"
                    ):
                        try:
                            args = json.loads(item.raw_item.arguments)
                        except (json.JSONDecodeError, TypeError):
                            pass
                    await progress.report_tool_call(
                        str(tool_name) if tool_name else "unknown", args
                    )

            # Force final update before response
            await progress.force_update()

            # Log execution details
            logger.debug(f"Agent steps: {len(result.new_items)}")
            for i, step in enumerate(result.new_items, 1):
                # Pretty-print structured outputs, show summary for others
                if hasattr(step, "raw_item") and hasattr(step.raw_item, "content"):
                    # Extract just the text content from message outputs
                    content = step.raw_item.content
                    if isinstance(content, list) and len(content) > 0:
                        text_content = (
                            content[0].text
                            if hasattr(content[0], "text")
                            else str(content[0])
                        )
                        # Pretty-print JSON if it's parseable
                        try:
                            parsed = json.loads(text_content)
                            _dump = getattr(step.raw_item, "model_dump_json", None)
                            raw_repr = (
                                _dump(indent=2, ensure_ascii=False)
                                if callable(_dump)
                                else str(step.raw_item)
                            )
                            logger.debug(f"  Step {i}: {step.type}: {raw_repr}")
                            logger.debug(
                                f"    Output (formatted):\n"
                                f"{json.dumps(parsed, indent=2, ensure_ascii=False)}"
                            )
                        except (json.JSONDecodeError, AttributeError):
                            # Not JSON, log first 200 chars
                            preview = (
                                text_content[:200] + "..."
                                if len(text_content) > 200
                                else text_content
                            )
                            logger.debug(f"  Step {i}: {step.type} - {preview}")
                    else:
                        logger.debug(f"  Step {i}: {step.type}")
                else:
                    # For other step types, show summary
                    logger.debug(f"  Step {i}: {type(step).__name__}")

            # Handle multi-stage pipeline output
            if isinstance(result.final_output, PipelineOutput):
                # Delete progress message before sending response
                await progress.finalize()
                await handle_pipeline_output(
                    result.final_output, update, context, user.id
                )
                # Return structured output for trace
                return result.final_output.model_dump_json(ensure_ascii=False)
            else:
                # Fallback for non-structured output
                response_text = (
                    str(result.final_output)
                    if result.final_output
                    else "No response generated"
                )
                logger.warning(
                    f"Non-structured output received: {type(result.final_output)}"
                )

                # Delete progress message before sending response
                await progress.finalize()
                await send_long_message(
                    bot=context.bot, chat_id=chat.id, text=response_text
                )
                # Return text output for trace
                return response_text

        except Exception as e:
            # Clean up progress message on error
            await progress.finalize()
            logger.exception(f"Error handling message from user {user.id}")

            error_message = (
                "❌ An error occurred while processing your request. "
                "Please try again or contact support."
            )

            await message.reply_text(error_message)
            # Return error for trace
            return f"Error: {e}"
        finally:
            # Bound stored history after the answer is sent. Never let a
            # trim glitch break the user's response or the trace.
            if session is not None:
                try:
                    await trim_session(session, settings.session_max_turns)
                except Exception:
                    logger.exception("trim_session failed")

    # Run with root span for Langfuse tracing
    if tracer is not None:
        # Create root span with user context
        from src.rules_lawyer_bot.utils.observability import get_trace_context_for_user

        trace_attrs = get_trace_context_for_user(user.id, user.username)
        # Add session ID for Langfuse session grouping
        trace_attrs["langfuse.session.id"] = str(chat.id)
        # Set input at trace level (required for Langfuse)
        trace_attrs["input"] = message_text

        with tracer.start_as_current_span(
            "telegram_message_handler", attributes=trace_attrs
        ) as root_span:
            # Run processing and get output
            output = await _process_message()

            # Set output at trace level (required for Langfuse)
            if root_span.is_recording():
                root_span.set_attribute("output", output)
    else:
        # No tracing, run directly
        await _process_message()
