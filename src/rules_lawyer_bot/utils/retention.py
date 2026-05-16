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


async def trim_session(session: Any, max_turns: int) -> None:
    """Keep only the last `max_turns` user-turn boundaries in `session`.

    Rewrites the session only when it actually exceeds the limit. Never
    raises through to the caller's hot path — wrap at the call site if a
    glitch must be swallowed; here we let real bugs surface in tests.
    """
    if max_turns <= 0:
        return
    items = await session.get_items()
    user_idxs = [i for i, it in enumerate(items) if _is_user(it)]
    if len(user_idxs) <= max_turns:
        return
    cut = user_idxs[-max_turns]
    kept = items[cut:]
    await session.clear_session()
    await session.add_items(kept)
    logger.info(
        "Trimmed session: dropped %d oldest items (kept last %d turns)",
        cut,
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
        logger.info(
            "Retention cleanup disabled "
            "(RETENTION_CLEANUP_INTERVAL_SECONDS=0)"
        )
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
