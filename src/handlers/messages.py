"""Telegram message handler with agent integration.

Implements the main message processing flow with multi-stage pipeline
and streaming progress updates.
"""

import json
import re

from agents import Runner
from telegram import Update
from telegram.ext import ContextTypes

from src.agent.definition import get_user_session, rules_agent
from src.agent.schemas import PipelineOutput, ReasonedAnswer
from src.config import settings
from src.formatters.sgr import format_reasoned_answer, log_reasoning_chain
from src.pipeline.handler import handle_pipeline_output
from src.pipeline.state import get_conversation_state
from src.utils.logger import logger
from src.utils.progress_reporter import ProgressReporter
from src.utils.safety import rate_limiter, ugrep_semaphore
from src.utils.telegram_helpers import send_long_message

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

    logger.info(f"User {user.id}: {message_text[:100]}")

    # Add user context and input to OpenTelemetry traces
    # See: https://langfuse.com/faq/all/empty-trace-input-and-output
    trace_span = None
    if settings.tracing_enabled:
        try:
            from opentelemetry import trace
            from src.utils.observability import get_trace_context_for_user

            trace_span = trace.get_current_span()
            if trace_span.is_recording():
                for key, value in get_trace_context_for_user(user.id, user.username).items():
                    trace_span.set_attribute(key, value)
                # Set input for Langfuse trace visibility
                trace_span.set_attribute("input.value", message_text)
                # Set session ID for Langfuse session grouping (chat_id groups conversation)
                trace_span.set_attribute("langfuse.session.id", str(update.effective_chat.id))
        except Exception as e:
            logger.debug(f"Failed to add trace context: {e}")

    # Check rate limit
    allowed, rate_limit_msg = await rate_limiter.check_rate_limit(user.id)
    if not allowed:
        await update.message.reply_text(f"⏳ {rate_limit_msg}")
        return

    # Check blocklist patterns (prompt injection, off-topic)
    if _check_blocklist(message_text):
        logger.warning(f"Blocklist triggered for user {user.id}: {message_text[:50]}...")
        await update.message.reply_text(BLOCKLIST_RESPONSE)
        return

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

        # Run agent with streaming to show progress
        async with ugrep_semaphore:
            logger.debug("[Perf] Acquired ugrep semaphore, calling Runner.run_streamed")
            result = Runner.run_streamed(
                starting_agent=rules_agent, input=agent_input, session=session
            )
            logger.debug("[Perf] Runner.run_streamed returned, waiting for first event")

            # Process streaming events
            event_count = 0
            async for event in result.stream_events():
                event_count += 1
                if event_count == 1:
                    logger.debug(f"[Perf] First event received: {event.type}")

                if event.type == "run_item_stream_event":
                    item = event.item
                    if item.type == "tool_call_item":
                        # Extract tool name and arguments
                        tool_name = getattr(item, "name", None)
                        if tool_name is None and hasattr(item, "raw_item"):
                            tool_name = getattr(item.raw_item, "name", "unknown")

                        # Extract arguments if available
                        args = None
                        if hasattr(item, "raw_item") and hasattr(item.raw_item, "arguments"):
                            try:
                                args = json.loads(item.raw_item.arguments)
                            except (json.JSONDecodeError, TypeError):
                                pass

                        logger.debug(f"[Perf] Tool call event received: {tool_name}")
                        await progress.report_tool_call(tool_name, args)
                        logger.debug(f"Tool called: {tool_name}")

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
            # Set output for Langfuse trace visibility
            if trace_span and trace_span.is_recording():
                try:
                    trace_span.set_attribute(
                        "output.value",
                        result.final_output.model_dump_json(ensure_ascii=False)
                    )
                except Exception:
                    pass
            # Delete progress message before sending response
            await progress.finalize()
            await handle_pipeline_output(
                result.final_output, update, context, user.id
            )
        elif isinstance(result.final_output, ReasonedAnswer):
            # Backward compatibility: handle old ReasonedAnswer format
            log_reasoning_chain(user.id, result.final_output)

            # Verbose output only for admins
            is_admin = settings.admin_ids and user.id in settings.admin_ids

            response_text = format_reasoned_answer(
                result.final_output,
                verbose=is_admin,
            )

            # Set output for Langfuse trace visibility
            if trace_span and trace_span.is_recording():
                try:
                    trace_span.set_attribute("output.value", response_text)
                except Exception:
                    pass

            # Delete progress message before sending response
            await progress.finalize()
            await send_long_message(
                bot=context.bot, chat_id=update.effective_chat.id, text=response_text
            )
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

            # Set output for Langfuse trace visibility
            if trace_span and trace_span.is_recording():
                try:
                    trace_span.set_attribute("output.value", response_text)
                except Exception:
                    pass

            # Delete progress message before sending response
            await progress.finalize()
            await send_long_message(
                bot=context.bot, chat_id=update.effective_chat.id, text=response_text
            )

        # Send trace URL to admin users for debugging
        if settings.admin_ids and user.id in settings.admin_ids and settings.tracing_enabled:
            try:
                from opentelemetry import trace
                from src.utils.observability import create_trace_url

                span = trace.get_current_span()
                if span.is_recording():
                    trace_id = format(span.get_span_context().trace_id, '032x')
                    trace_url = create_trace_url(trace_id)
                    if trace_url:
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=f"🔍 Debug trace: {trace_url}",
                            disable_web_page_preview=True,
                        )
            except Exception as e:
                logger.debug(f"Failed to send trace URL: {e}")

    except Exception as e:
        # Clean up progress message on error
        await progress.finalize()
        logger.exception(f"Error handling message from user {user.id}")

        error_message = (
            "❌ An error occurred while processing your request. "
            "Please try again or contact support."
        )

        # Set error output for Langfuse trace visibility
        if trace_span and trace_span.is_recording():
            try:
                trace_span.set_attribute("output.value", f"Error: {e}")
            except Exception:
                pass

        await update.message.reply_text(error_message)
