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
