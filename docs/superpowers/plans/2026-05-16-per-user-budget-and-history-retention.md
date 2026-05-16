# Per-User Budget and History Retention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent per-user budget (requests + tokens, daily + monthly, hard block) and bounded SQLite session history (inline last-N-turns trim + background TTL cleanup).

**Architecture:** Two independent SQLite-backed modules. `utils/budget.py` (`BudgetTracker`) keeps per-user request/token counters keyed by day and month; checked before the agent run, recorded after. `utils/retention.py` trims each user's `SQLiteSession` to the last N turns inline after the answer, and a background task deletes stale session DB files and prunes old budget rows. Integration is limited to `handlers/messages.py` and `main.py`. `utils/context_window.py` is untouched.

**Tech Stack:** Python 3.12, `sqlite3` (stdlib, sync calls wrapped in `asyncio.to_thread`), `pydantic-settings`, `pytest` + `pytest-asyncio`, OpenAI Agents SDK (`agents`), `uv`.

Spec: `docs/superpowers/specs/2026-05-16-per-user-budget-and-history-retention-design.md`

---

## File Structure

- **Create** `src/rules_lawyer_bot/utils/budget.py` — `BudgetDecision` dataclass, `BudgetTracker` class, module-level `budget_tracker` singleton. Owns all budget DB access. Fail-open built in.
- **Create** `src/rules_lawyer_bot/utils/retention.py` — `trim_session()`, `cleanup_stale_sessions()`, `run_cleanup_once()`, and the `start_cleanup()`/`stop_cleanup()` background-task pair (mirrors `utils/health.py` heartbeat).
- **Create** `tests/test_budget.py`, `tests/test_retention.py`.
- **Modify** `src/rules_lawyer_bot/config.py` — 8 new settings + `budget_db_path` property.
- **Modify** `src/rules_lawyer_bot/handlers/messages.py` — budget check (after rate limit, before blocklist), record (after successful run), trim (after answer).
- **Modify** `src/rules_lawyer_bot/main.py` — start/stop the cleanup task in `on_startup`/`on_shutdown`.
- **Modify** `.env.example` — document the 8 new env vars.

Notes for the engineer:
- Tests run with `uv run pytest`. Async tests need an explicit `@pytest.mark.asyncio` marker (this repo has no `asyncio_mode=auto`); see `tests/test_context_window.py`.
- `logger` is `from src.rules_lawyer_bot.utils.logger import logger`. The project relies on the Sentry logging integration, so `logger.exception(...)` / `logger.error(...)` is "log + Sentry" — no explicit `sentry_sdk` call needed (follow the `utils/health.py` pattern).
- Background-task lifecycle must mirror `utils/health.py` exactly (`start_heartbeat`/`stop_heartbeat`).

---

## Task 1: Configuration + .env.example

**Files:**
- Modify: `src/rules_lawyer_bot/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Add the 8 settings fields**

In `src/rules_lawyer_bot/config.py`, immediately after the `max_full_document_chars` field (ends at line 68, before the `# Logging` comment on line 70), insert:

```python
    # Per-user budget
    budget_enabled: bool = Field(
        default=True,
        description="Master switch for per-user request/token budget"
    )
    daily_request_limit: int = Field(
        default=50,
        description="Max successful requests per user per UTC day"
    )
    daily_token_limit: int = Field(
        default=300000,
        description="Max total tokens per user per UTC day"
    )
    monthly_request_limit: int = Field(
        default=1000,
        description="Max successful requests per user per UTC month"
    )
    monthly_token_limit: int = Field(
        default=6000000,
        description="Max total tokens per user per UTC month"
    )

    # Session history retention
    session_max_turns: int = Field(
        default=20,
        description=(
            "Keep only the last N user-turn boundaries in each user's "
            "SQLiteSession. Trimmed inline after every answer."
        )
    )
    session_ttl_days: int = Field(
        default=30,
        description=(
            "Delete a user's session DB file if untouched for this many "
            "days (privacy + disk)."
        )
    )
    retention_cleanup_interval_seconds: int = Field(
        default=86400,
        description=(
            "Interval for the background session/budget cleanup task. "
            "Runs once at startup, then every interval."
        )
    )
```

