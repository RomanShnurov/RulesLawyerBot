# Inactivity Watchdog + In-Flight Lock + Orphan Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a stalled OpenRouter/proxy stream actually abortable, prevent concurrent agent runs on one user's session, and stop a killed run's orphaned user turn from poisoning the next run.

**Architecture:** `Runner.run_streamed` runs the model in a *detached* SDK task; `RunResultStreaming.stream_events()` swallows a consumer `CancelledError` and then awaits that frozen detached task in its `finally` — so any `asyncio.wait_for` around the drain can never fire. Fix: drain in our own task, watched by an external inactivity + absolute-ceiling loop that calls `result.cancel("immediate")` (synchronous producer kill) and then **abandons** the drain task instead of awaiting it. A low httpx read-timeout reaps any zombie. A per-user `asyncio.Lock` drops concurrent messages; a retention helper removes orphaned trailing user turns.

**Tech Stack:** Python 3.13, openai-agents 0.6.1, httpx 0.28, tenacity, pytest + pytest-asyncio, ruff, pyrefly.

**Spec:** `docs/superpowers/specs/2026-05-17-inactivity-watchdog-design.md`

---

### Task 1: Config knob `agent_stream_inactivity_timeout_seconds`

**Files:**
- Modify: `src/rules_lawyer_bot/config.py` (the `agent_run_timeout_seconds` Field block, ~lines 56-65)
- Test: `tests/test_pipeline_resilience.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline_resilience.py`:

```python
def test_inactivity_timeout_default_and_below_ceiling():
    """The per-stream-event inactivity budget exists, defaults to 45s,
    and is strictly below the absolute wall-clock ceiling."""
    from src.rules_lawyer_bot.config import settings

    assert settings.agent_stream_inactivity_timeout_seconds == 45
    assert (
        settings.agent_stream_inactivity_timeout_seconds
        < settings.agent_run_timeout_seconds
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_resilience.py::test_inactivity_timeout_default_and_below_ceiling -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'agent_stream_inactivity_timeout_seconds'`

- [ ] **Step 3: Add the config field and update the ceiling docstring**

In `src/rules_lawyer_bot/config.py`, replace the existing `agent_run_timeout_seconds` Field block:

```python
    agent_run_timeout_seconds: int = Field(
        default=120,
        description=(
            "Hard wall-clock cap on a single agent run (all internal "
            "retries included). A stalled model/proxy stream raises no "
            "retriable error, so without this deadline the request hangs "
            "and — with sequential update dispatch — freezes the bot. On "
            "timeout the user gets a message and the handler returns."
        ),
    )
```

with:

```python
    agent_run_timeout_seconds: int = Field(
        default=120,
        description=(
            "Absolute wall-clock ceiling on a single agent run (all "
            "internal retries included), enforced by the drain watchdog "
            "in handlers/messages.py (NOT via asyncio.wait_for, which the "
            "Agents SDK neutralizes — see docs/superpowers/specs/"
            "2026-05-17-inactivity-watchdog-design.md). On breach the run "
            "is cancelled and abandoned and the user gets a message."
        ),
    )
    agent_stream_inactivity_timeout_seconds: int = Field(
        default=45,
        description=(
            "Max seconds allowed between two consecutive Agents SDK "
            "stream events before the run is declared stalled. Detects "
            "the real failure mode (a frozen proxy stream that delivers "
            "no semantic progress) far sooner than the absolute ceiling. "
            "Must be < agent_run_timeout_seconds. Also used as the httpx "
            "read-timeout backstop on the AsyncOpenAI client."
        ),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline_resilience.py::test_inactivity_timeout_default_and_below_ceiling -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/rules_lawyer_bot/config.py tests/test_pipeline_resilience.py
git commit -m "feat(config): add agent_stream_inactivity_timeout_seconds knob"
```

---

### Task 2: `retention.drop_trailing_unanswered_user_turn`

