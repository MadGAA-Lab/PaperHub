# Resumable Chat Streaming — Implementation Plan (Part A, rewritten)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use
> checkbox (`- [ ]`) tracking. Per-task gates (CLAUDE.md): backend from `backend/` via `uv run`;
> frontend from `frontend/` via `npm`; run only touched test files + targeted ruff/mypy/typecheck
> /lint per task; full suites at plan-phase completion. Conventional Commits; focused per-concern
> commits; never stage build output.

**Goal:** Replace the old "Stop = client-side retract" Part A with **server-side resumable
streaming**: a run is a backend-owned background task; a disconnect never cancels; the originating
tab streams live; a returning client (refresh / other device) reattaches by **polling event
deltas** replayed through the same reducer; **only the explicit Stop button cancels**.

**Source of truth:** [`2026-06-17-paperhub-resumable-streaming-design.md`](2026-06-17-paperhub-resumable-streaming-design.md)
(decisions D1–D8). **Part B (version/changelog)** stays in
[`2026-06-16-paperhub-run-cancel-version-awareness.md`](2026-06-16-paperhub-run-cancel-version-awareness.md)
and is unaffected.

**Tech stack:** Backend — FastAPI, sse-starlette, aiosqlite, asyncio. Frontend — React 19 + TS
strict, Zustand, react-i18next, Sonner, lucide-react. Tests — pytest; Vitest + RTL + MSW.

---

## File structure

**Backend**
- `backend/src/paperhub/api/run_broker.py` (create) — `RunHandle` + `RunBroker` (process-local
  registry): `emit`, `subscribe`/`unsubscribe`, `events_since`, terminal + TTL eviction, live-task
  set.
- `backend/src/paperhub/api/chat.py` (modify) — extract the `stream_events` body into a
  `run_agent(...)` background coroutine that `handle.emit({...})`s instead of `yield`ing; `POST
  /chat` spawns it + returns a thin **subscriber** SSE; add `POST /chat/cancel` and `GET
  /chat/runs/{run_id}/events`.
- `backend/src/paperhub/db/...` or `app.py` lifespan (modify) — startup reconciliation: leftover
  `running` → `interrupted` + paired assistant row.
- `backend/src/paperhub/api/sessions.py` (modify) — `GET …/messages` returns each row's run
  `status`.
- Tests: `backend/tests/test_run_broker.py`, `test_chat_resumable.py`, `test_chat_cancel.py`,
  `test_startup_reconcile.py`, `test_messages_run_status.py`; `backend/scripts/live_resume_test.py`.

**Frontend**
- `frontend/src/types/domain.ts` (modify) — `ChatMessage.status` += `"processing" | "interrupted"`;
  `RunEventsResponse` type.
- `frontend/src/lib/api.ts` (modify) — `cancelRun(runId)`, `fetchRunEvents(runId, since)`.
- `frontend/src/store/chat.ts` (modify) — `retractTurn`, hydrate `running` → `processing`
  placeholder, an `applyRunEvent` reducer reused by SSE + poller, `markInterrupted`/retry helpers.
- `frontend/src/hooks/useChatStream.ts` (modify) — synchronous `stop()`; reuse `applyRunEvent`.
- `frontend/src/hooks/useRunReattach.ts` (create) — poll `processing` turns → replay deltas → stop
  on terminal / switch / tab-hide.
- `frontend/src/components/chat/Composer.tsx` (modify) — Send→Stop while streaming.
- `frontend/src/components/chat/MessageBubble.tsx` (modify) — render `interrupted` + Retry.
- `frontend/src/pages/ChatPage.tsx` (modify) — wire `isStreaming` + `onStop`; mount reattach.
- `frontend/src/locales/{en,zh-TW,zh-CN,ja}/chat.json` (modify) — `composer.stop*`,
  `message.interrupted`, `message.retry`.
- Tests colocated per unit.

---

## Task A1 — Run broker (`run_broker.py`)

**Pure, no FastAPI.** TDD: `backend/tests/test_run_broker.py` first.

Interface:
```python
@dataclass
class RunHandle:
    run_id: int
    task: asyncio.Task[Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)   # full SSE event buffer
    subscribers: set[asyncio.Queue[dict[str, Any] | None]] = field(default_factory=set)
    status: str = "running"          # running|ok|error|cancelled|interrupted
    final_message_id: int | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)
    evict_at: float | None = None

    def emit(self, event: dict[str, Any]) -> None: ...   # append + fan out to subscribers
    def subscribe(self) -> asyncio.Queue: ...            # returns a queue pre-seeded? no: see A2
    def unsubscribe(self, q) -> None: ...
    def events_since(self, cursor: int) -> tuple[list[dict], int]: ...  # (events[cursor:], len)
    def mark_terminal(self, status: str, *, now: float) -> None: ...    # set status, done, evict_at

class RunBroker:
    def register(self, run_id) -> RunHandle
    def get(self, run_id) -> RunHandle | None
    def evict_expired(self, now: float) -> None
```

