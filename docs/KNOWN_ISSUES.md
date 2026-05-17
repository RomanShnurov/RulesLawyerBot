# Known Issues (deferred)

## #2 — Hard agent-run timeout does not bound a stalled proxy stream

**Status:** deferred (root-caused, not fixed). Logged 2026-05-17.

### Update 2026-05-17 — it is extreme tail latency, NOT a permanent hang

A later run confirmed the request **does eventually complete correctly** —
it is catastrophic intermittent latency, not a lost answer:

```
13:39:53  [Resolver] resolved -> Alchemists (score=100); context injected
13:56:18  [Perf] run summary: total=974.01s turns≈5 tool_calls=3 tokens=33627
13:56:18  action_type: final_answer  ->  Final answer sent (confidence: 92%)
```

Per-turn deltas in that run:

```
normal turns:  +0.03s +4.12s +3.63s +1.95s +4.44s   (model ~2-4s)
pathological:  +604.25s  +603.54s  +262.19s  +99.72s  (proxy stream frozen)
```

So ~974s (~16 min) wall-clock was almost entirely four multi-minute
freezes between model turns; the answer arrived and was correct. The
`asyncio.wait_for(120s)` still did not abort during the freezes
(confirming root cause #1: the cancel is not propagating through the SDK
stream await).

Amplifier observed: the user re-sent the same message after ~10s of no
reply, spawning a **second concurrent agent run on the same SQLiteSession**
(no per-user in-flight lock). It also inherited a stale user turn
("Сколько очков за птицу в Крылья?") left in the session by a *previous*
killed run (a hung run never reaches `trim_session`, so its un-answered
user message persists and confuses the next run). Two secondary gaps worth
fixing alongside #2:
- a per-user in-flight lock (drop/queue a second message while one is
  running) to prevent concurrent runs on one session;
- cleanup of a killed/aborted run's trailing un-answered user turn.

### Symptom

A user question entered the agent and produced **no answer for ~18 minutes**.
Perf log (clean diagnostic run, `PERF_LOGGING=true`):

```
12:18:34  User 262689794: Сколько очков за птицу в Крылья?
12:18:35  [Perf] model turn 1 ... trace=019e353a
12:33:37  [Perf] model turn 2: prev turn +902.14s, input≈3985 est_tokens, 35 items
          (no [Perf] run summary, no reply, run still alive afterwards)
```

`prev turn +902.14s` = the model/proxy stream stalled **902 seconds between
two model turns**. The bot stayed alive (heartbeat OK, `pdfs=241`) but the
single request hung and never returned. The `agent_run_timeout_seconds=120`
hard deadline did **not** abort it.

### Where the timeout is applied

`src/rules_lawyer_bot/handlers/messages.py` — `_run_agent_with_retry` (~line 275):

```python
async def _attempts() -> RunResultStreaming:
    async for attempt in AsyncRetrying(stop=stop_after_attempt(3), ...):
        with attempt:
            result = Runner.run_streamed(starting_agent=agent, input=agent_input,
                                         session=session, max_turns=8,
                                         run_config=_RUN_CONFIG)
            async for _event in result.stream_events():   # full drain
                pass
            return result

return await asyncio.wait_for(_attempts(), timeout=settings.agent_run_timeout_seconds)  # 120s
```

The whole stream drain is *formally* inside `asyncio.wait_for(120s)`, yet it
did not fire.

### Root cause (most likely → least likely)

1. **Cancellation delivered but not propagated.** `asyncio.wait_for` only
   *schedules* a cancel; the coroutine must surface `CancelledError` at an
   await point. The Agents SDK streaming generator / httpx-anyio transport
   can swallow it (broad `except`, or a blocking network teardown in the
   async-generator `aclose()`), so the cancel never takes effect.
2. **Proxy keep-alive defeats the per-read timeout.** OpenRouter via
   proxyapi.ru holds the SSE connection open and trickles keep-alive bytes;
   each byte resets the httpx read-timeout (`AsyncOpenAI(timeout=120)`)
   while zero *semantic* progress is made. `asyncio.wait_for` is wall-clock
   so should still fire — unless combined with (1).
3. The 902s gap is between two perf-filter invocations (the filter fires
   once per model turn via `call_model_input_filter`): turn-1's model
   request was sent, the proxy held the connection ~902s before delivering
   the turn-1 completion that triggers turn 2.

The actual failure mode is **stream inactivity** (no new events), not just
total wall-clock — and the current single outer `wait_for` does not catch
it. Secondary impact: a 902s stall blocks the Telegram update handler; with
sequential update processing this can freeze the bot for other users too
(exactly what the `agent_run_timeout_seconds` docstring in `config.py`
warns about).

### Proposed fix (when resumed)

- Add an **inactivity watchdog** around `result.stream_events()`: bound each
  iteration (`anext`) with its own `asyncio.wait_for` (per-chunk budget,
  e.g. a fraction of `agent_run_timeout_seconds`). No new event within the
  budget → cancel, raise `TimeoutError`, return `AGENT_TIMEOUT_RESPONSE`.
  This gives a cancel point the SDK cannot swallow and detects the real
  failure mode (inactivity) rather than only total wall-clock.
- Keep the outer `asyncio.wait_for` as the absolute ceiling.
- Verify the cancel actually tears down the httpx stream (no shielded
  `aclose()` hang); add a small `asyncio.shield`-free teardown if needed.
- Consider lowering the `AsyncOpenAI` httpx read timeout and confirming the
  `APITimeoutError` (retriable) path works for non-trickle stalls.

### Notes

- Orthogonal to the P1–P4 pipeline work (resolver / clarification state /
  prompt / payload eviction). Pre-existing; surfaced during P1–P4 E2E
  verification on 2026-05-17.
- Reproduces against the live OpenRouter-via-proxyapi gateway with
  `openai/gpt-oss-120b`; may be intermittent (depends on proxy behaviour).