**Files:**
- Modify: `src/rules_lawyer_bot/utils/retention.py` (add helper after `drop_trailing_clarification`, ~line 100)
- Test: `tests/test_retention.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_retention.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_retention.py -k drop_orphan -v`
Expected: FAIL — `ImportError: cannot import name 'drop_trailing_unanswered_user_turn'`

- [ ] **Step 3: Implement the helper**

In `src/rules_lawyer_bot/utils/retention.py`, add immediately after the
`drop_trailing_clarification` function (after its `return True` at ~line 100):

```python
def _is_assistant_message(item: Any) -> bool:
    """An assistant answer item (the SDK persists the final structured
    output as an assistant message). Used to decide whether the last user
    turn was actually answered."""
    if not isinstance(item, dict):
        return False
    if item.get("role") == "assistant":
        return True
    if item.get("type") == "message" and item.get("role") in (None, "assistant"):
        return True
    return False


async def drop_trailing_unanswered_user_turn(session: Any) -> bool:
    """Remove a killed/aborted run's orphaned trailing user turn.

    Runner.run_streamed persists the user input immediately
    (_save_result_to_session, run.py:1059) and the assistant answer only
    at the end. A run killed in between leaves a user turn (optionally
    followed by dangling tool calls) with no assistant answer after it.
    That stale turn confuses the next run, so drop everything from the
    start of the last user turn onward. A normally-completed turn always
    ends with an assistant message, so this is a no-op at rest.

    Returns True if anything was dropped.
    """
    items = await session.get_items()
    if not items:
        return False
    last_user = None
    for i in range(len(items) - 1, -1, -1):
        if _is_user(items[i]):
            last_user = i
            break
    if last_user is None:
        return False
    if any(_is_assistant_message(it) for it in items[last_user + 1 :]):
        return False
    cut = last_user
    while cut > 0 and _is_user(items[cut - 1]):
        cut -= 1
    kept = items[:cut]
    await session.clear_session()
    await session.add_items(kept)
    logger.info(
        "Dropped %d orphaned item(s) from a killed/un-answered run",
        len(items) - cut,
    )
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_retention.py -k drop_orphan -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the full retention suite for regressions**

Run: `uv run pytest tests/test_retention.py -v`
Expected: PASS (all, including pre-existing `drop_trailing_clarification` tests)

- [ ] **Step 6: Commit**

```bash
git add src/rules_lawyer_bot/utils/retention.py tests/test_retention.py
git commit -m "feat(retention): drop_trailing_unanswered_user_turn for killed runs"
```

---

### Task 3: Watchdog drain (cancel + abandon) in `_run_agent_with_retry`

**Files:**
- Modify: `src/rules_lawyer_bot/handlers/messages.py` (replace `_run_agent_with_retry`, ~lines 223-277; add helpers/constants above it)
- Test: `tests/test_pipeline_resilience.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline_resilience.py`:

```python
@pytest.mark.asyncio
async def test_inactivity_watchdog_aborts_frozen_stream(monkeypatch):
    """A stream that emits nothing is aborted at the INACTIVITY budget,
    well before the absolute ceiling, and TimeoutError is not retried."""
    monkeypatch.setattr(
        messages_module.settings, "agent_stream_inactivity_timeout_seconds", 0.05
    )
    monkeypatch.setattr(
        messages_module.settings, "agent_run_timeout_seconds", 60
    )
    call_count = {"n": 0}

    def _frozen(*_a, **_k):
        call_count["n"] += 1
        result = MagicMock()

        async def _stream():
            await asyncio.sleep(30)  # never emits an event
            return
            yield

        result.stream_events = _stream
        return result

    loop = asyncio.get_running_loop()
    t0 = loop.time()
    with patch("src.rules_lawyer_bot.handlers.messages.Runner") as MockRunner:
        MockRunner.run_streamed.side_effect = _frozen
        with pytest.raises(TimeoutError):
            await _run_agent_with_retry(
                agent=MagicMock(), agent_input="q", session=MagicMock()
            )
    assert call_count["n"] == 1                 # not retried
    assert loop.time() - t0 < 5                 # bounded by inactivity, not 60s


