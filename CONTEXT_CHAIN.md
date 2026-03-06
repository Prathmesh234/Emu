# Context Chain — Limitations & Improvements

Current implementation: `backend/context_manager/context.py`

---

## Architecture

```
_history: dict[str, list[PreviousMessage]]
    key   = session_id (UUID string)
    value = ordered list of turns [system, user, assistant, user, ...]
```

Each turn is a `PreviousMessage(role, content, timestamp)` where screenshots are stored as full `data:image/png;base64,...` strings inline in `content`.

---

Another feature to add - Step by step tackling of the problem using .md files as memory context. We will have plan.md which will always be made for each session and other information it can create those other .md files. 

## Limitations

### 1. No token/size budgeting
- Every screenshot is ~2-3 MB of base64 text. A 30-step task accumulates ~60-90 MB of raw string data in-memory.
- Claude's context window is 200K tokens. Each base64 screenshot consumes significant tokens. After ~15-20 screenshots the chain may hit the limit with no handling.
- **No pruning, summarization, or sliding window.** The chain grows unbounded until the session ends.

### 2. In-memory only — no persistence
- `_history` is a Python dict. If the server restarts (uvicorn reload, crash), all session history is lost.
- Long-running 3-4 hour tasks are vulnerable to any process interruption.
- No disk/DB fallback, no checkpointing.

### 3. No session cleanup or TTL
- Sessions are never garbage-collected. Orphaned sessions (user closes Electron, network drops) stay in memory forever.
- `clear_session()` exists but is never called from any endpoint.
- No TTL, no max-sessions cap, no eviction policy.

### 4. Screenshots stored at full resolution
- Every screenshot is stored as-is (~2700 KB base64). No compression, no resizing.
- Older screenshots become less useful as the task progresses — the model mostly needs the latest 2-3.
- No distinction between "current state" screenshots and "historical reference" screenshots.

### 5. No context window management strategy
- When the chain exceeds the model's context window, the API call will fail with an error.
- No pre-flight token counting before calling the model.
- No strategy for what to drop: old screenshots? Old assistant turns? Summarize middle turns?

### 6. Consecutive same-role merging is lossy
- `_merge_consecutive()` in the Claude client merges consecutive user messages (e.g., screenshot + text) into one multi-part message.
- This is necessary for Anthropic's alternating-role requirement but loses turn boundary information.
- If two user texts get merged, the model can't distinguish which came first.

### 7. No task isolation within a session
- A session can span multiple tasks (user says "open Chrome", then later "now open VS Code").
- There's no concept of task boundaries. The entire history of task 1 is carried into task 2.
- For multi-hour sessions this means task 5 carries the full context of tasks 1-4, most of which is irrelevant noise.

### 8. No error/retry context
- When a model call fails (network error, parse error, timeout), the chain still has the screenshot that was sent.
- But if the fallback action (screenshot with 0.5 confidence) gets added to the chain, it pollutes history with low-quality turns.
- No mechanism to mark a turn as "failed/retried" vs "successful."

### 9. System prompt is frozen at session start
- The system prompt is added once when the session is created (`_get()` bootstraps it).
- If the system prompt is updated (code change), existing sessions still use the old one.
- No way to hot-swap or version the system prompt mid-session.

### 10. No concurrent access protection
- Multiple async requests for the same session_id can race on `_history[session_id].append()`.
- Python lists are mostly thread-safe for appends, but FastAPI's async handlers could interleave between `add_screenshot_turn` and `build_request` in unexpected ways.
- No locking per session.

### 11. build_request copies entire history every call
- `list(history)` creates a shallow copy of the full chain on every model call.
- With 100+ turns this is wasteful. The copy is only used to build one API request.

### 12. No metadata on turns
- Turns only store `role`, `content`, `timestamp`.
- Missing: step_index, action_type, confidence, success/failure, token count, image dimensions.
- Makes it impossible to implement smart pruning ("drop all screenshots older than turn N except the first one").

---

## Proposed Improvements (Priority Order)

### P0 — Must-have for 3-4 hour sessions

| # | Fix | Approach |
|---|-----|----------|
| 1 | **Sliding window with screenshot pruning** | Keep last N screenshots at full resolution. Replace older screenshots with a text marker `[SCREENSHOT @ turn 7 — removed]`. Always keep the first screenshot. |
| 2 | **Token counting pre-flight** | Before calling the model, estimate token count. If over budget, apply pruning. Use `anthropic.count_tokens()` or a rough heuristic (4 chars ≈ 1 token, images via Anthropic's formula). |
| 3 | **Session persistence** | Write chain to disk (SQLite or JSON file per session) after every turn. Reload on server restart. |
| 4 | **Session TTL + cleanup** | Background task that evicts sessions idle for >1 hour. Endpoint to explicitly close a session. |

### P1 — Important for quality

| # | Fix | Approach |
|---|-----|----------|
| 5 | **Task boundary markers** | When a new user text message arrives after a `done` action, insert a `[NEW TASK]` separator. Optionally summarize the previous task into 1-2 sentences. |
| 6 | **Screenshot compression** | Resize screenshots to max 1280px wide before storing. Convert to JPEG at 80% quality. Cuts size by ~70%. |
| 7 | **Turn metadata** | Extend `PreviousMessage` with `step_index`, `action_type`, `is_screenshot`, `token_estimate`, `pruned` fields. |
| 8 | **Async locking** | Add `asyncio.Lock` per session_id to prevent race conditions. |

### P2 — Nice to have

| # | Fix | Approach |
|---|-----|----------|
| 9 | **Mid-chain summarization** | Every 20 turns, summarize turns 1-15 into a compact text block. Keeps context relevant without losing key decisions. |
| 10 | **System prompt versioning** | Store prompt version hash with session. Detect drift and optionally re-inject updated prompt. |
| 11 | **Failed turn cleanup** | Tag turns from failed model calls. Optionally strip them before the next request. |
| 12 | **Lazy history building** | Instead of copying the full list, use a generator/view that streams turns to the message builder. |