- [ ] **Step 2: Add the `budget_db_path` property**

In `src/rules_lawyer_bot/config.py`, immediately after the `session_db_dir` property (ends line 155), insert:

```python
    @property
    def budget_db_path(self) -> str:
        """Path to the single shared budget counters database."""
        return f"{self.data_path}/budget.db"
```

- [ ] **Step 3: Document the new env vars**

In `.env.example`, after line 21 (`ADMIN_USER_IDS=123456789`) and its blank line, insert:

```
# Per-user budget (BUDGET_ENABLED=false disables check + record entirely)
BUDGET_ENABLED=true
DAILY_REQUEST_LIMIT=50
DAILY_TOKEN_LIMIT=300000
MONTHLY_REQUEST_LIMIT=1000
MONTHLY_TOKEN_LIMIT=6000000

# Session history retention
SESSION_MAX_TURNS=20
SESSION_TTL_DAYS=30
RETENTION_CLEANUP_INTERVAL_SECONDS=86400
```

- [ ] **Step 4: Verify config imports cleanly**

Run: `uv run python -c "from src.rules_lawyer_bot.config import settings; print(settings.budget_db_path, settings.daily_request_limit, settings.session_max_turns)"`
Expected: prints a path ending in `/budget.db`, then `50 20`

- [ ] **Step 5: Commit**

```bash
git add src/rules_lawyer_bot/config.py .env.example
git commit -m "feat(config): add per-user budget and session retention settings"
```

---

## Task 2: BudgetTracker module

**Files:**
- Create: `src/rules_lawyer_bot/utils/budget.py`
- Test: `tests/test_budget.py`

Design contract:
- `BudgetDecision(allowed: bool, reason: str, retry_at: datetime | None)`.
- `BudgetTracker(db_path: str, *, daily_request_limit, daily_token_limit, monthly_request_limit, monthly_token_limit)`.
- `await tracker.check(user_id: int, *, now: datetime | None = None) -> BudgetDecision` — never raises (fail-open: on any DB error logs and returns `allowed=True`).
- `await tracker.record(user_id: int, total_tokens: int, *, now: datetime | None = None) -> None` — never raises (on DB error logs and returns).
- `await tracker.prune(*, now: datetime | None = None, daily_keep_days: int = 60, monthly_keep_months: int = 13) -> int` — deletes old period rows, returns rows deleted.
- `now` params exist only so tests can pin time deterministically; production calls pass nothing (defaults to `datetime.now(timezone.utc)`).

- [ ] **Step 1: Write failing tests**

Create `tests/test_budget.py`:

```python
"""Tests for the per-user budget tracker.

Counters are keyed by UTC day and month. check() must fail open on any
DB error so a counter glitch never blocks every user.
"""

from datetime import datetime, timezone

import pytest

from src.rules_lawyer_bot.utils.budget import BudgetDecision, BudgetTracker


def _tracker(tmp_path, **overrides) -> BudgetTracker:
    kwargs = dict(
        daily_request_limit=3,
        daily_token_limit=1000,
        monthly_request_limit=10,
        monthly_token_limit=5000,
    )
    kwargs.update(overrides)
    return BudgetTracker(str(tmp_path / "budget.db"), **kwargs)


_NOW = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_fresh_user_is_allowed(tmp_path):
    t = _tracker(tmp_path)
    d = await t.check(1, now=_NOW)
    assert isinstance(d, BudgetDecision)
    assert d.allowed is True


@pytest.mark.asyncio
async def test_record_then_check_counts_requests(tmp_path):
    t = _tracker(tmp_path)
    await t.record(1, 10, now=_NOW)
    await t.record(1, 10, now=_NOW)
    await t.record(1, 10, now=_NOW)
    d = await t.check(1, now=_NOW)
    assert d.allowed is False
    assert "запрос" in d.reason.lower()
    assert d.retry_at == datetime(2026, 5, 17, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_daily_token_limit_blocks_before_request_limit(tmp_path):
    t = _tracker(tmp_path)
    await t.record(1, 600, now=_NOW)
    await t.record(1, 600, now=_NOW)  # 1200 tokens, only 2 requests
    d = await t.check(1, now=_NOW)
    assert d.allowed is False
    assert "токен" in d.reason.lower()


@pytest.mark.asyncio
async def test_monthly_limit_blocks_with_daily_under(tmp_path):
    # daily limits high so only the monthly request cap can trip
    t = _tracker(tmp_path, daily_request_limit=1000, daily_token_limit=10**9)
    days = [datetime(2026, 5, d, 12, 0, tzinfo=timezone.utc) for d in range(1, 12)]
    for day in days:
        await t.record(1, 1, now=day)
    d = await t.check(1, now=datetime(2026, 5, 15, 9, 0, tzinfo=timezone.utc))
    assert d.allowed is False
    assert d.retry_at == datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_day_rollover_resets_daily_counter(tmp_path):
    t = _tracker(tmp_path)
    for _ in range(3):
        await t.record(1, 10, now=_NOW)
    assert (await t.check(1, now=_NOW)).allowed is False
    next_day = datetime(2026, 5, 17, 8, 0, tzinfo=timezone.utc)
    assert (await t.check(1, now=next_day)).allowed is True


@pytest.mark.asyncio
async def test_check_fails_open_on_db_error(tmp_path, monkeypatch):
    t = _tracker(tmp_path)

    def _boom(*a, **k):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(t, "_read_counters", _boom)
    d = await t.check(1, now=_NOW)
    assert d.allowed is True


@pytest.mark.asyncio
async def test_prune_deletes_old_rows(tmp_path):
    t = _tracker(tmp_path)
    old = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    await t.record(1, 10, now=old)
    deleted = await t.prune(now=_NOW, daily_keep_days=60, monthly_keep_months=13)
    assert deleted >= 1
    # A brand-new check after prune is unaffected.
    assert (await t.check(1, now=_NOW)).allowed is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_budget.py -v`
Expected: collection/import error — `ModuleNotFoundError: No module named 'src.rules_lawyer_bot.utils.budget'`

- [ ] **Step 3: Implement `budget.py`**

Create `src/rules_lawyer_bot/utils/budget.py`:

