# Major Issues To Address

Audit of 15 sessions in `.emu/sessions/` (May 5–6, 2026, ~1000 messages total).
Focus: where the harness is *not* solving the problem and the model gets confused
or stuck — especially around the AX-tree click path. Every issue cites concrete
evidence from the conversation logs.

---

## 1. `element_index: 0 + x/y` is the single biggest failure mode (AXPress on app root)

**The bug:** When the model intends a *pixel* click, Anthropic/OpenAI providers
emit the full schema with `element_index: 0` plus real `x, y` coordinates. The
dispatcher's element-zero fallback in `backend/tools/dispatcher.py:141-169` is
*supposed* to drop `element_index` and route to the pixel path — but in practice
the call still reaches the AX path and tries `AXPress` on `element[0]` (the
`AXApplication` root), which is hard-coded to fail with macOS error
`-25206 / kAXErrorActionUnsupported`.

**Why it's the worst issue:** the model can't tell from the error message what
went wrong, so it just retries the *exact same* call. There is no harness-side
auto-correction.

**Evidence (looped 5×, only stopped by user):**
- `4b1c8afe` #102, #106, #108, #112, #114, #121, #123, #125 — same call
  `cua_click({"pid":99189,"element_index":0,"window_id":204945,"x":1004,"y":414,"action":"press",...})`
  → all 7 attempts returned `AX action AXPress failed with code -25206`. User
  finally interjected at #116: *"stop clicking the same place it is clearly not
  clickable"*. Model still ran 3 more identical clicks after that.
- `8ba7d0d9` #111–#121 — five identical `element_index:0 + x/y` calls,
  all `-25206`. Only on #125 did the model finally drop `element_index` and
  succeed.
- 34 occurrences of the pattern across all sessions
  (count from grep `element_index: 0` + nonzero `x`/`y`).

**Fixes worth considering:**
- In the driver (`ClickTool.swift:155`) treat `element_index == 0 && hasXY` as
  unambiguous pixel intent and route accordingly, instead of erroring or
  AX-pressing the application root. Belt-and-braces beyond the dispatcher.
- Surface a richer error message — "you addressed AXApplication root with
  AXPress, retry as a pixel click by removing element_index" — instead of the
  raw OS code `-25206`.
- Make the schema for `cua_click` model an OR (oneOf) so providers can't fill
  both branches at once.

---

## 2. Model retries identical failed actions in tight loops, even after explicit user stop

The harness has no "this exact tool-call+args just failed N times" detection
and no backoff guidance.

**Evidence:**
- `4b1c8afe` #102→#125: 7 identical `cua_click(... x:1004,y:414)` calls in a
  row, all -25206; user said "stop clicking the same place" at #116, model did
  3 more.