@pytest.mark.asyncio
async def test_watchdog_abandons_uncancellable_drain(monkeypatch):
    """If the drain ignores cancellation past the grace, we still return
    promptly (abandon the zombie) instead of hanging."""
    monkeypatch.setattr(
        messages_module.settings, "agent_stream_inactivity_timeout_seconds", 0.05
    )
    monkeypatch.setattr(
        messages_module.settings, "agent_run_timeout_seconds", 60
    )
    monkeypatch.setattr(
        messages_module, "_ABANDON_GRACE_SECONDS", 0.05
    )

    def _shielded(*_a, **_k):
        result = MagicMock()

        async def _stream():
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                await asyncio.shield(asyncio.sleep(30))  # ignores cancel
            return
            yield

        result.stream_events = _stream
        return result

    loop = asyncio.get_running_loop()
    t0 = loop.time()
    with patch("src.rules_lawyer_bot.handlers.messages.Runner") as MockRunner:
        MockRunner.run_streamed.side_effect = _shielded
        with pytest.raises(TimeoutError):
            await _run_agent_with_retry(
                agent=MagicMock(), agent_input="q", session=MagicMock()
            )
    assert loop.time() - t0 < 5  # did not block on the uncancellable drain
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pipeline_resilience.py -k "inactivity_watchdog or abandons_uncancellable" -v`
Expected: FAIL — `test_inactivity_watchdog_aborts_frozen_stream` hangs/exceeds because the current single `asyncio.wait_for` uses `agent_run_timeout_seconds` (60s) only; `test_watchdog_abandons_uncancellable_drain` errors with `AttributeError: ... '_ABANDON_GRACE_SECONDS'`.

- [ ] **Step 3: Add helpers + constants and rewrite the function**

In `src/rules_lawyer_bot/handlers/messages.py`, add `import contextlib`
to the stdlib imports (next to `import asyncio`):

```python
import asyncio
import contextlib
```

Add these module-level definitions immediately ABOVE
`async def _run_agent_with_retry` (after the `_RETRY_WAIT = ...` line, ~line 131):

```python
# Grace given to a cancelled drain task to unwind after
# result.cancel("immediate") before we ABANDON it. The SDK's
# stream_events() finally awaits the detached _run_impl_task with no
# timeout (result.py:339-342), so we must never block on the drain task
# indefinitely — abandoning is the only escape. See
# docs/superpowers/specs/2026-05-17-inactivity-watchdog-design.md.
_ABANDON_GRACE_SECONDS = 5.0


def _swallow_task_result(task: "asyncio.Task") -> None:
    """Done-callback: retrieve an abandoned task's outcome so asyncio does
    not log 'Task exception was never retrieved' for a zombie drain."""
    if task.cancelled():
        return
    with contextlib.suppress(Exception):
        task.exception()