```python
"""Persistent per-user budget: request + token counters, day + month windows.

Single SQLite file (single-instance deployment). All sync sqlite3 work runs
in asyncio.to_thread. check() and record() never raise — a counter-store
glitch must not block every user (fail-open); the in-memory rate limiter
still bounds spam.
"""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.rules_lawyer_bot.utils.logger import logger

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_counters (
    user_id    INTEGER NOT NULL,
    period_key TEXT    NOT NULL,
    requests   INTEGER NOT NULL DEFAULT 0,
    tokens     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, period_key)
);
"""


@dataclass
class BudgetDecision:
    allowed: bool
    reason: str
    retry_at: datetime | None


def _day_key(now: datetime) -> str:
    return f"d:{now:%Y-%m-%d}"


def _month_key(now: datetime) -> str:
    return f"m:{now:%Y-%m}"


def _next_utc_midnight(now: datetime) -> datetime:
    nxt = (now + timedelta(days=1)).date()
    return datetime(nxt.year, nxt.month, nxt.day, tzinfo=timezone.utc)


def _first_of_next_month(now: datetime) -> datetime:
    if now.month == 12:
        return datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)


class BudgetTracker:
    def __init__(
        self,
        db_path: str,
        *,
        daily_request_limit: int,
        daily_token_limit: int,
        monthly_request_limit: int,
        monthly_token_limit: int,
    ) -> None:
        self._db_path = db_path
        self._daily_req = daily_request_limit
        self._daily_tok = daily_token_limit
        self._monthly_req = monthly_request_limit
        self._monthly_tok = monthly_token_limit

    def _connect(self) -> sqlite3.Connection:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(_SCHEMA)
        return conn

    def _read_counters(self, user_id: int, day_key: str, month_key: str) -> dict:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT period_key, requests, tokens FROM usage_counters "
                "WHERE user_id = ? AND period_key IN (?, ?)",
                (user_id, day_key, month_key),
            ).fetchall()
        finally:
            conn.close()
        out = {day_key: (0, 0), month_key: (0, 0)}
        for pk, req, tok in rows:
            out[pk] = (req, tok)
        return out

    def _write_counters(
        self, user_id: int, day_key: str, month_key: str, tokens: int
    ) -> None:
        conn = self._connect()
        try:
            conn.executemany(
                "INSERT INTO usage_counters(user_id, period_key, requests, tokens) "
                "VALUES (?, ?, 1, ?) "
                "ON CONFLICT(user_id, period_key) DO UPDATE SET "
                "requests = requests + 1, tokens = tokens + excluded.tokens",
                [(user_id, day_key, tokens), (user_id, month_key, tokens)],
            )
            conn.commit()
        finally:
            conn.close()

    def _prune(self, day_cutoff: str, month_cutoff: str) -> int:
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM usage_counters "
                "WHERE (period_key LIKE 'd:%' AND period_key < ?) "
                "   OR (period_key LIKE 'm:%' AND period_key < ?)",
                (f"d:{day_cutoff}", f"m:{month_cutoff}"),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    async def check(
        self, user_id: int, *, now: datetime | None = None
    ) -> BudgetDecision:
        now = now or datetime.now(timezone.utc)
        dk, mk = _day_key(now), _month_key(now)
        try:
            counters = await asyncio.to_thread(
                self._read_counters, user_id, dk, mk
            )
        except Exception:
            logger.exception(
                "budget.check failed for user %s; failing open", user_id
            )
            return BudgetDecision(True, "", None)

        d_req, d_tok = counters[dk]
        m_req, m_tok = counters[mk]

        if d_req >= self._daily_req:
            return BudgetDecision(
                False,
                f"Дневной лимит запросов исчерпан ({self._daily_req}).",
                _next_utc_midnight(now),
            )
        if d_tok >= self._daily_tok:
            return BudgetDecision(
                False,
                f"Дневной лимит токенов исчерпан ({self._daily_tok}).",
                _next_utc_midnight(now),
            )
        if m_req >= self._monthly_req:
            return BudgetDecision(
                False,
                f"Месячный лимит запросов исчерпан ({self._monthly_req}).",
                _first_of_next_month(now),
            )
        if m_tok >= self._monthly_tok:
            return BudgetDecision(
                False,
                f"Месячный лимит токенов исчерпан ({self._monthly_tok}).",
                _first_of_next_month(now),
            )
        return BudgetDecision(True, "", None)

    async def record(
        self, user_id: int, total_tokens: int, *, now: datetime | None = None
    ) -> None:
        now = now or datetime.now(timezone.utc)
        try:
            await asyncio.to_thread(
                self._write_counters,
                user_id,
                _day_key(now),
                _month_key(now),
                max(0, int(total_tokens)),
            )
        except Exception:
            logger.exception(
                "budget.record failed for user %s (tokens=%s)",
                user_id,
                total_tokens,
            )

    async def prune(
        self,
        *,
        now: datetime | None = None,
        daily_keep_days: int = 60,
        monthly_keep_months: int = 13,
    ) -> int:
        now = now or datetime.now(timezone.utc)
        day_cutoff = (now - timedelta(days=daily_keep_days)).strftime("%Y-%m-%d")
        months_back = now.year * 12 + (now.month - 1) - monthly_keep_months
        month_cutoff = f"{months_back // 12:04d}-{months_back % 12 + 1:02d}"
        try:
            return await asyncio.to_thread(
                self._prune, day_cutoff, month_cutoff
            )
        except Exception:
            logger.exception("budget.prune failed")
            return 0


from src.rules_lawyer_bot.config import settings

budget_tracker = BudgetTracker(
    settings.budget_db_path,
    daily_request_limit=settings.daily_request_limit,
    daily_token_limit=settings.daily_token_limit,
    monthly_request_limit=settings.monthly_request_limit,
    monthly_token_limit=settings.monthly_token_limit,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_budget.py -v`
Expected: PASS — all 7 tests green

- [ ] **Step 5: Type-check**

Run: `uv run mypy src/rules_lawyer_bot/utils/budget.py`
Expected: `Success: no issues found` (or no errors for this file)

- [ ] **Step 6: Commit**

