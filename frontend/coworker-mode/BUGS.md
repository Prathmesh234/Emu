# BUGS — Coworker mode (open)

Live-test bugs reported after the round-3 fixes. None of these have
been fixed yet — captured here so they don't get lost across context
windows.

---

## 1. `cua_double_click` is broken

The driver tool does not actually perform a double click that the
target app honours. Until it works end-to-end, **remove it from the
prompt and from the tool registry exposed to the model.** Don't
advertise broken primitives — the model will reach for them and
the task fails.

Action items:
- Drop `cua_double_click` from `COWORKER_DRIVER_TOOLS_OPENAI` in
  `backend/tools/coworker_tools.py`.
- Strip any reference to it from `coworker_system_prompt.py`.
- Remove the IPC route for `double-click` in
  `frontend/cua-driver-commands/index.js`.
- File a driver-side issue (separate) once we know whether it's an
  AX problem or an event-posting problem.

---

## 2. Cursor still glitches onto other windows when rotating apps

Even after:
- Skipping `reapplyPinAbove` when `frontmostApplication.pid != pid`
- Adding `didDeactivateApplicationNotification` to `orderOut` the overlay
- Hiding the overlay on every "wrong front pid" tick

…the user still sees the cyan cursor flash onto VS Code (and other
apps) for a millisecond when Cmd+Tabbing between apps.

Hypotheses to explore next:
- The `orderFrontRegardless()` in `show()` may fire during a glide
  (`animateAndWait`) that started while the target was frontmost
  but completed after the user already switched.
- The overlay window is `.normal` level + `.canJoinAllSpaces +
  .stationary` collection behavior. `.canJoinAllSpaces` may be
  letting the window leak across Spaces transitions and render on
  the post-switch app.
- We may need to drop the overlay to `level = below normal -1` or
  give it a target-window-tied ordering that the system itself
  reasserts on every front-app change.
- Or: drop the frontmost-pid guard and instead track the target
  *window's* `kCGWindowIsOnscreen + zIndex` and orderOut whenever
  any other app's window is above it.

Until fixed, this is the single most user-visible artefact.

---

## 3. Tool calls / step events are not streaming live to the UI

The trace lines (`[tool] cua_get_window_state ... → ...`) for
coworker mode pile up on the backend stdout in real time, but the
frontend renders them all at once at the END of the turn instead
of one-by-one as they happen.

Suspects:
- `log_and_send` may be called but the WebSocket message format
  isn't what the renderer expects in the new `cua_driver_call` /
  `raise_app` switch cases we added in `Chat.js`.
- The trace-line element may be getting appended to a detached DOM
  node (the step container) that only attaches when the step
  completes.
- Or — the WS messages ARE arriving live, but the renderer is
  buffering them until a `step` event lands (which only fires when
  the turn finishes).

Investigation: tail the WebSocket frames with the DevTools
Network → WS panel during a real run, compare timing of `[tool]`
prints (backend stdout) vs `tool_event` frames in the WS log vs
the moment the line appears in the UI.

---

## 4. Send button never converts to "Stop" while running

`syncGeneratingUI(true)` fires at the start of `respond()`, but the
button state must not be wired to it. Or the toggle hook lives in a
component that re-renders without picking up the generating flag.
User has no way to stop the agent — combined with bug 3 (no live
trace) it makes the app feel hung.

Investigation:
- `frontend/components/chrome/ChatInput.*` (or wherever the send
  button lives) — check whether it subscribes to `state.isGenerating`.
- Verify `store.setGenerating(true)` is actually called and
  rendered before the first WebSocket frame returns.
- Verify the stop click path posts to `/agent/stop` (which now
  works backend-side).

---

## 5. General UI wonkiness

A swarm of smaller issues observed in the same session:

- After WebSocket disconnect (`connection closed` in trace), the UI
  doesn't visibly reset — user sees a half-frozen state.
- `[display] session lock cleared` fires even though the user never
  finished the task. Looks like the lock is dropped on the first
  connection close, not on real `done` / `stop`.
- Plan-review pause doesn't always show a clear "approve" prompt
  in the chat panel (sometimes the chat just stops with no UI
  affordance, even though the backend logs `[plan-review] Plan
  created — pausing for user approval`).

Investigation: walk through the WS event handlers in
`frontend/pages/Chat.js` for `connection_closed`,
`plan_review_request`, `stopped`, and verify each updates the
visible UI state, not just an internal flag.

---

## Prioritisation

1. **#4 (send→stop)** — without this the user is helpless. Fix first.
2. **#3 (live trace streaming)** — confirms the agent is actually
   doing things; user trust collapses without it.
3. **#1 (drop double_click)** — trivial, a few line deletes.
4. **#2 (cursor flash)** — deeper investigation; spike before rewrite.
5. **#5 (misc UI)** — sweep last, after the above clear up.