async def _drain_with_watchdog(result: RunResultStreaming) -> None:
    """Drain result.stream_events() under an inactivity + absolute-ceiling
    watchdog, cancelling and ABANDONING the run on stall.

    Why a separate task + external cancel: Runner.run_streamed spawns the
    real work as a detached background task. stream_events() swallows a
    CancelledError delivered to the consumer (result.py:322) then, in its
    finally, awaits that frozen detached task with no timeout
    (result.py:339-342). So an asyncio.wait_for around the drain can never
    fire. The only working mechanism is to run the drain in its own task
    and, from OUTSIDE it, call result.cancel("immediate") (synchronous
    producer kill, result.py:283-290) then abandon the drain task.
    """
    loop = asyncio.get_running_loop()
    started = loop.time()
    last_event = started

    async def _drain() -> None:
        nonlocal last_event
        async for _event in result.stream_events():
            last_event = loop.time()

    drain_task = asyncio.create_task(_drain())
    drain_task.add_done_callback(_swallow_task_result)
    inactivity = float(settings.agent_stream_inactivity_timeout_seconds)
    ceiling = float(settings.agent_run_timeout_seconds)
    try:
        while True:
            now = loop.time()
            remaining = min(
                inactivity - (now - last_event),
                ceiling - (now - started),
            )
            if remaining > 0:
                await asyncio.wait({drain_task}, timeout=remaining)
            if drain_task.done():
                drain_task.result()  # re-raise retriable / SDK error if any
                return
            now = loop.time()
            stalled = (now - last_event) >= inactivity
            over_ceiling = (now - started) >= ceiling
            if not (stalled or over_ceiling):
                continue
            logger.warning(
                "Agent run aborted (%s): inactive %.1fs, total %.1fs; "
                "cancelling + abandoning",
                "inactivity" if stalled else "absolute ceiling",
                now - last_event,
                now - started,
            )
            try:
                result.cancel("immediate")  # sync, non-blocking
            except Exception:
                logger.exception("result.cancel() failed")
            drain_task.cancel()
            await asyncio.wait({drain_task}, timeout=_ABANDON_GRACE_SECONDS)
            if not drain_task.done():
                logger.warning(
                    "Drain task did not stop within %.0fs grace; "
                    "abandoning zombie (httpx read-timeout will reap it)",
                    _ABANDON_GRACE_SECONDS,
                )
            raise TimeoutError(
                "agent stream inactive or absolute ceiling exceeded"
            )
    finally:
        if not drain_task.done():
            drain_task.cancel()
```

Then replace the entire existing `async def _run_agent_with_retry(...)`
function (from its `def` line through its final
`raise AssertionError("retry loop exited without a result")`) with:

```python
async def _run_agent_with_retry(agent, agent_input: str, session) -> RunResultStreaming:
    """Run the agent with bounded retries on transient/structured failures.

    Retries on ValidationError / ModelBehaviorError / OpenAI network
    errors. MaxTurnsExceeded and TimeoutError are NOT retried (re-running
    a stalled model just multiplies the wait).

    The drain runs under _drain_with_watchdog, which bounds it by an
    inactivity budget AND an absolute wall-clock ceiling and aborts via
    cancel + abandon. The old outer asyncio.wait_for is removed: the
    Agents SDK neutralizes it (see the design spec).
    """
    # Seed per-run perf state BEFORE any task is created: the shared dict
    # is mutated in place by the perf model-input filter from inside the
    # SDK's detached task context; rebinding via .set() would not
    # propagate. perf_logging only gates emission, not bookkeeping.
    now = time.perf_counter()
    _perf_state.set({"turn": 0, "attempts": 0, "start": now, "last": now})

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=_RETRY_WAIT,
        retry=retry_if_exception_type(_RETRIABLE_ERRORS),
        reraise=True,
    ):
        with attempt:
            state = _perf_state.get()
            if state is not None:
                state["attempts"] += 1
            result = Runner.run_streamed(
                starting_agent=agent,
                input=agent_input,
                session=session,
                max_turns=8,
                run_config=_RUN_CONFIG,
            )
            # Drain inside its own task under the watchdog. A stored
            # ValidationError/ModelBehaviorError surfaces here (re-raised
            # by drain_task.result()) so AsyncRetrying still retries it.
            await _drain_with_watchdog(result)
            return result
    # Unreachable: AsyncRetrying(reraise=True) either returns or re-raises.
    raise AssertionError("retry loop exited without a result")
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_pipeline_resilience.py -k "inactivity_watchdog or abandons_uncancellable" -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the FULL resilience suite (no regressions)**

Run: `uv run pytest tests/test_pipeline_resilience.py -v`
Expected: PASS — all pre-existing tests still green, including
`test_agent_run_times_out_and_is_not_retried`,
`test_retry_on_validation_error_from_stream`,
`test_run_agent_initialises_perf_state`,
`test_max_turns_exceeded_not_retried`.

- [ ] **Step 6: Commit**

```bash
git add src/rules_lawyer_bot/handlers/messages.py tests/test_pipeline_resilience.py
git commit -m "fix(agent): cancel+abandon inactivity watchdog (resolves KNOWN_ISSUES #2)"
```