```bash
git add src/rules_lawyer_bot/utils/budget.py tests/test_budget.py
git commit -m "feat(budget): persistent per-user request/token budget tracker"
```

---

## Task 3: Session trim (retention, part 1)

**Files:**
- Create: `src/rules_lawyer_bot/utils/retention.py`
- Test: `tests/test_retention.py`

`trim_session(session, max_turns)` cuts session history to the last `max_turns`
user-turn boundaries. It only ever cuts at a `role == "user"` item, so a
`tool_output` is never orphaned from its `tool_call` (same boundary rule as
`utils/context_window.py`). It rewrites the session only when actually over the
limit.

- [ ] **Step 1: Write failing tests**

Create `tests/test_retention.py`:

```python
"""Tests for session trimming and stale-session cleanup."""

import time
from pathlib import Path

import pytest

from src.rules_lawyer_bot.utils.retention import (
    cleanup_stale_sessions,
    trim_session,
)


class FakeSession:
    """Duck-typed stand-in for agents.SQLiteSession."""

    def __init__(self, items):
        self._items = list(items)
        self.clear_calls = 0

    async def get_items(self, limit=None):
        return list(self._items)

    async def clear_session(self):
        self.clear_calls += 1
        self._items = []

    async def add_items(self, items):
        self._items.extend(items)


def _u(t):
    return {"role": "user", "content": t}


def _a(t):
    return {"role": "assistant", "content": t}


def _tool(t):
    return {"role": "tool", "content": t}


@pytest.mark.asyncio
async def test_trim_keeps_last_n_turns_at_user_boundary():
    items = [
        _u("q1"), _tool("big1"), _a("a1"),
        _u("q2"), _tool("big2"), _a("a2"),
        _u("q3"), _tool("big3"), _a("a3"),
    ]
    s = FakeSession(items)
    await trim_session(s, max_turns=2)
    kept = await s.get_items()
    assert kept[0] == _u("q2")
    assert kept[-1] == _a("a3")
    assert s.clear_calls == 1


@pytest.mark.asyncio
async def test_trim_no_rewrite_when_under_limit():
    s = FakeSession([_u("q1"), _a("a1"), _u("q2"), _a("a2")])
    await trim_session(s, max_turns=5)
    assert s.clear_calls == 0
    assert len(await s.get_items()) == 4


@pytest.mark.asyncio
async def test_trim_empty_session_is_noop():
    s = FakeSession([])
    await trim_session(s, max_turns=3)
    assert s.clear_calls == 0


@pytest.mark.asyncio
async def test_trim_no_user_items_is_noop():
    s = FakeSession([_tool("x"), _a("y")])
    await trim_session(s, max_turns=1)
    assert s.clear_calls == 0


@pytest.mark.asyncio
async def test_cleanup_deletes_stale_db_and_sidecars(tmp_path):
    sess = tmp_path / "sessions"
    sess.mkdir()
    old = sess / "111.db"
    old.write_text("x")
    (sess / "111.db-wal").write_text("w")
    (sess / "111.db-shm").write_text("s")
    fresh = sess / "222.db"
    fresh.write_text("y")

    old_ts = time.time() - 40 * 86400
    import os
    os.utime(old, (old_ts, old_ts))

    deleted = await cleanup_stale_sessions(str(sess), ttl_days=30)

    assert deleted == 1
    assert not old.exists()
    assert not (sess / "111.db-wal").exists()
    assert not (sess / "111.db-shm").exists()
    assert fresh.exists()


@pytest.mark.asyncio
async def test_cleanup_missing_dir_is_noop(tmp_path):
    deleted = await cleanup_stale_sessions(str(tmp_path / "nope"), ttl_days=30)
    assert deleted == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_retention.py -v`
Expected: `ModuleNotFoundError: No module named 'src.rules_lawyer_bot.utils.retention'`

- [ ] **Step 3: Implement `retention.py` (trim + cleanup; task task uses both)**

Create `src/rules_lawyer_bot/utils/retention.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_retention.py -v`
Expected: PASS — all 6 tests green

- [ ] **Step 5: Type-check**

Run: `uv run mypy src/rules_lawyer_bot/utils/retention.py`
Expected: no errors for this file

- [ ] **Step 6: Commit**

