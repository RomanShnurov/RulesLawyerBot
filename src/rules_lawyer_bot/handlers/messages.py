"""Telegram message handler with agent integration.

Implements the main message processing flow with multi-stage pipeline
and streaming progress updates.
"""

import json
import re

import sentry_sdk
from agents import Runner
from agents.exceptions import MaxTurnsExceeded
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

from src.rules_lawyer_bot.agent.definition import get_rules_agent, get_user_session
from src.rules_lawyer_bot.agent.schemas import PipelineOutput
from src.rules_lawyer_bot.config import settings
from src.rules_lawyer_bot.utils.budget import budget_tracker
from src.rules_lawyer_bot.utils.retention import trim_session
from src.rules_lawyer_bot.pipeline.handler import handle_pipeline_output
from src.rules_lawyer_bot.pipeline.state import get_conversation_state
from src.rules_lawyer_bot.utils.context_window import (
    build_context_trimming_filter,
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
    "|".join(f"({p})" for p in BLOCKLIST_PATTERNS),
    re.IGNORECASE
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


# RateLimitError intentionally omitted: a 1-4s exponential backoff is too
# short to clear a real rate limit, and we lack Retry-After header parsing.
# Better to fail fast and let the user retry manually.
_RETRIABLE_ERRORS = (
    ValidationError,
    APIConnectionError,
    APITimeoutError,
)


RETRY_EXHAUSTED_RESPONSE = (
    "⚠️ Не удалось обработать запрос. "
    "Попробуйте переформулировать вопрос."
)

MAX_TURNS_RESPONSE = (
    "🔄 Запрос оказался слишком сложным — агент превысил лимит шагов. "
    "Попробуйте задать более конкретный вопрос."
)

_RETRY_WAIT = wait_exponential(multiplier=1, min=1, max=4)

# Bound every model call (including each internal ReAct turn) to a token
# budget so accumulated session history + large tool outputs cannot exceed
# the model's context window. Stateless — safe to build once.
_RUN_CONFIG = RunConfig(
    call_model_input_filter=build_context_trimming_filter(
        max_tokens=settings.max_context_tokens
    )
)


async def _run_agent_with_retry(agent, agent_input: str, session):
    """Run the agent with bounded retries on transient/structured failures.

    Retries on ValidationError (LLM returned malformed JSON) and OpenAI
    network errors. Business errors propagate immediately.
    MaxTurnsExceeded is not retried — it propagates to the caller.
    """
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=_RETRY_WAIT,
        retry=retry_if_exception_type(_RETRIABLE_ERRORS),
        reraise=True,
    ):
        with attempt:
            result = Runner.run_streamed(
                starting_agent=agent,
                input=agent_input,
                session=session,
                max_turns=8,
                run_config=_RUN_CONFIG,
            )
            # Drain the stream so any ValidationError surfaces here, inside
            # the retry attempt, rather than later in the caller.
            # This means live tool-call progress is no longer reported during
            # the run — events are replayed from `result.new_items` after
            # completion.  This is a deliberate tradeoff to enable retry on
            # structured-output ValidationError.
            async for _event in result.stream_events():
                pass
            return result


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
    user = update.effective_user
    message_text = update.message.text

    # Bind request context BEFORE the first log call so user_id/chat_id
    # are attached to every record from this task. ContextVars + Sentry
    # SDK 2.x asyncio scope isolation keep concurrent requests separated.
    bind_request_context(user.id, user.username, update.effective_chat.id)

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
        await update.message.reply_text(f"⏳ {rate_limit_msg}")
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
            await update.message.reply_text(f"🚫 {decision.reason}{retry}")
            return

    # Check blocklist patterns (outside trace to avoid unnecessary spans)
    if _check_blocklist(message_text):
        logger.warning(f"Blocklist triggered for user {user.id}: {message_text[:50]}...")
        await update.message.reply_text(BLOCKLIST_RESPONSE)
        return

    # Helper to run the main processing logic
    async def _process_message():
        """Main processing logic wrapped in root span for Langfuse tracing."""
        # Get conversation state
        conv_state = get_conversation_state(context, user.id)

        # Build context-aware input for agent
        agent_input = message_text

        # Inject game context if available
        if conv_state.has_game_context():
            agent_input = (
                f"[Context: Current game is '{conv_state.current_game}', "
                f"PDF: '{conv_state.current_pdf}']\n\n"
                f"User question: {message_text}"
            )
            logger.debug(
                f"[Pipeline] Injected game context: {conv_state.current_game}"
            )

        # Send typing indicator
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action="typing"
        )

        # Create progress reporter for streaming updates
        progress = ProgressReporter(context.bot, update.effective_chat.id)

        try:
            # Get user-specific session
            logger.debug(f"[Perf] Getting session for user {user.id}")
            session = get_user_session(user.id)
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
                logger.warning(
                    f"MaxTurnsExceeded for user {user.id}"
                )
                await progress.finalize()
                await update.message.reply_text(MAX_TURNS_RESPONSE)
                return MAX_TURNS_RESPONSE
            except _RETRIABLE_ERRORS as e:
                # With tenacity reraise=True, the last retriable error
                # propagates here after attempts are exhausted.
                logger.warning(
                    f"Retry exhausted for user {user.id}: {type(e).__name__}"
                )
                await progress.finalize()
                await update.message.reply_text(RETRY_EXHAUSTED_RESPONSE)
                return RETRY_EXHAUSTED_RESPONSE

            # Record budget usage for the completed run (admins exempt).
            if settings.budget_enabled and user.id not in settings.admin_ids:
                usage = getattr(
                    getattr(result, "context_wrapper", None), "usage", None
                )
                total_tokens = getattr(usage, "total_tokens", 0) or 0
                await budget_tracker.record(user.id, total_tokens)

            # Replay progress events from completed stream (we drained it
            # inside _run_agent_with_retry to surface ValidationError;
            # for live progress reporting we now iterate result.new_items).
            for item in result.new_items:
                if item.type == "tool_call_item":
                    tool_name = getattr(item, "name", None)
                    if tool_name is None and hasattr(item, "raw_item"):
                        tool_name = getattr(item.raw_item, "name", "unknown")
                    args = None
                    if hasattr(item, "raw_item") and hasattr(item.raw_item, "arguments"):
                        try:
                            args = json.loads(item.raw_item.arguments)
                        except (json.JSONDecodeError, TypeError):
                            pass
                    await progress.report_tool_call(tool_name, args)

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
                            logger.debug(
                                f"  Step {i}: {step.type}: "
                                f"{step.raw_item.model_dump_json(indent=2, ensure_ascii=False)}"
                            )
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
                    bot=context.bot, chat_id=update.effective_chat.id, text=response_text
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

            await update.message.reply_text(error_message)
            # Return error for trace
            return f"Error: {e}"

    # Run with root span for Langfuse tracing
    if tracer is not None:
        # Create root span with user context
        from src.rules_lawyer_bot.utils.observability import get_trace_context_for_user

        trace_attrs = get_trace_context_for_user(user.id, user.username)
        # Add session ID for Langfuse session grouping
        trace_attrs["langfuse.session.id"] = str(update.effective_chat.id)
        # Set input at trace level (required for Langfuse)
        trace_attrs["input"] = message_text

        with tracer.start_as_current_span(
            "telegram_message_handler",
            attributes=trace_attrs
        ) as root_span:
            # Run processing and get output
            output = await _process_message()

            # Set output at trace level (required for Langfuse)
            if root_span.is_recording():
                root_span.set_attribute("output", output)
    else:
        # No tracing, run directly
        await _process_message()