---

### Task 4: httpx read-timeout backstop on the AsyncOpenAI client

**Files:**
- Modify: `src/rules_lawyer_bot/agent/definition.py` (imports + `client = AsyncOpenAI(...)`, ~lines 11-48)
- Test: `tests/test_agent_factory.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_factory.py`:

```python
def test_openai_client_uses_low_httpx_read_timeout():
    """The AsyncOpenAI client is built with an httpx.Timeout whose read
    timeout equals the inactivity budget (zombie-producer backstop), not
    the old 120s scalar."""
    import httpx

    from src.rules_lawyer_bot.agent.definition import create_agent
    from src.rules_lawyer_bot.config import settings

    with patch(
        "src.rules_lawyer_bot.agent.definition.AsyncOpenAI"
    ) as MockClient:
        create_agent()

    timeout = MockClient.call_args.kwargs["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.read == float(
        settings.agent_stream_inactivity_timeout_seconds
    )
    assert timeout.connect == 10.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_factory.py::test_openai_client_uses_low_httpx_read_timeout -v`
Expected: FAIL — `timeout` is a `float` (120.0), not `httpx.Timeout`; `isinstance` assertion fails.

- [ ] **Step 3: Implement the httpx.Timeout backstop**

In `src/rules_lawyer_bot/agent/definition.py`, add the import next to the
existing `from openai import AsyncOpenAI`:

```python
import httpx
from agents import Agent, OpenAIChatCompletionsModel, SQLiteSession
from openai import AsyncOpenAI
```

Replace the existing client construction:

```python
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=float(settings.agent_run_timeout_seconds),
    )
```

with:

```python
    # Low read-timeout = defense-in-depth backstop ONLY. The inactivity
    # watchdog in handlers/messages.py is the primary stall detector
    # (semantic: no SDK event). This bounds the lifetime of an abandoned
    # zombie producer if result.cancel() did not stop it promptly. Note:
    # proxyapi.ru keep-alive bytes can reset the httpx read-timeout
    # (KNOWN_ISSUES #2), which is exactly why it is only a backstop.
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=httpx.Timeout(
            read=float(settings.agent_stream_inactivity_timeout_seconds),
            connect=10.0,
            write=30.0,
            pool=10.0,
        ),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_agent_factory.py::test_openai_client_uses_low_httpx_read_timeout -v`
Expected: PASS

- [ ] **Step 5: Run the full agent-factory suite**

Run: `uv run pytest tests/test_agent_factory.py -v`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add src/rules_lawyer_bot/agent/definition.py tests/test_agent_factory.py
git commit -m "feat(agent): low httpx read-timeout backstop for zombie producer"
```

---

### Task 5: Per-user in-flight lock + orphan sweep wiring in `handle_message`

**Files:**
- Modify: `src/rules_lawyer_bot/handlers/messages.py` (retention import ~line 34-37; add module lock/constant near `BLOCKLIST_RESPONSE` ~line 80; pre-run sweep + reactive cleanup inside `_process_message`; in-flight gate around the tracer block ~lines 620-642)
- Create: `tests/test_messages_inflight.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_messages_inflight.py`:

```python
"""Per-user in-flight lock + orphan-turn sweep wiring in handle_message."""
import asyncio
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.rules_lawyer_bot.handlers import messages


def _update(user_id, text="rules?"):
    upd = MagicMock()
    upd.effective_user.id = user_id
    upd.effective_user.username = "u"
    upd.effective_chat.id = 555
    upd.message.text = text
    upd.message.reply_text = AsyncMock()
    return upd


def _context():
    ctx = MagicMock()
    ctx.user_data = {}
    ctx.bot.send_chat_action = AsyncMock()
    return ctx


@pytest.fixture(autouse=True)
def _clear_locks():
    messages._user_run_locks.clear()
    yield
    messages._user_run_locks.clear()