```bash
git add src/rules_lawyer_bot/utils/retention.py tests/test_retention.py
git commit -m "feat(retention): session trim + stale-session/budget cleanup task"
```

---

## Task 4: Background cleanup task test

**Files:**
- Test: `tests/test_retention.py` (append)

Verify `start_cleanup`/`stop_cleanup` lifecycle and that `run_cleanup_once`
swallows failures.

- [ ] **Step 1: Append failing tests**

Add to the end of `tests/test_retention.py`:

```python
@pytest.mark.asyncio
async def test_start_cleanup_zero_interval_is_noop():
    from src.rules_lawyer_bot.utils import retention

    retention.start_cleanup(0)
    assert retention._cleanup_task is None


@pytest.mark.asyncio
async def test_start_then_stop_cleanup_task():
    import asyncio

    from src.rules_lawyer_bot.utils import retention

    retention.start_cleanup(3600)
    assert retention._cleanup_task is not None
    await asyncio.sleep(0)  # let the task start
    await retention.stop_cleanup()
    assert retention._cleanup_task is None


@pytest.mark.asyncio
async def test_run_cleanup_once_swallows_errors(monkeypatch):
    from src.rules_lawyer_bot.utils import retention

    async def _boom(*a, **k):
        raise RuntimeError("sweep down")

    monkeypatch.setattr(retention, "cleanup_stale_sessions", _boom)
    # Must not raise even though the sweep blows up.
    await retention.run_cleanup_once()
```

- [ ] **Step 2: Run the new tests**

Run: `uv run pytest tests/test_retention.py -v -k "cleanup_task or zero_interval or swallows"`
Expected: PASS — 3 tests green (implementation from Task 3 already satisfies them)

- [ ] **Step 3: Commit**

```bash
git add tests/test_retention.py
git commit -m "test(retention): background cleanup task lifecycle + error safety"
```

---

## Task 5: Wire budget check + record into the message handler

**Files:**
- Modify: `src/rules_lawyer_bot/handlers/messages.py`
- Test: `tests/test_messages_budget.py` (create)

Integration points (line numbers from the current file):
- Imports: alongside the existing `from src.rules_lawyer_bot.config import settings` (line 27).
- **Budget check:** after the rate-limit block (lines 184–187), before the blocklist block (line 190).
- **Budget record:** in `_process_message`, immediately after the `except _RETRIABLE_ERRORS` block ends (line 252) and before the `# Replay progress events` comment (line 254) — at that point `result` is a successful run.

- [ ] **Step 1: Write the failing test**

Create `tests/test_messages_budget.py`:

```python
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
         patch.object(messages.settings, "admin_ids", []), \
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
         patch.object(messages.settings, "admin_ids", [42]), \
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_messages_budget.py -v`
Expected: FAIL — `AttributeError: <module 'messages'> has no attribute 'budget_tracker'`

- [ ] **Step 3: Add the import**

In `src/rules_lawyer_bot/handlers/messages.py`, after line 27 (`from src.rules_lawyer_bot.config import settings`), add:

```python
from src.rules_lawyer_bot.utils.budget import budget_tracker
from src.rules_lawyer_bot.utils.retention import trim_session
```

- [ ] **Step 4: Insert the budget check after the rate-limit block**

In `src/rules_lawyer_bot/handlers/messages.py`, find the rate-limit block:

```python
    # Check rate limit (outside trace to avoid unnecessary spans)
    allowed, rate_limit_msg = await rate_limiter.check_rate_limit(user.id)
    if not allowed:
        await update.message.reply_text(f"⏳ {rate_limit_msg}")
        return
```

Immediately after it (before the `# Check blocklist patterns` comment), insert:

```python
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
```

- [ ] **Step 5: Insert the budget record after a successful run**

In `src/rules_lawyer_bot/handlers/messages.py`, find the end of the retry-exhausted handler inside `_process_message`:

```python
            except _RETRIABLE_ERRORS as e:
                # With tenacity reraise=True, the last retriable error
                # propagates here after attempts are exhausted.
                logger.warning(
                    f"Retry exhausted for user {user.id}: {type(e).__name__}"
                )
                await progress.finalize()
                await update.message.reply_text(RETRY_EXHAUSTED_RESPONSE)
                return RETRY_EXHAUSTED_RESPONSE
```

