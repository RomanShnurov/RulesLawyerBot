"""Bounded SQLite session history.

OpenAI Agents SDK appends every turn (messages, tool calls, full tool
outputs) to a per-user SQLiteSession and never prunes (pop_item is LIFO
only). This module:

- trim_session(): inline, keep the last N user-turn boundaries.
- cleanup_stale_sessions() + budget prune: a daily background task that
  deletes abandoned session DB files and old budget rows.

trim_session cuts only at role=="user" items, so a tool_output is never
separated from its tool_call (same boundary rule as context_window.py).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Optional

from src.rules_lawyer_bot.utils.logger import logger


def _is_user(item: Any) -> bool:
    return isinstance(item, dict) and item.get("role") == "user"


_TOOL_PAYLOAD_LIMIT = 1500


def _tool_payload_key(item: Any) -> Optional[str]:
    """Return the payload field name if `item` is a stored tool result."""
    if not isinstance(item, dict):
        return None
    if item.get("type") == "function_call_output" and isinstance(
        item.get("output"), str
    ):
        return "output"
    if item.get("role") == "tool" and isinstance(item.get("content"), str):
        return "content"
    return None


def _evict_tool_payloads(items: list[Any], limit: int) -> tuple[list[Any], int]:
    """Replace oversized tool-result payloads with a compact stub.

    trim_session runs AFTER the answer is sent, so nothing is in flight; if
    a later turn needs the data the agent re-calls the tool (cheap: tools
    run in <0.05s). The item is kept and only its payload string shrinks, so
    every tool_call/tool_output pair stays structurally intact.
    """
    out: list[Any] = []
    evicted = 0
    for it in items:
        key = _tool_payload_key(it)
        if key is not None and len(it[key]) > limit:
            stub = dict(it)
            stub[key] = f"<elided: {len(it[key])} chars of stale tool output>"
            out.append(stub)
            evicted += 1
        else:
            out.append(it)
    return out, evicted


def _is_boundary(item: Any) -> bool:
    """Items that must not be dropped as a trailing-assistant run: user
    turns and tool calls/outputs (keeps tool pairing intact)."""
    if not isinstance(item, dict):
        return True
    if item.get("role") in ("user", "tool"):
        return True
    if item.get("type") in ("function_call", "function_call_output"):
        return True
    return False


async def drop_trailing_clarification(session: Any) -> bool:
    """Remove the trailing assistant/reasoning items (the just-asked, now
    answered clarification) so a weak model can't copy it verbatim on the
    recovery turn. Stops at the first user / tool-pair boundary, so history
    and tool pairing are preserved. Returns True if anything was dropped.
    """
    items = await session.get_items()
    if not items:
        return False
    cut = len(items)
    while cut > 0 and not _is_boundary(items[cut - 1]):
        cut -= 1
    if cut == len(items):
        return False
    kept = items[:cut]
    await session.clear_session()
    await session.add_items(kept)
    logger.info(
        "Dropped %d trailing clarification item(s) for recovery turn",
        len(items) - cut,
    )
    return True


async def trim_session(session: Any, max_turns: int) -> None:
    """Bound stored history: keep the last `max_turns` user-turn boundaries
    AND elide oversized historical tool payloads. Rewrites the session only
    when it actually changes. Never raises through the caller's hot path.
    """
    if max_turns <= 0:
        return
    items = await session.get_items()
    user_idxs = [i for i, it in enumerate(items) if _is_user(it)]

    cut = 0
    if len(user_idxs) > max_turns:
        cut = user_idxs[-max_turns]
        items = items[cut:]

    items, evicted = _evict_tool_payloads(items, _TOOL_PAYLOAD_LIMIT)

    if cut == 0 and evicted == 0:
        return
    await session.clear_session()
    await session.add_items(items)
    logger.info(
        "Trimmed session: dropped %d oldest item(s), elided %d tool "
        "payload(s) (kept last %d turns)",
        cut,
        evicted,
        max_turns,
    )


def _delete_db_file(db: Path) -> None:
    for p in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        try:
            p.unlink(missing_ok=True)
        except OSError as e:
            logger.warning("Could not delete %s: %s", p, e)


def _sweep_stale(session_dir: str, ttl_days: int) -> int:
    base = Path(session_dir)
    if not base.exists():
        return 0
    cutoff = time.time() - ttl_days * 86400
    deleted = 0
    for db in base.glob("*.db"):
        try:
            if db.stat().st_mtime < cutoff:
                _delete_db_file(db)
                deleted += 1
        except OSError as e:
            logger.warning("Could not stat %s: %s", db, e)
    return deleted


async def cleanup_stale_sessions(session_dir: str, ttl_days: int) -> int:
    """Delete session DB files (and -wal/-shm) untouched for ttl_days."""
    return await asyncio.to_thread(_sweep_stale, session_dir, ttl_days)


# --------------------------------------------------------------------------- #
# Background task (mirrors utils/health.py heartbeat lifecycle)
# --------------------------------------------------------------------------- #

_cleanup_task: Optional[asyncio.Task] = None


async def run_cleanup_once() -> None:
    """One cleanup pass: stale session files + old budget rows."""
    from src.rules_lawyer_bot.config import settings
    from src.rules_lawyer_bot.utils.budget import budget_tracker

    try:
        n = await cleanup_stale_sessions(
            settings.session_db_dir, settings.session_ttl_days
        )
        if n:
            logger.info("Retention: deleted %d stale session DB(s)", n)
    except Exception:
        logger.exception("Retention: stale-session sweep failed")

    try:
        rows = await budget_tracker.prune()
        if rows:
            logger.info("Retention: pruned %d old budget row(s)", rows)
    except Exception:
        logger.exception("Retention: budget prune failed")


async def _cleanup_loop(interval: int) -> None:
    await run_cleanup_once()
    while True:
        try:
            await asyncio.sleep(interval)
            await run_cleanup_once()
        except asyncio.CancelledError:
            logger.debug("Cleanup loop cancelled")
            raise
        except Exception as e:
            logger.warning("Cleanup tick failed: %s", e)


def start_cleanup(interval: int) -> None:
    """Spawn the cleanup task. No-op when interval <= 0."""
    global _cleanup_task
    if interval <= 0:
        logger.info("Retention cleanup disabled (RETENTION_CLEANUP_INTERVAL_SECONDS=0)")
        return
    if _cleanup_task is not None and not _cleanup_task.done():
        return
    _cleanup_task = asyncio.create_task(
        _cleanup_loop(interval), name="retention-cleanup"
    )
    logger.info("✅ Retention cleanup every %ds", interval)


async def stop_cleanup() -> None:
    """Cancel and await the cleanup task (idempotent)."""
    global _cleanup_task
    if _cleanup_task is None:
        return
    _cleanup_task.cancel()
    try:
        await _cleanup_task
    except (asyncio.CancelledError, Exception):
        pass
    _cleanup_task = None