def _common_patches(run_mock):
    """Patch everything _process_message touches before/around the run so
    the test exercises only the in-flight gate."""
    prog = MagicMock()
    prog.finalize = AsyncMock()
    prog.report_tool_call = AsyncMock()
    prog.force_update = AsyncMock()
    return [
        patch.object(messages.settings, "budget_enabled", False),
        patch.object(
            messages.rate_limiter,
            "check_rate_limit",
            AsyncMock(return_value=(True, "")),
        ),
        patch.object(
            messages.game_resolver,
            "resolve",
            lambda *_a, **_k: types.SimpleNamespace(kind="ambiguous"),
        ),
        patch.object(
            messages, "get_user_session", lambda _uid: MagicMock()
        ),
        patch.object(
            messages,
            "drop_trailing_unanswered_user_turn",
            AsyncMock(return_value=False),
        ),
        patch.object(
            messages, "ProgressReporter", lambda *_a, **_k: prog
        ),
        patch.object(messages, "trim_session", AsyncMock()),
        patch.object(messages, "send_long_message", AsyncMock()),
        patch.object(messages, "_run_agent_with_retry", run_mock),
    ]


@pytest.mark.asyncio
async def test_second_concurrent_message_is_dropped_with_notice():
    started = asyncio.Event()
    release = asyncio.Event()

    async def _blocking_run(*_a, **_k):
        started.set()
        await release.wait()
        r = MagicMock()
        r.new_items = []
        r.final_output = None
        return r

    run_mock = AsyncMock(side_effect=_blocking_run)
    patches = _common_patches(run_mock)
    for p in patches:
        p.start()
    try:
        first = asyncio.create_task(
            messages.handle_message(_update(42), _context())
        )
        await asyncio.wait_for(started.wait(), timeout=2)  # lock held now

        upd2 = _update(42)
        await messages.handle_message(upd2, _context())

        upd2.message.reply_text.assert_awaited_once()
        assert "обрабат" in upd2.message.reply_text.call_args[0][0].lower()
        assert run_mock.await_count == 1  # second run never started

        release.set()
        await asyncio.wait_for(first, timeout=2)
        assert run_mock.await_count == 1
    finally:
        for p in patches:
            p.stop()


@pytest.mark.asyncio
async def test_pre_run_orphan_sweep_is_called_before_agent():
    sweep = AsyncMock(return_value=True)

    async def _quick_run(*_a, **_k):
        r = MagicMock()
        r.new_items = []
        r.final_output = None
        return r

    run_mock = AsyncMock(side_effect=_quick_run)
    patches = _common_patches(run_mock)
    # Replace the orphan-sweep patch (index 4) with our spy.
    patches[4] = patch.object(
        messages, "drop_trailing_unanswered_user_turn", sweep
    )
    for p in patches:
        p.start()
    try:
        await messages.handle_message(_update(7), _context())
        sweep.assert_awaited()  # pre-run sweep ran
        assert run_mock.await_count == 1
    finally:
        for p in patches:
            p.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_messages_inflight.py -v`
Expected: FAIL — `AttributeError: module 'src.rules_lawyer_bot.handlers.messages' has no attribute '_user_run_locks'` (and `drop_trailing_unanswered_user_turn` not yet imported into messages).

- [ ] **Step 3: Import the helper and add the lock + constant**

In `src/rules_lawyer_bot/handlers/messages.py`, extend the retention
import:

```python
from src.rules_lawyer_bot.utils.retention import (
    drop_trailing_clarification,
    drop_trailing_unanswered_user_turn,
    trim_session,
)
```

Add near the other response constants (right after `BLOCKLIST_RESPONSE = (...)`, ~line 83):

```python
# Per-user in-flight gate. asyncio is single-threaded per loop, so a
# locked() check immediately followed by `async with lock` has no yield
# point between them: a concurrent second update for the same user is
# reliably dropped (no second agent run on the same SQLiteSession).
_user_run_locks: dict[int, asyncio.Lock] = {}

