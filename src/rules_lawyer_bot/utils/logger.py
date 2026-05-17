"""Centralized logging configuration.

Every record is enriched with:
- OpenTelemetry trace_id / span_id from the active span (empty when no span)
- Telegram user_id / chat_id from request_context contextvars

Output format is switchable via settings.log_format:
- "text" (default): human-readable single-line format for local development
- "json": structured JSON for log aggregators (Loki, Datadog, CloudWatch)
"""

import logging
import sys
from pathlib import Path
from typing import Optional

from src.rules_lawyer_bot.config import settings


# Fields injected by ContextFilter — listed here so JsonFormatter emits them
# even when the message string does not reference them.
_CONTEXT_FIELDS = ("trace_id", "span_id", "user_id", "username", "chat_id")


class ContextFilter(logging.Filter):
    """Attach OTel trace identifiers and request context to every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        trace_id, span_id = _current_trace_ids()
        record.trace_id = trace_id
        record.span_id = span_id

        # Lazy import: request_context is a leaf module, but doing the import
        # at the top would tie logger import order to it. Keep it loose.
        from src.rules_lawyer_bot.utils import request_context as rc

        record.user_id = rc.user_id_var.get()
        record.username = rc.username_var.get()
        record.chat_id = rc.chat_id_var.get()
        return True


def _current_trace_ids() -> tuple[Optional[str], Optional[str]]:
    """Return (trace_id, span_id) from the active OTel span, or (None, None).

    Returns hex strings in OTel's canonical 32-char / 16-char form. When no
    span is active (or OTel is not installed) both values are None.
    """
    try:
        from opentelemetry import trace as otel_trace

        span = otel_trace.get_current_span()
        ctx = span.get_span_context()
        if not ctx.is_valid:
            return None, None
        return f"{ctx.trace_id:032x}", f"{ctx.span_id:016x}"
    except Exception:
        return None, None


class _CompactTextFormatter(logging.Formatter):
    """Human-readable formatter that appends correlation IDs when present.

    Keeps the legacy single-line look but adds `[trace=... user=...]` only
    for records that actually carry context, so background/startup logs
    remain clean.
    """

    _BASE = "%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d"

    def __init__(self) -> None:
        super().__init__(fmt=self._BASE)

    def format(self, record: logging.LogRecord) -> str:
        head = super().format(record)

        ctx_parts = []
        trace_id = getattr(record, "trace_id", None)
        if trace_id:
            ctx_parts.append(f"trace={trace_id[:8]}")
        user_id = getattr(record, "user_id", None)
        if user_id is not None:
            ctx_parts.append(f"user={user_id}")

        ctx = f" [{' '.join(ctx_parts)}]" if ctx_parts else ""
        return f"{head}{ctx} - {record.getMessage()}"


def _build_formatter() -> logging.Formatter:
    """Pick formatter based on settings.log_format."""
    if settings.log_format.lower() == "json":
        try:
            from pythonjsonlogger.json import JsonFormatter
        except ImportError:  # python-json-logger < 3.0
            from pythonjsonlogger.jsonlogger import JsonFormatter  # type: ignore[no-redef]

        # The fmt string is a field manifest for JsonFormatter — it tells
        # the formatter which LogRecord attributes to emit. Context fields
        # come from ContextFilter; message/level/etc are stdlib defaults.
        base_fields = ("asctime", "levelname", "name", "filename", "lineno", "funcName", "message")
        field_list = " ".join(f"%({f})s" for f in base_fields + _CONTEXT_FIELDS)
        return JsonFormatter(
            fmt=field_list,
            rename_fields={
                "asctime": "ts",
                "levelname": "level",
                "lineno": "line",
                "funcName": "func",
            },
        )

    return _CompactTextFormatter()


def setup_logging() -> logging.Logger:
    """Configure application logging with file and console handlers."""

    logger = logging.getLogger("boardgame_bot")
    logger.setLevel(getattr(logging, settings.log_level.upper()))

    formatter = _build_formatter()
    ctx_filter = ContextFilter()

    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(ctx_filter)
    logger.addHandler(console_handler)

    # File handler
    log_file = Path(settings.data_path) / "app.log"
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(ctx_filter)
        logger.addHandler(file_handler)

        logger.info(f"Logging initialized - Log file: {log_file.absolute()}")
    except Exception as e:
        logger.warning(f"Failed to create log file at {log_file}: {e}")
        logger.warning("Continuing with console logging only")

    # Reduce noise from external libraries
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # Suppress OpenTelemetry/Logfire trace logs
    logging.getLogger("logfire").setLevel(logging.WARNING)
    logging.getLogger("opentelemetry").setLevel(logging.WARNING)
    logging.getLogger("opentelemetry.sdk.trace").setLevel(logging.WARNING)
    logging.getLogger("opentelemetry.exporter").setLevel(logging.WARNING)

    return logger


# Global logger instance
logger = setup_logging()
