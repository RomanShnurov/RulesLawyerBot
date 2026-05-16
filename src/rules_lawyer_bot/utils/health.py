"""Health endpoint + heartbeat logger.

Exposes a small aiohttp `/health` endpoint that returns a JSON snapshot of
the bot's runtime state and runs an asyncio task that periodically logs
the same snapshot. Together they answer the question "is the bot alive?"
from two angles:

- HTTP endpoint — for Docker healthcheck, Uptime Kuma, k8s probes, etc.
- Periodic log line — for passive monitoring (Loki alerts, Langfuse
  presence, manual `tail -f`).

The endpoint always returns 200 if the process is responsive. A `status`
field in the body downgrades to "degraded" when the PDF library is empty,
so external monitors can alert on the body even when the HTTP code is OK.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Optional

from aiohttp import web

from src.rules_lawyer_bot.config import settings
from src.rules_lawyer_bot.utils.logger import logger


# Module-level state. A dict (not dataclass) because access happens from
# both the aiohttp request handler and the heartbeat task — keeping it
# small and read-mostly avoids any locking concern (GIL-protected dict
# writes are atomic for our simple fields).
_state: dict = {
    "started_at": 0.0,
    "last_update_at": None,   # Optional[float]
    "updates_total": 0,
}

_runner: Optional[web.AppRunner] = None
_heartbeat_task: Optional[asyncio.Task] = None


# --------------------------------------------------------------------------- #
# State mutation
# --------------------------------------------------------------------------- #


def init_state() -> None:
    """Record the process start time. Call once during startup."""
    _state["started_at"] = time.time()
    _state["last_update_at"] = None
    _state["updates_total"] = 0


def record_update() -> None:
    """Mark that a Telegram update was just received.

    Called by a `TypeHandler(Update, ...)` registered with the application.
    Cheap by design — used on the hot path.
    """
    _state["last_update_at"] = time.time()
    _state["updates_total"] += 1


# --------------------------------------------------------------------------- #
# Snapshot
# --------------------------------------------------------------------------- #


def get_snapshot() -> dict:
    """Return a self-contained dict describing current bot health."""
    now = time.time()
    started = _state["started_at"]
    last = _state["last_update_at"]

    pdf_dir = Path(settings.pdf_storage_path)
    if pdf_dir.exists():
        pdf_count = sum(1 for _ in pdf_dir.glob("*.pdf"))
    else:
        pdf_count = 0
    games_index_exists = (pdf_dir / "games_index.json").exists()

    status = "ok"
    if pdf_count == 0:
        status = "degraded"

    return {
        "status": status,
        "uptime_seconds": round(now - started, 1) if started else None,
        "last_update_age_seconds": round(now - last, 1) if last else None,
        "updates_total": _state["updates_total"],
        "library": {
            "pdf_count": pdf_count,
            "index_exists": games_index_exists,
        },
        "config": {
            "tracing_enabled": settings.tracing_enabled,
            "sentry_enabled": settings.sentry_enabled,
            "openai_model": settings.openai_model,
        },
    }


# --------------------------------------------------------------------------- #
# HTTP endpoint
# --------------------------------------------------------------------------- #


async def _health_handler(request: web.Request) -> web.Response:
    snap = get_snapshot()
    return web.json_response(snap, status=200)


async def start_health_server(host: str, port: int) -> None:
    """Start the aiohttp /health server on the current event loop.

    Failures (port in use, permission denied) are logged but do NOT crash
    the bot — health is a sidecar concern, not a critical path.
    """
    global _runner
    if port <= 0:
        logger.info("Health endpoint disabled (HEALTH_PORT=0)")
        return

    app = web.Application()
    app.router.add_get("/health", _health_handler)
    app.router.add_get("/", _health_handler)

    try:
        _runner = web.AppRunner(app, access_log=None)
        await _runner.setup()
        site = web.TCPSite(_runner, host=host, port=port)
        await site.start()
        logger.info(f"✅ Health endpoint listening on http://{host}:{port}/health")
    except Exception as e:
        logger.error(f"Failed to start health server on {host}:{port}: {e}")
        _runner = None


async def stop_health_server() -> None:
    """Tear down the health server (idempotent)."""
    global _runner
    if _runner is not None:
        try:
            await _runner.cleanup()
        except Exception as e:
            logger.warning(f"Error stopping health server: {e}")
        finally:
            _runner = None
            logger.info("Health endpoint stopped")


# --------------------------------------------------------------------------- #
# Heartbeat task
# --------------------------------------------------------------------------- #


def _format_heartbeat_line(snap: dict) -> str:
    last_age = snap["last_update_age_seconds"]
    last_str = f"{last_age:.0f}s" if last_age is not None else "never"
    return (
        f"heartbeat status={snap['status']} "
        f"uptime={snap['uptime_seconds']:.0f}s "
        f"last_update_age={last_str} "
        f"updates_total={snap['updates_total']} "
        f"pdfs={snap['library']['pdf_count']}"
    )


async def _heartbeat_loop(interval: int) -> None:
    """Log a single 'heartbeat ...' line every `interval` seconds."""
    while True:
        try:
            await asyncio.sleep(interval)
            logger.info(_format_heartbeat_line(get_snapshot()))
        except asyncio.CancelledError:
            logger.debug("Heartbeat loop cancelled")
            raise
        except Exception as e:
            # Don't let a logging glitch kill the heartbeat — log + keep going.
            logger.warning(f"Heartbeat tick failed: {e}")


def start_heartbeat(interval: int) -> None:
    """Spawn the heartbeat asyncio task. No-op when interval <= 0."""
    global _heartbeat_task
    if interval <= 0:
        logger.info("Heartbeat log disabled (HEARTBEAT_INTERVAL_SECONDS=0)")
        return
    if _heartbeat_task is not None and not _heartbeat_task.done():
        return
    _heartbeat_task = asyncio.create_task(
        _heartbeat_loop(interval), name="bot-heartbeat"
    )
    logger.info(f"✅ Heartbeat log every {interval}s")


async def stop_heartbeat() -> None:
    """Cancel and await the heartbeat task (idempotent)."""
    global _heartbeat_task
    if _heartbeat_task is None:
        return
    _heartbeat_task.cancel()
    try:
        await _heartbeat_task
    except (asyncio.CancelledError, Exception):
        pass
    _heartbeat_task = None