BUSY_RESPONSE = (
    "⏳ Я ещё обрабатываю ваш предыдущий вопрос — подождите немного."
)
```

- [ ] **Step 4: Add the pre-run orphan sweep**

In `_process_message`, the current block is:

```python
            session = get_user_session(user.id)
            if answering_clarification:
                try:
                    await drop_trailing_clarification(session)
                except Exception:
                    logger.exception("drop_trailing_clarification failed")
```

Replace it with (sweep runs first — a killed prior run's orphan is a
trailing user turn; the clarification drop targets a trailing assistant
turn, so order is independent and safe):

```python
            session = get_user_session(user.id)
            # Pre-run sweep: a prior killed/aborted run may have left an
            # orphaned trailing user turn (SDK persists input immediately,
            # answer only at the end). At this point the new input is not
            # in the session yet, so any trailing user turn is an orphan.
            try:
                await drop_trailing_unanswered_user_turn(session)
            except Exception:
                logger.exception("pre-run orphan sweep failed")
            if answering_clarification:
                try:
                    await drop_trailing_clarification(session)
                except Exception:
                    logger.exception("drop_trailing_clarification failed")
```

- [ ] **Step 5: Add the reactive cleanup in the TimeoutError branch**

In `_process_message`, the current branch is:

```python
            except TimeoutError:
                logger.warning(
                    f"Agent run timed out for user {user.id} after "
                    f"{settings.agent_run_timeout_seconds}s"
                )
                await progress.finalize()
                await message.reply_text(AGENT_TIMEOUT_RESPONSE)
                return AGENT_TIMEOUT_RESPONSE
```

Replace it with:

```python
            except TimeoutError:
                logger.warning(
                    f"Agent run timed out for user {user.id} after "
                    f"{settings.agent_run_timeout_seconds}s"
                )
                # Reactive cleanup: the aborted run just orphaned this
                # user turn in the session. Best-effort; the next run's
                # pre-run sweep is the robust net.
                try:
                    await drop_trailing_unanswered_user_turn(session)
                except Exception:
                    logger.exception("reactive orphan cleanup failed")
                await progress.finalize()
                await message.reply_text(AGENT_TIMEOUT_RESPONSE)
                return AGENT_TIMEOUT_RESPONSE
```

- [ ] **Step 6: Add the in-flight gate around the run**

In `handle_message`, the current tail is:

```python
    # Run with root span for Langfuse tracing
    if tracer is not None:
        # Create root span with user context
        from src.rules_lawyer_bot.utils.observability import get_trace_context_for_user

        trace_attrs = get_trace_context_for_user(user.id, user.username)
        # Add session ID for Langfuse session grouping
        trace_attrs["langfuse.session.id"] = str(chat.id)
        # Set input at trace level (required for Langfuse)
        trace_attrs["input"] = message_text

        with tracer.start_as_current_span(
            "telegram_message_handler", attributes=trace_attrs
        ) as root_span:
            # Run processing and get output
            output = await _process_message()

            # Set output at trace level (required for Langfuse)
            if root_span.is_recording():
                root_span.set_attribute("output", output)
    else:
        # No tracing, run directly
        await _process_message()
```

Replace it with (gate first, then the existing block unchanged but
indented one level under `async with lock:`):

```python
    # Per-user in-flight gate: drop a concurrent second message instead of
    # starting a second agent run on the same SQLiteSession.
    lock = _user_run_locks.setdefault(user.id, asyncio.Lock())
    if lock.locked():
        logger.info(
            "In-flight run for user %s; dropping concurrent message", user.id
        )
        await message.reply_text(BUSY_RESPONSE)
        return
    async with lock:
        # Run with root span for Langfuse tracing
        if tracer is not None:
            # Create root span with user context
            from src.rules_lawyer_bot.utils.observability import (
                get_trace_context_for_user,
            )

            trace_attrs = get_trace_context_for_user(user.id, user.username)
            # Add session ID for Langfuse session grouping
            trace_attrs["langfuse.session.id"] = str(chat.id)
            # Set input at trace level (required for Langfuse)
            trace_attrs["input"] = message_text

            with tracer.start_as_current_span(
                "telegram_message_handler", attributes=trace_attrs
            ) as root_span:
                # Run processing and get output
                output = await _process_message()

                # Set output at trace level (required for Langfuse)
                if root_span.is_recording():
                    root_span.set_attribute("output", output)
        else:
            # No tracing, run directly
            await _process_message()