Tests: emit appends + delivers to all subscribers; `events_since(cursor)` returns the tail +
new cursor; `mark_terminal` sets status/done/`evict_at`; `evict_expired` drops only past-TTL
terminal handles; a subscriber added mid-run misses nothing when the caller replays
`events_since(0)` first (the A2 contract).

> **Time:** `time.monotonic()` is passed in (`now=`) so tests are deterministic — do not call it
> inside the broker.

Gates: `uv run pytest tests/test_run_broker.py`, ruff, mypy.
Commit: `feat(chat): in-process run broker for resumable streaming (FR-15)`.

---

## Task A2 — Extract `run_agent` + subscriber `POST /chat`

**The load-bearing refactor.** Move the body of `stream_events()`
([chat.py:580-961](../../../backend/src/paperhub/api/chat.py#L580-L961)) into a module-level
background coroutine `run_agent(handle, req, settings, adapter, ...)`. Mechanical rule: **every
`yield {"event": E, "data": D}` becomes `handle.emit({"event": E, "data": D})`.** Keep all agent
logic, tracing, `_finalise`, the `set/reset_client_headers_context` contextvar, and the existing
`try/except Exception/finally` intact. Add:
- on success: after `_finalise(status="ok")`, `handle.final_message_id = message_id`; emit `final`;
  `handle.mark_terminal("ok", now=monotonic())`.
- on `except Exception`: emit `error`; `mark_terminal("error", ...)`.
- on `except asyncio.CancelledError`: re-raise (the cancel endpoint owns DB cleanup); the `finally`
  still resets the contextvar and `mark_terminal` is NOT called here (cancel path sets status).
- `finally`: `reset_client_headers_context`; close subscriber queues (`emit(None)` sentinel).

`POST /chat`:
```python
handle = broker.register(run_id)
handle.task = asyncio.create_task(run_agent(handle, ...))
_live_tasks.add(handle.task); handle.task.add_done_callback(_live_tasks.discard)

async def subscriber() -> AsyncIterator[dict]:
    q = handle.subscribe()
    try:
        for past in handle.events:            # replay buffer (register→subscribe race insurance)
            yield past
        while True:
            evt = await q.get()
            if evt is None: break             # terminal sentinel
            yield evt
    finally:
        handle.unsubscribe(q)                 # DISCONNECT = unsubscribe only; task keeps running
return EventSourceResponse(subscriber())
```

> **Key property to preserve:** the `run_id`/`session` event must be emitted by `run_agent` (so a
> reattaching client still learns the run_id via `/messages`, and the originating SSE gets it on
> replay). The user message is persisted inside `run_agent` before work starts, as today.

Tests (`test_chat_resumable.py`, stubbed adapter): (1) `POST /chat` streams the same events as
before; (2) **disconnect ≠ cancel** — drop the subscriber early, assert the `run_agent` task still
reaches a terminal status and persisted the assistant message; (3) a second subscriber attached
after some events still receives the full sequence (replay).

Gates: pytest those + the existing chat tests, ruff, mypy.
Commit: `feat(chat): run agent in a background task; POST /chat subscribes (FR-15)`.

---

## Task A3 — `POST /chat/cancel` (the only cancel path)

```python
class CancelRequest(BaseModel):
    run_id: int

@router.post("/chat/cancel")
async def cancel_run(req: CancelRequest) -> dict[str, str]:
    handle = broker.get(req.run_id)
    if handle is not None and handle.task is not None and not handle.task.done():
        handle.task.cancel()
        handle.mark_terminal("cancelled", now=time.monotonic())
    settings = load_settings()
    async with open_db(settings.db_path) as conn:
        # guard BOTH writes on still-'running' so a Stop racing completion can't nuke a real answer
        await conn.execute(
            "DELETE FROM messages WHERE run_id = ? AND run_id IN "
            "(SELECT id FROM runs WHERE id = ? AND status = 'running')",
            (req.run_id, req.run_id))
        await conn.execute(
            "UPDATE runs SET finished_at=datetime('now'), status='cancelled' "
            "WHERE id = ? AND status = 'running'", (req.run_id,))
        await conn.commit()
    return {"status": "cancelled", "run_id": str(req.run_id)}
```

Tests (`test_chat_cancel.py`, autouse-clear the broker): cancels a registered task (sleep
stand-in) → `task.cancelled()`; deletes messages + sets `cancelled` for a `running` run; **race
guard** — an already-`ok` run keeps its messages + stays `ok`; a no-handle `running` run (post
restart) is still cleaned up by the guarded DB writes.

Gates: pytest, ruff, mypy.
Commit: `feat(chat): POST /chat/cancel cancels the run task + retracts (FR-15)`.

---

## Task A4 — `GET /chat/runs/{run_id}/events` (reattach poll, high-fidelity)

```python
@router.get("/chat/runs/{run_id}/events")
async def run_events(run_id: int, since: int = 0) -> dict[str, object]:
    handle = broker.get(run_id)
    if handle is not None:
        events, cursor = handle.events_since(since)
        return {"status": handle.status, "events": events, "next_cursor": cursor}
    # handle absent: evicted-after-done or lost-to-restart → DB fallback to a terminal snapshot
    settings = load_settings()
    async with open_db(settings.db_path) as conn:
        row = await (await conn.execute(
            "SELECT status FROM runs WHERE id = ?", (run_id,))).fetchone()
        status = row[0] if row else "interrupted"
        # build a synthetic terminal event (final or error) from the persisted assistant message
        events = await _terminal_events_from_db(conn, run_id, status, since)
    return {"status": status, "events": events, "next_cursor": since + len(events)}
```

`_terminal_events_from_db`: for `ok` emit a `final` event from the assistant row; for
`error|interrupted` emit an `error`/`interrupted` event; for `cancelled` emit nothing (client
removes the placeholder). Only emit when `since == 0` (the client hasn't converged yet).

Tests (`test_chat_resumable.py`): live handle returns deltas + advancing cursor; absent handle with
an `ok` run returns a synthetic `final`; absent + `cancelled` returns `status=cancelled`, no events.

Gates: pytest, ruff, mypy.
Commit: `feat(chat): GET /chat/runs/{id}/events reattach poll with DB fallback (FR-15)`.

---

## Task A5 — Startup reconciliation (running → interrupted)

On app boot (lifespan startup, before serving), in a single transaction:
```sql
-- pair invariant: give each orphaned running run a paired assistant 'interrupted' row
INSERT INTO messages (session_id, run_id, role, content, created_at)
SELECT m.session_id, m.run_id, 'assistant', '', datetime('now')
FROM messages m JOIN runs r ON r.id = m.run_id
WHERE r.status='running' AND m.role='user'
  AND NOT EXISTS (SELECT 1 FROM messages a WHERE a.run_id=m.run_id AND a.role='assistant');
UPDATE runs SET status='interrupted', finished_at=datetime('now') WHERE status='running';
```
(Adapt column names to the real schema.) The assistant row's *content* is empty; the frontend
renders `status='interrupted'` as the distinct Retry state (A9), not from message text.

Test (`test_startup_reconcile.py`): seed a `running` run + lone user message, run the reconcile
fn, assert `runs.status='interrupted'` and a paired assistant row now exists.

Gates: pytest, ruff, mypy.
Commit: `feat(chat): mark in-flight runs interrupted on startup (FR-15)`.

---

## Task A6 — `GET …/messages` returns run status

[sessions.py:176-195](../../../backend/src/paperhub/api/sessions.py#L176-L195) already
`LEFT JOIN runs r`. Add `r.status` to the SELECT and a `run_status: str | None` field to
`MessageOut`. The client uses it to decide which trailing turns are `running` (→ processing
placeholder + poller).

Test (`test_messages_run_status.py`): a session with a `running` run returns `run_status:'running'`
on the user row; an `ok` run returns `'ok'`.

Gates: pytest, ruff, mypy.
Commit: `feat(chat): include run status in GET session messages (FR-15)`.

---

## Task A7 — Composer Stop button + i18n

Per old A4 (unchanged): props `isStreaming?`, `onStop?`; while streaming render a Stop button
(`type="button"`, `<Square>`, `aria-label={t("composer.stop")}`, tooltip `composer.stopTooltip`,
not disabled). i18n keys in all four locales: `composer.stop` (Stop/停止/停止/停止),
`composer.stopTooltip` (Stop generating/停止生成/停止生成/生成を停止).

Test (`ComposerStop.test.tsx`): streaming shows `/stop/i` and calls `onStop`; idle shows Send.
Parity test green.

Commit: `feat(chat): Composer Stop button + tooltip while streaming (FR-15)`.

---

## Task A8 — `cancelRun` client + synchronous `stop()` + ChatPage wiring

`api.ts`: `cancelRun(runId)` → `POST /chat/cancel`; `fetchRunEvents(runId, since)` →
`GET /chat/runs/{id}/events?since=`.

`useChatStream.ts` `stop()` (synchronous, same tick): set `userStoppedRef`; `abortRef.abort()`;
resolve `rid = runIdRef.current ?? <run_id of the trailing processing/streaming assistant in the
active session>`; `retractTurn(sid)` → `requestComposerText(restored)`; `void cancelRun(rid)`.
Swallow the user-stop abort in the outer catch (`if (userStoppedRef.current) return;`).

`store.ts` `retractTurn(sessionId): string` — drop the trailing assistant placeholder + its paired
user message; return the user text (per old A2).

`ChatPage.tsx`: `const { send, stop } = useChatStream();` pass `isStreaming` + `onStop={stop}`.

Tests: `retractTurn.test.ts` (pair removed, text returned); `useChatStreamStop.test.ts` (SSE that
*resolves* on abort → after `send`+`stop()`, session has 0 messages + composer draft restored;
`cancelRun` mocked).

Commit: `feat(chat): synchronous stop() retracts + cancels; run-events client (FR-15)`.

---

## Task A9 — Status taxonomy + `interrupted`/Retry render

`domain.ts`: `ChatMessage.status?: "streaming" | "processing" | "ok" | "error" | "interrupted"`.
- `streaming` = live local SSE (originating tab). `processing` = hydrated/reattached (drives the
  poller + Stop). Both make `isStreaming`-style UI true; only `processing` is polled.
- Update `ChatPage` `isStreaming` to `status === "streaming" || status === "processing"` so Stop
  shows on reattached turns too.

`MessageBubble.tsx`: render `status==='interrupted'` as a distinct muted bubble with a **Retry**
button (`t("message.retry")`) that re-sends the original user message (call the existing send path
with the paired user text). i18n: `message.interrupted` ("Generation was interrupted." / 生成已中斷
/ 生成已中断 / 生成が中断されました。), `message.retry` (Retry/重試/重试/再試行).

Tests: `MessageBubbleInterrupted.test.tsx` (interrupted shows the message + a Retry control);
parity green.

Commit: `feat(chat): processing + interrupted message states with Retry (FR-15)`.

---

## Task A10 — Reattach poller (`useRunReattach.ts`)

On hydration, `hydrateSessionMessages` appends a `processing` assistant placeholder (`content:""`,
carries `run_id`) when the last user row's run is `running` and has no assistant row (pair
invariant). Introduce/extract an `applyRunEvent(sessionId, event)` store reducer that BOTH the SSE
path and the poller feed (same fidelity — D7).

`useRunReattach()` (mounted in ChatPage): for the active session's trailing `processing` turn, keep
a `cursor` and poll `fetchRunEvents(run_id, cursor)` every ~1 s:
- replay each returned event via `applyRunEvent`; advance `cursor = next_cursor`.
- stop when `status` is terminal (`ok` settles via a `/messages` refetch; `error|interrupted` show
  the state; `cancelled` removes the placeholder), on session switch, or on tab hide
  (`document.hidden`).

Tests (`useRunReattach.test.ts`, MSW): a `processing` turn polls, applies a `token` then a `final`,
flips the bubble to `ok`, and stops polling; a `cancelled` response removes the placeholder.

Commit: `feat(chat): reattach poller replays run events on refresh/other device (FR-15)`.

---

## Part A verification (REQUIRED before "done")

1. **Unit:** all A1–A10 tests green; backend ruff+mypy, frontend typecheck+lint clean.
2. **LIVE (`backend/scripts/live_resume_test.py` against `:8000`):**
   - **disconnect ≠ cancel** — open `/chat`, capture `run_id`, drop the SSE mid-run; assert
     `tool_calls` keep accruing and `runs.status` stays `running` → then `ok` (finished with no
     client);
   - **reattach** — after the drop, poll `GET /chat/runs/{id}/events` and observe deltas building to
     a terminal `final` with the full answer;
   - **explicit Stop stops the LLM** — on a fresh run, `POST /chat/cancel`; `tool_calls` count
     frozen within ~1 s, `runs.status='cancelled'`, messages deleted.
3. **Browser (the gate that matters):** long turn → refresh mid-answer → the turn reattaches and
   finishes on screen (trace + deck rebuild); open the same session on a second tab → it shows the
   answer building; one Stop click → turn vanishes, text restored, backend halts; restart the
   backend mid-run → the turn shows **interrupted** with Retry. Ask the user to confirm visually.

---

## Self-review

**Design coverage:** D1 background task (A2) ✓; D2 live SSE subscribe (A2) ✓; D3 polling reattach
(A4+A10) ✓; D4 cancel-only-by-Stop (A3; disconnect just unsubscribes in A2) ✓; D5 startup
interrupted (A5) ✓; D6 single-worker (assumed; broker process-local) ✓; D7 high-fidelity event
deltas through one reducer (A4+A10 `applyRunEvent`) ✓; D8 distinct interrupted + Retry (A9) ✓.
**Pair invariant:** retract removes both (A8); hydrate adds a processing placeholder (A10); startup
adds a paired interrupted row (A5). **Risk retired:** owned-task cancel (A2/A3) removes the
sse-starlette task-identity gamble from the old A1.