- `ded6b80b` #46–#71: model called `cua_scroll(amount:30 down)` **eight times
  in a row** while user was asking it to *click on the email* (#56, #65). It
  kept scrolling.
- `62e3c19a` #29–#38: alternating `cua_click(element_index:2)` and `(:3)` and
  back to `(:2)` after each click pulled a fresh AX tree — no progress.
- 5 sessions show ≥3 adjacent identical tool calls with same args.

**Fixes worth considering:**
- Driver/dispatcher tracks (tool, normalized-args) over the last K calls; on
  a 2nd identical failure inject a hard interrupt that says "this call has
  already failed twice with the same args; pick a different element / pixel /
  strategy before trying again."
- The "driver guidance" footer already says *"verify the visible or AX state
  changed before reporting success"* — but it isn't enforced and the model
  routinely ignores it.

---

## 3. AX tree returns 4000+ elements for Chrome, blowing context and timing out

`cua_get_window_state` on a Chrome window with a heavy DOM (Techmeme, Gmail
inbox, Calendar) produces 4000–4100 elements of `tree_markdown` — easily
many KB per call — and the *next* call to the same window can return only
77 elements with no visual change.

**Evidence:**
- `62e3c19a` #18 → 4072 elements; #32 → 77 elements (no user action between);
  #40 → 4086. Tree is unstable and bloated.
- `62e3c19a` #30: `cua_get_window_state` **timed out after 30s** because the
  Chrome AX tree was too big to walk.
- Several sessions show `tree_markdown: ""` (empty) responses when the
  scrape failed silently — the model then reuses stale element_index values.

**Why it confuses the model:**
- Element indices renumber every call, so an `element_index: 70` from turn N
  may be a different node on turn N+1.
- The model has no signal that the tree is "bad/partial"; it just sees a
  smaller tree and assumes the page changed.
- Token budget is wasted on accessibility nodes that aren't actionable
  (`AXGroup`, `AXWebArea`, dozens of empty `AXStaticText`).

**Fixes worth considering:**
- Cap `tree_markdown` at a configurable element count and surface a
  "truncated, use `query` to filter" hint when over budget.
- Stable IDs across snapshots (hash of role+title+bounds) so an
  `element_index` is reusable across `get_window_state` calls — currently
  the index cache is keyed by snapshot/turn, forcing a re-snapshot before
  every action.
- Drop AX nodes with no actions and no visible role/title from
  `tree_markdown` so the model only sees actionable nodes.
- Treat `tree_markdown == ""` as a hard error that requires retry, not a
  response to act on.

---

## 4. AX elements that don't advertise `AXPress` — silent no-ops

When the model picks an `AXGroup` / `AXWebArea` / `AXStaticText` from the tree,
the click "succeeds" but is a no-op. The driver does warn ("Element does not
advertise AXPress"), but the success ✅ emoji and "Performed AXPress" wording
swamps the warning.

**Evidence:**
- `4044b0fa` #24, `4b1c8afe` #44 #58, `ded6b80b` #29 — all hit `AXGroup` or
  `AXWebArea` and produced "⚠️ Element does not advertise AXPress (actions:
  AXShowMenu, AXScrollToVisible). Action may have been a no-op."
- 9 occurrences of "does not advertise AXPress" across logs.

**Fix:** demote these to `[cua_click error]` — currently they are scored
✅ which the model interprets as success. The warning text is below the
checkmark and gets ignored.

---

## 5. Mode confusion: function tools (`cua_*`) vs "desktop action" mode (`navigate_and_click`, `screenshot`)

The harness has two co-existing tool dialects and they are *mixed* inside a
single session. Skills like `apple-tv-f1-navigator` flip the runtime to the
"desktop action" loop where every assistant turn is `action:
navigate_and_click confidence=0.9` followed by a user `<screenshot>` reply.
This is where the worst context bloat happens.

**Evidence:**
- `4044b0fa` #38 → model called `screenshot({})` as a function tool. Got back:
  `ERROR: 'screenshot' is NOT a function tool — it is a DESKTOP ACTION. You
  called it as a function tool with arguments: {}`. The error itself is
  actionable, but the *next* user message switched modes again, leaving the
  agent confused.
- `fa51011a` #58–#112: 30+ alternating `action: navigate_and_click` /
  `<screenshot>` exchanges with effectively zero progress on the
  Cursor-marketplace task. The model has no AX tree to anchor coordinates on
  and just guesses pixels.
- `8740b607`: same loop pattern for the Apple TV F1 task — 14 screenshots
  in a row, model needed user "continue" to keep going.

**Fixes worth considering:**
- Pick one dialect per session and stick to it. If a skill needs the
  screenshot-only path, it should disable the `cua_*` toolset at the same time
  so the model can't accidentally call `screenshot({})`.
- When in screenshot-loop mode, summarize prior screenshots in text and
  drop the bytes from context — currently every step bloats prompt length
  by another full-image base64.

---

## 6. JavaScript via Apple Events is rejected → `cua_page` execute_javascript broken on Brave/Chrome out of the box

`cua_page(action: "execute_javascript", ...)` returns:
`'Google Chrome' rejected the JavaScript execution — 'Allow JavaScript from
Apple Events' is not enabled.` This is a hard wall every time the model tries
to programmatically scrape a webpage.

**Evidence:** `3feafb2e` #48, `8ba7d0d9` #20 #74 — every JS-execution attempt
fails until the user manually enables the toggle.

**Fixes worth considering:**
- Auto-enable the Chrome/Brave preference (it's a `defaults write`) at first
  launch, gated by the same user_approved flow we already use for
  `bring_app_frontmost`.
- Failing that, when the model gets this error, the harness should
  programmatically prompt the user to flip the setting *once* and remember
  the answer instead of failing every page request.

---

## 7. `cua_get_window_state` screenshot fails when the window is on another Space (`Failed to start stream due to audio/video capture failure`)

After `cua_launch_app`, the new window often lands on a different macOS Space
(`is_on_screen: false`, `on_current_space: false`). ScreenCaptureKit then
refuses to start a stream and the model gets:
`Screenshot failed: capture failed: Failed to start stream due to audio/video
capture failure`. The model interprets this as a permission problem and runs
`cua_check_permissions` (which says "granted"), going in circles.

**Evidence:**
- `4b1c8afe` #18 #20 #24 #28 — four consecutive screenshot failures right
  after `cua_launch_app` until user `bring_app_frontmost` was used.
- 8 sessions hit this error at least once.

**Fixes worth considering:**
- `cua_launch_app` should follow with an automatic `bring_app_frontmost`
  (already user-approved on prior call) so the captured window is on the
  current Space.
- The error message is misleading — "audio/video capture failure" suggests
  Screen Recording perms; it's actually "the window you asked for is not on
  this Space". Rewrite the error to point at the Space/visibility cause.

---

## 8. Daemon connection drops mid-task with no auto-recovery

`emu-cua-driver` is started by Electron (per repo memory) but if it crashes
the model just sees `daemon unavailable: Connection refused` for every call
until the user restarts the app.

**Evidence:**
- `3feafb2e` #58–#67 — three consecutive daemon-refused errors, model gave
  up: *"Blocked: the Emu CUA driver daemon just went down… please restart
  the EmuCuaDriver daemon"*.
- `62e3c19a` #30: `cua_get_window_state` timed out after 30s, then the next
  call worked — implies the daemon hung.

**Fix:** The Electron-side `EmuCuaDriverProcess` should auto-restart the
daemon on connection-refused and surface a soft "retried" notice instead of
killing the task.

---

## 9. Browser-default mismatch: user says Chrome, model launches Brave

Pure prompt-following error, but it costs an extra round-trip every time.

**Evidence:**
- `3feafb2e` #19 user: *"use chrome"* — agent had launched Brave.
- `8ba7d0d9` #83 user: *"nice can you open gmail on chrome"* — agent had
  used Brave for the previous step.

**Fix:** the system prompt / coworker-mode tooling should default to Chrome
when the user says "Chrome" explicitly, and the planner should record the
chosen browser in the plan so a later step doesn't drift.

---

## 10. "PLAN APPROVED" auto-injection pollutes context

Every time `update_plan` runs, the system injects a synthetic user message:
`[PLAN APPROVED] The user has accepted the plan. Proceed with execution —
take a screenshot to orient yourself and begin from step 1.`

**Evidence:** 21 occurrences across sessions. In `3799f03d` the *exact same*
message was injected at #4 and again at #44 with no user input in between.

**Effect:** the model treats every plan update as a fresh "start from step 1"
trigger and re-runs `cua_list_windows` / `use_skill(...)` from scratch.

**Fix:** Inject the PLAN APPROVED message exactly once per plan-version, not
per `update_plan` call. After the first approval, subsequent edits should be
silent.

---

## 11. Skills are reloaded on every session start, eating context

`use_skill("google-chrome")`, `use_skill("gmail")`, `use_skill("web-search")`
are loaded back-to-back at session start and re-loaded on plan re-renders.

**Evidence:**
- `3799f03d` #5–#10 — chrome + gmail + web-search loaded in 3 calls before
  the model has even taken a screenshot.
- 41 `use_skill` calls across all sessions; same skills re-loaded mid-task.

**Fix:** Cache loaded skills in the system prompt (or in a short header) and
suppress repeat `use_skill` returns within a session. Surface a "skill
already loaded" no-op result.

---

## 12. Empty-arg tool calls on the AX path

The model occasionally drops the required `pid`/`window_id`:
- `4044b0fa` #62 `cua_get_window_state({})` → `Missing required integer
  field pid.`
- `4044b0fa` #74 `cua_click({})` → `Missing required integer field pid.`

**Fix:** dispatcher should fall back to the most-recent (pid, window_id) pair
from `get_window_state` if missing, instead of erroring out — or attach
"last-known target" to the system prompt so the model has it to fill in.

---

## 13. "Click on the email" → model scrolls instead

Symptom of #2 (no diff between tool-call intent and outcome) but worth
calling out as a UX issue. When a user explicitly says *click*, the model
should not respond with a `cua_scroll` chain.

**Evidence:** `ded6b80b` #56 user: "try to click on the email first and then
scroll" → agent did 4 scrolls and 0 clicks. #65 user: "click on the email" →
3 more scrolls, no click.

**Fix:** add to system prompt: when the most recent user message contains a
verb that maps to a click (`click`, `open`, `select`, `tap`), the next
action MUST be a click; if no click target is identifiable, ask the user
rather than substituting `scroll`.

---

## 14. Verify-after-action is advice, not enforcement

Every successful tool call ends with: *"A successful tool result only means
the input was posted/accepted; verify the visible or AX state changed
before reporting success."*

The model reads this 53× across the logs and ignores it 53× —
proceeds to the next action without a verifier `get_window_state`.

**Fix:** make this a hard step. After `cua_click` on a clickable element,
the harness can automatically diff the next AX snapshot and inject a
"⚠️ click had no observable effect" turn that the model must address before
its next action.

---

## 15. Session-file resume is brittle

`5741ca75` ("continue, use session files") — the model couldn't find the
prior session's notes. It tried `read_session_file("hn_top_blog_posts.md")`
and got "File not found", then ran `find` / `grep` over `.emu/sessions/`
manually. User had to push: *"there should be 100% search for the session
files"*.

**Fix:** the resume flow should auto-load the prior day's `plan.md` +
session artifact list before the model's first turn, not after the model
fumbles for it.

---

## Quick-impact prioritization

If you can only fix five things, fix these first (in order):

1. **`element_index:0 + x/y` AXPress on root** — single largest cause of
   stuck loops and user "stop" interventions.
2. **No retry-budget / loop detection** — converts every other bug into a
   runaway failure mode.
3. **AX tree size + index instability** — root cause of stale-index clicks
   and the 30-second timeouts on Chrome.
4. **Screenshot fails on off-Space windows after `cua_launch_app`** —
   misleading error makes model spin on permissions.
5. **Mode-confusion between `cua_*` and screenshot-loop dialect** —
   converts skill-led tasks into 30-screenshot, no-progress sessions.