```

- [ ] **Step 7: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_messages_inflight.py -v`
Expected: PASS (2 passed)

- [ ] **Step 8: Run the handler regression suites**

Run: `uv run pytest tests/test_messages_budget.py tests/test_integration.py -v`
Expected: PASS (all — the gate sits after rate-limit/budget/blocklist, so those paths are unchanged)

- [ ] **Step 9: Commit**

```bash
git add src/rules_lawyer_bot/handlers/messages.py tests/test_messages_inflight.py
git commit -m "feat(handler): per-user in-flight lock + orphan-turn sweep wiring"
```

---

### Task 6: Full verification (lint, types, whole suite)

**Files:** none (verification only)

- [ ] **Step 1: Lint**

Run: `uv run ruff check .`
Expected: PASS (no errors)

- [ ] **Step 2: Format**

Run: `uv run ruff format .`
Expected: files unchanged or reformatted; if anything reformatted, `git add -A && git commit -m "style: ruff format"`.

- [ ] **Step 3: Static types (changed files only)**

Run: `uv run pyrefly check`
Expected: No NEW type errors in `config.py`, `utils/retention.py`,
`handlers/messages.py`, `agent/definition.py`. Pre-existing legacy errors
elsewhere are out of scope (per `CLAUDE.md`); if pyrefly flags a changed
file, fix only that file.

- [ ] **Step 4: Full test suite**

Run: `uv run pytest -q`
Expected: PASS (entire suite green, no regressions)

- [ ] **Step 5: Final commit (only if Step 2/3 produced changes)**

```bash
git add -A
git commit -m "chore: lint/format/type cleanup for inactivity-watchdog work"
```

---

## Self-Review

**Spec coverage:**
- Fix 1 inactivity watchdog (cancel+abandon, removes outer wait_for, absolute ceiling via watchdog) → Task 3. ✓
- Fix 2 httpx read-timeout backstop → Task 4. ✓
- Fix 3 per-user in-flight lock (drop + notice) → Task 5 (gate + `BUSY_RESPONSE` + `_user_run_locks`). ✓
- Fix 4 orphan cleanup: helper → Task 2; pre-run sweep → Task 5 Step 4; reactive on TimeoutError → Task 5 Step 5. ✓
- Config knob + repurposed ceiling docstring → Task 1. ✓
- `_ABANDON_GRACE_SECONDS` module constant → Task 3. ✓
- Perf-state in-place-mutation invariant preserved (set before tasks) → Task 3 rewrite. ✓
- Tests: frozen-stream/inactivity, abandon, absolute-ceiling (existing `test_agent_run_times_out_and_is_not_retried` still asserts ceiling path), in-flight drop, orphan sweep/reactive → Tasks 2,3,5. ✓
- Residual risk (zombie writing post-release) accepted/documented in spec; mitigations (pre-run sweep + trim + httpx backstop) all implemented. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N"; every code step shows full code; every run step shows the exact command and expected result. ✓

**Type consistency:** `drop_trailing_unanswered_user_turn(session) -> bool` defined in Task 2, imported and called identically in Task 5. `_drain_with_watchdog(result: RunResultStreaming) -> None`, `_swallow_task_result(task)`, `_ABANDON_GRACE_SECONDS`, `_user_run_locks`, `BUSY_RESPONSE` defined and used with consistent names/signatures across Tasks 3 and 5. `httpx.Timeout(read=..., connect=10.0, write=30.0, pool=10.0)` matches the Task 4 test assertions (`timeout.read`, `timeout.connect == 10.0`). ✓