Immediately after that block (before the `# Replay progress events from completed stream` comment), insert:

```python
            # Record budget usage for the completed run (admins exempt).
            if settings.budget_enabled and user.id not in settings.admin_ids:
                usage = getattr(
                    getattr(result, "context_wrapper", None), "usage", None
                )
                total_tokens = getattr(usage, "total_tokens", 0) or 0
                await budget_tracker.record(user.id, total_tokens)
```

- [ ] **Step 6: Run the budget integration tests**

Run: `uv run pytest tests/test_messages_budget.py -v`
Expected: PASS — 2 tests green

- [ ] **Step 7: Run the full suite to check no regression**

Run: `uv run pytest -v`
Expected: PASS — all tests green (existing + new)

- [ ] **Step 8: Commit**

```bash
git add src/rules_lawyer_bot/handlers/messages.py tests/test_messages_budget.py
git commit -m "feat(messages): enforce per-user budget around the agent run"
```

---

## Task 6: Wire inline session trim into the message handler

**Files:**
- Modify: `src/rules_lawyer_bot/handlers/messages.py`
- Test: `tests/test_messages_budget.py` (append)

The trim must run after the answer is sent, on every branch (pipeline output,
fallback, error), and never break the response. The inner `try` in
`_process_message` (starts ~line 223 `try:`, `except Exception` ~line 339) is
the right scope: add a `finally` that trims the session. Guard with a
pre-initialised `session = None` so the `finally` is safe if
`get_user_session` failed.

- [ ] **Step 1: Append the failing test**

Add to the end of `tests/test_messages_budget.py`:

```python
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
         patch.object(messages.settings, "admin_ids", []), \
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
async def test_trim_failure_does_not_break_response():
    from src.rules_lawyer_bot.handlers import messages

    upd, ctx = _update(), _context()
    fake_session = MagicMock()
    result = MagicMock()
    result.final_output = None
    result.new_items = []

    with patch.object(messages.settings, "budget_enabled", False), \
         patch.object(messages.settings, "admin_ids", []), \
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_messages_budget.py -v -k "trimmed_after_answer or trim_failure"`
Expected: FAIL — `trim_mock.assert_awaited_once_with` not satisfied (trim not called yet)

- [ ] **Step 3: Pre-initialise `session` and add the trimming `finally`**

In `src/rules_lawyer_bot/handlers/messages.py`, inside `_process_message`, find:

```python
        try:
            # Get user-specific session
            logger.debug(f"[Perf] Getting session for user {user.id}")
            session = get_user_session(user.id)
            logger.debug("[Perf] Session loaded, starting agent run")
```

Replace the `try:` line and the lines up to the session assignment with a guarded form:

```python
        session = None
        try:
            # Get user-specific session
            logger.debug(f"[Perf] Getting session for user {user.id}")
            session = get_user_session(user.id)
            logger.debug("[Perf] Session loaded, starting agent run")
```

Then find the matching `except Exception as e:` block that ends `_process_message`'s main try:

```python
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
```

Immediately after that `except Exception` block, add a `finally` at the same indentation:

```python
        finally:
            # Bound stored history after the answer is sent. Never let a
            # trim glitch break the user's response or the trace.
            if session is not None:
                try:
                    await trim_session(session, settings.session_max_turns)
                except Exception:
                    logger.exception("trim_session failed")
```

- [ ] **Step 4: Run the trim tests**

Run: `uv run pytest tests/test_messages_budget.py -v -k "trimmed_after_answer or trim_failure"`
Expected: PASS — 2 tests green

- [ ] **Step 5: Full suite regression check**

Run: `uv run pytest -v`
Expected: PASS — all tests green

- [ ] **Step 6: Commit**

```bash
git add src/rules_lawyer_bot/handlers/messages.py tests/test_messages_budget.py
git commit -m "feat(messages): trim session history after every answer"
```

---

## Task 7: Start/stop the cleanup task in main.py

**Files:**
- Modify: `src/rules_lawyer_bot/main.py`

