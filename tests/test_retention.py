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
