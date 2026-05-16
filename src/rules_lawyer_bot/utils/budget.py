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