Mirror the existing `health.start_heartbeat` / `health.stop_heartbeat` wiring
inside `on_startup` / `on_shutdown`.

- [ ] **Step 1: Add the retention import**

In `src/rules_lawyer_bot/main.py`, line 26 currently:

```python
from src.rules_lawyer_bot.utils import health
```

Change it to:

```python
from src.rules_lawyer_bot.utils import health, retention
```

- [ ] **Step 2: Start the cleanup task in `on_startup`**

In `src/rules_lawyer_bot/main.py`, find:

```python
    async def on_startup(app: Application) -> None:
        await health.start_health_server(settings.health_host, settings.health_port)
        health.start_heartbeat(settings.heartbeat_interval_seconds)
```

Add one line so it becomes:

```python
    async def on_startup(app: Application) -> None:
        await health.start_health_server(settings.health_host, settings.health_port)
        health.start_heartbeat(settings.heartbeat_interval_seconds)
        retention.start_cleanup(settings.retention_cleanup_interval_seconds)
```

- [ ] **Step 3: Stop the cleanup task in `on_shutdown`**

In `src/rules_lawyer_bot/main.py`, find:

```python
    async def on_shutdown(app: Application) -> None:
        await health.stop_heartbeat()
        await health.stop_health_server()
```

Add one line so it becomes:

```python
    async def on_shutdown(app: Application) -> None:
        await retention.stop_cleanup()
        await health.stop_heartbeat()
        await health.stop_health_server()
```

- [ ] **Step 4: Verify the module imports and wiring**

Run: `uv run python -c "import src.rules_lawyer_bot.main as m; import inspect; src=inspect.getsource(m); assert 'retention.start_cleanup' in src and 'retention.stop_cleanup' in src; print('wired ok')"`
Expected: prints `wired ok`

- [ ] **Step 5: Full suite + type-check**

Run: `uv run pytest -v && uv run mypy src/rules_lawyer_bot/utils/budget.py src/rules_lawyer_bot/utils/retention.py`
Expected: all tests PASS; mypy reports no errors for the two files

- [ ] **Step 6: Commit**

```bash
git add src/rules_lawyer_bot/main.py
git commit -m "feat(main): run the retention cleanup task over the bot lifecycle"
```

---

## Task 8: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Full test suite**

Run: `uv run pytest -v`
Expected: every test passes, including `tests/test_budget.py`, `tests/test_retention.py`, `tests/test_messages_budget.py`, and the pre-existing `tests/test_context_window.py`.

- [ ] **Step 2: Spec coverage walk-through**

Confirm against `docs/superpowers/specs/2026-05-16-per-user-budget-and-history-retention-design.md`:
- Budget: requests + tokens, day + month, hard block w/ retry time → Task 2 + Task 5.
- Admin exemption (no check, no record) → Task 5 Steps 4–5.
- Fail-open on DB error → Task 2 Step 3 (`check` try/except) + test.
- Inline last-N-turns trim at user boundary → Task 3 + Task 6.
- Background TTL cleanup of session files + budget prune → Task 3 + Task 4 + Task 7.
- Config/env vars → Task 1.
- `context_window.py` untouched → confirm `git diff --stat` lists no change to that file.

- [ ] **Step 3: Confirm no unintended files changed**

Run: `git diff --stat origin/master -- src/rules_lawyer_bot/utils/context_window.py`
Expected: empty output (file unchanged)

---

## Self-Review (completed by plan author)

- **Spec coverage:** every spec section maps to a task (see Task 8 Step 2). No gaps.
- **Placeholder scan:** no TBD/TODO; every code step contains full code; every command has expected output.
- **Type consistency:** `BudgetDecision(allowed, reason, retry_at)`, `BudgetTracker.check/record/prune`, `budget_tracker` singleton, `trim_session(session, max_turns)`, `cleanup_stale_sessions(session_dir, ttl_days)`, `start_cleanup(interval)`/`stop_cleanup()` — names and signatures are consistent across Tasks 2–8 and the handler/main integration.
- **Fail-open location:** centralised inside `BudgetTracker.check` (Task 2) so the handler stays simple and the behaviour is unit-testable (Task 2 test `test_check_fails_open_on_db_error`).
