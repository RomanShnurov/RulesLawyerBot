"""Tests for session trimming and stale-session cleanup."""

import time

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
        _u("q1"),
        _tool("big1"),
        _a("a1"),
        _u("q2"),
        _tool("big2"),
        _a("a2"),
        _u("q3"),
        _tool("big3"),
        _a("a3"),
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
    from src.rules_lawyer_bot.utils.budget import budget_tracker

    called = []

    async def _boom(*a, **k):
        called.append(True)
        raise RuntimeError("sweep down")

    async def _no_prune(*a, **k):
        return 0

    monkeypatch.setattr(retention, "cleanup_stale_sessions", _boom)
    monkeypatch.setattr(budget_tracker, "prune", _no_prune)
    # Must not raise even though the sweep blows up.
    await retention.run_cleanup_once()
    assert called  # the failing sweep path was actually exercised


def _fco(output: str):
    """OpenAI Agents SDK tool-result item shape (function_call_output)."""
    return {"type": "function_call_output", "call_id": "c1", "output": output}


@pytest.mark.asyncio
async def test_trim_elides_oversized_tool_payload():
    big = "x" * 5000
    items = [_u("q1"), _fco(big), _a("a1")]
    s = FakeSession(items)
    await trim_session(s, max_turns=20)
    kept = await s.get_items()
    assert s.clear_calls == 1
    assert kept[1]["type"] == "function_call_output"
    assert kept[1]["call_id"] == "c1"
    assert kept[1]["output"].startswith("<elided:")
    assert len(kept[1]["output"]) < 100
    assert kept[0] == _u("q1") and kept[-1] == _a("a1")


@pytest.mark.asyncio
async def test_trim_keeps_small_tool_payload_untouched():
    items = [_u("q1"), _tool("small result"), _a("a1")]
    s = FakeSession(items)
    await trim_session(s, max_turns=20)
    assert s.clear_calls == 0
    assert (await s.get_items())[1] == _tool("small result")


@pytest.mark.asyncio
async def test_drop_trailing_clarification_removes_last_assistant():
    from src.rules_lawyer_bot.utils.retention import drop_trailing_clarification

    items = [_u("q1"), _fco("tool out"), _a("clarify?")]
    s = FakeSession(items)
    dropped = await drop_trailing_clarification(s)
    kept = await s.get_items()
    assert dropped is True
    assert kept == [_u("q1"), _fco("tool out")]


@pytest.mark.asyncio
async def test_drop_trailing_clarification_noop_when_last_is_user():
    from src.rules_lawyer_bot.utils.retention import drop_trailing_clarification

    s = FakeSession([_a("a1"), _u("q2")])
    dropped = await drop_trailing_clarification(s)
    assert dropped is False
    assert s.clear_calls == 0


@pytest.mark.asyncio
async def test_drop_orphan_user_turn_when_unanswered():
    from src.rules_lawyer_bot.utils.retention import (
        drop_trailing_unanswered_user_turn,
    )

    # q1 answered (a1); q2 is a killed run: only the user turn persisted.
    s = FakeSession([_u("q1"), _a("a1"), _u("q2")])
    dropped = await drop_trailing_unanswered_user_turn(s)
    assert dropped is True
    assert await s.get_items() == [_u("q1"), _a("a1")]
    assert s.clear_calls == 1


@pytest.mark.asyncio
async def test_drop_orphan_user_turn_with_dangling_tool_calls():
    from src.rules_lawyer_bot.utils.retention import (
        drop_trailing_unanswered_user_turn,
    )

    # Killed run got as far as a tool call but never produced an answer.
    s = FakeSession([_u("q1"), _a("a1"), _u("q2"), _fco("partial tool out")])
    dropped = await drop_trailing_unanswered_user_turn(s)
    assert dropped is True
    assert await s.get_items() == [_u("q1"), _a("a1")]


@pytest.mark.asyncio
async def test_drop_orphan_noop_when_last_turn_answered():
    from src.rules_lawyer_bot.utils.retention import (
        drop_trailing_unanswered_user_turn,
    )

    s = FakeSession([_u("q1"), _fco("tool"), _a("a1")])
    dropped = await drop_trailing_unanswered_user_turn(s)
    assert dropped is False
    assert s.clear_calls == 0


@pytest.mark.asyncio
async def test_drop_orphan_noop_on_empty_session():
    from src.rules_lawyer_bot.utils.retention import (
        drop_trailing_unanswered_user_turn,
    )

    s = FakeSession([])
    dropped = await drop_trailing_unanswered_user_turn(s)
    assert dropped is False
    assert s.clear_calls == 0
