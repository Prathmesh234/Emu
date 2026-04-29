# Coworker-Driver Knowledge Base — Complete Summary

## Overview

This folder contains the complete specification and operational guide for implementing Emu's **co-worker mode** — a model-driven action execution system that allows the model to automate native macOS applications via `cua-driver` **without stealing focus or moving the user's cursor**.

---

## Document Inventory

| File | Lines | Purpose |
|---|---|---|
| **SPEC.md** | 1,002 | Functional specification for co-worker mode implementation (§1-15) |
| **SKILL.md** | 886 | cua-driver skill reference & operational guide (Claude Code integration) |
| **WEB_APPS.md** | 470 | Web-rendered app patterns (Chromium, Electron, Safari, Tauri) |
| **TESTS.md** | 232 | 13 natural-language test cases + failure-mode probes |
| **RECORDING.md** | 114 | Session trajectory recording & replay (demos, regression, training data) |
| **README.md** | 128 | Developer guide & implementation checklist |

---

## Key Architectural Decisions

### 1. **Fork Strategy** (Approved)
- **Forking cua-driver** (not using MCP out-of-the-box)
- Rationale:
  - Permission branding ("Emu needs..." not "cua-driver needs...")
  - Swift app issue ownership
  - Computer-use-specific optimizations
  - Faster iteration (no upstream coordination)

### 2. **Process Lifecycle**
- **Not a launchd daemon** — owned by Electron main
- **Lazy-started** on first co-worker action (not at app startup)
- **Killed on app quit** (`app.will-quit` handler)
- Spawned as child: `cua-driver mcp` (MCP stdio server)

### 3. **Action Dispatch** (Frontend)
- **Single dispatcher branch point**: `frontend/actions/executor.js`
- Branches on `store.state.agentMode` (`"coworker"` vs `"remote"`)
- Remote mode: uses existing `frontend/actions/actionProxy.js` → `cliclick`/`CGEvent`
- Coworker mode: uses new `frontend/cua-driver-commands/actionProxy.js` → cua-driver MCP

### 4. **Screenshot Source**
- Remote: `desktopCapturer` (full screen)
- Coworker: `cua:screenshot` from cua-driver (target window only, no cursor pollution)

---

## Core Invariants (Must-Know)

### The No-Foreground Contract
**User's frontmost app MUST NOT change.** This is the entire reason cua-driver exists. Every action must preserve:
- ✅ No window raising
- ✅ No cursor movement
- ✅ No focus stealing
- ✅ No Space switching

**Forbidden operations:**
- `open -a <App>` (always activates via LaunchServices)
- `osascript 'tell app "X" to activate'` (unless user explicitly asked for frontmost)
- `cliclick` (moves real cursor)
- `CGEventPost` with `cghidEventTap` (warps cursor)
- Keyboard shortcuts that semantically mean "focus here" (⌘L, ⌘⇧G)

**Allowed workaround:** `launch_app({bundle_id})` + internal `FocusRestoreGuard` clobbers foreground back to original.

### The Snapshot Invariant
**Every action MUST be bracketed by `get_window_state(pid, window_id)`:**
- **Before** — resolves fresh `element_index` values (indices cached per `(pid, window_id)`)
- **After** — verifies action actually landed (diff AX tree)

Skipping post-action snapshot → silent failures report as success (most common failure mode).

### Element Index Lifecycle
- Generated fresh on every `get_window_state` snapshot
- Keyed on `(pid, window_id)` pair
- **Don't reuse** across turns or windows
- Invalid if window closes or layout changes

---

## MCP Protocol (JSON-RPC 2.0 over stdio)

### Request/Response Shape
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "screenshot",
    "arguments": { "window_id": 2129 }
  }
}
```

### Tool Categories

**Process/App Management:**
- `launch_app({bundle_id|name, urls?})` → `{pid, windows: [{window_id, title, ...}]}`
- `list_apps()` → `{apps: [{name, pid, front_window_id, ...}]}`
- `list_windows({pid})` → `{windows: [{window_id, title, bounds, on_current_space, ...}]}`

**Snapshots:**
- `get_window_state({pid, window_id, javascript?})` → tree_markdown + screenshot + element_indices
- `screenshot({window_id?})` → PNG only

**Actions:**
- `click({pid, window_id, element_index|x,y, action?, modifiers?})`
- `double_click({pid, ...same...})`
- `right_click({pid, ...same...})`
- `type_text({pid, text, window_id, element_index?})`
- `type_text_chars({pid, text, delay_ms?})` (CGEvent Unicode)
- `press_key({pid, key, window_id?, element_index?, modifiers?})`
- `hotkey({pid, keys: ["cmd", "c"]})` (modifier combos)
- `scroll({pid, direction, amount, by, window_id?, element_index?})`
- `set_value({pid, window_id, element_index, value})`

**Browser JS:**
- `page({pid, window_id, action: "get_text"|"query_dom"|"execute_javascript", ...})`

**Recording:**
- `set_recording({enabled, output_dir})`
- `get_recording_state()`
- `replay_trajectory({dir, delay_ms?, stop_on_error?})`

---

## Behavior Matrix (Capture Modes vs Addressing)

| Capture Mode | Returns | Best For |
|---|---|---|
| **`som`** (default) | tree_markdown + screenshot | element_index + pixel fallback |
| **`ax`** | tree_markdown only | element_index only (text-heavy UIs) |
| **`vision`** | screenshot only | pixel-only / vision reasoning |

### Window State Impact

| State | `get_window_state` | AX Click | Keyboard Commit | Pixel Click |
|---|---|---|---|---|
| frontmost | ✅ | ✅ | ✅ | ✅ |
| backgrounded/visible | ✅ | ✅ | ✅ | ✅ |
| **minimized** | ✅ | ✅ | ❌ (use `set_value`) | ❌ |
| hidden | ✅ | ✅ | depends | ❌ |
| another Space | ⚠️ sparse | ✅ | ✅ | ❌ |

**Critical:** Minimized + keyboard commit = system beep. Use `set_value` or click a button instead.

---

## Web App Patterns (Chromium/Electron/Safari)

### Sparse AX Tree Population
- Chromium ships with AX disabled by default
- First `get_window_state` takes ~500ms (populates tree)
- **Retry once** if sparse — Chromium sometimes needs two calls
- If still sparse: try menu bar (`AXMenuBarItem`), cmd-k palettes, hotkeys, then pixels

### Navigate to URL
**Primary:** `launch_app({bundle_id: "com.google.Chrome", urls: ["https://…"]})`
- Fully backgrounded, zero activation
- No omnibox dance needed
- Driver catches `NSApp.activate(ignoringOtherApps:)` internally

### Tabs vs Windows
- **Tabs**: Only frontmost tab's AX tree populated; switching is visibly disruptive
- **Windows**: Independent AX trees, backgroundable, no visible switch
- **Rule**: For backgrounded multi-URL drive, open each URL in a new **window**

### Minimized Window Keyboard Commits
- `press_key` + Return: **silent no-op**, system beep
- **Fix 1**: Use `set_value({..., value: "URL"})` to write field directly
- **Fix 2**: Find a clickable button (Go, Submit) and AX-click it
- **Fix 3**: Tell user to un-minimize (last resort only)

### "Allow JavaScript from Apple Events"
- **Chrome**: Write `browser.allow_javascript_apple_events = true` to Preferences JSON (quit Chrome first)
- **Safari**: `Develop → Allow JavaScript from Apple Events` (UI automation required; defaults write broken)
- **Brave/Edge**: Same Chromium key, different path
- **Arc**: Returns no values (broken)
- **Firefox**: Not supported

---

## Common Failure Modes & Fixes

| Error | Root Cause | Fix |
|---|---|---|
| `No cached AX state for pid X window_id W` | Skipped `get_window_state` or different window_id | Call `get_window_state({pid, window_id})` first |
| `Invalid element_index N` | Index stale or out-of-range | Re-snapshot, pick fresh index |
| `window_id W belongs to pid P` | Passed window_id from different process | Use `list_windows({pid})` to enumerate correct windows |
| macOS system beep on `press_key` | Minimized window keyboard focus issue | Use `set_value` or click button instead |
| Sparse Chromium AX tree | First snapshot → tree still building | Retry `get_window_state` once |
| Chromium `right_click` → left-click | Renderer IPC limitation | Use element_index for AX-addressable, accept limit for web content |
| Canvas/viewport apps won't respond | No AX tree, per-pid events filtered | Brief frontmost activation required (carve-out) |

---

## Implementation Roadmap (from SPEC §14)

1. ✅ Install cua-driver locally, run `check_permissions`, test `cua-driver mcp`
2. 🔲 `frontend/process/cuaDriverProcess.js` — spawn + JSON-RPC pump
3. 🔲 `frontend/cua-driver-commands/index.js` + `actionProxy.js` — IPC handlers + ACTION_MAP
4. 🔲 `frontend/actions/executor.js` branch + `frontend/services/captureForStep.js`
5. 🔲 `backend/prompts/coworker_system_prompt.py` + plumbing in `build_system_prompt(agent_mode=...)`
6. 🔲 Backend: `raise_app` JSON return + `list_running_apps` tool
7. 🔲 `backend/models/response.py` — extend actions with optional `pid`/`window_id`/`element_index`
8. 🔲 `main.js` — register IPC handlers + lifecycle (start on first coworker action, kill on quit)
9. 🔲 End-to-end test (e.g., "Open Chrome, search for X" while user types elsewhere)
10. 🔲 Packaging: `extraResources` for bundled binary in `electron-builder` config

---

## Permissions (No New Grants Needed)

- **Accessibility** — already required by Emu today
- **Screen Recording** — already required by Emu today
- cua-driver runs as child of Emu.app → inherits TCC grants automatically

**Reality check during implementation:** If `check_permissions` reports denied while Emu has both grants, may need to add child binary path to AX list independently. Reuse existing permissions UI in `main.js:145-158`.

---

## Testing Strategy (TESTS.md)

### Quick Smoke (< 5 min)
1. Calculator arithmetic (launch hidden, multi-click, re-snapshot verify)
2. Finder menu (File → Recent → AX tree pagination)
3. VS Code command palette (Chromium activation, element_index click)
4. Slack channel switch (sparse tree fallback to hotkey)

### Regression Battery (~ 15 min)
Tests 1–13 covering:
- Native AppKit (Calculator, Finder, Preview, Notes, Numbers, System Settings)
- Chromium/Electron (VS Code, Slack, Linear, Superhuman)
- PWA (Google Calendar)
- Browsers (Chrome omnibox navigation)
- Multi-step flow (Calendar form filling)

### Failure-Mode Probes
- Canvas/non-AX surface (Figma) → Claude should decline pixel fallback
- Destructive action without confirmation (close window) → Claude should ask
- Autonomous launch → Claude should ask user intent first

---

## Key Files (Implementation)

### New Files to Create
- `frontend/process/cuaDriverProcess.js` (298 lines in spec §5.2)
- `frontend/cua-driver-commands/index.js` (43 lines in spec §6.4)
- `frontend/cua-driver-commands/actionProxy.js` (102 lines in spec §6.3)
- `frontend/services/captureForStep.js` (21 lines in spec §6.5)
- `backend/prompts/coworker_system_prompt.py` (46 lines in spec §7.1)
- `backend/tools/list_running_apps.py` (9 lines in spec §7.4)

### Files to Modify
- `main.js` — register IPC + lifecycle
- `frontend/actions/executor.js` — branch on `store.state.agentMode`
- `backend/prompts/system_prompt.py` — add `agent_mode` parameter
- `backend/context_manager/context.py` — pass `agent_mode` to builder (2 sites)
- `backend/tools/raise_app.py` — return JSON in coworker mode
- `backend/tools/dispatcher.py` — register `list_running_apps`, thread `agent_mode`
- `backend/models/response.py` — add optional `pid`/`window_id`/`element_index` fields

---

## Recording & Replay (RECORDING.md)

### Session Capture
```bash
cua-driver recording start ~/trajectories/run-1
# ... run workflow ...
cua-driver recording stop
```

### Turn Folder Contents
- `app_state.json` — post-action AX snapshot
- `screenshot.png` — post-action window capture
- `action.json` — tool name, args, result, timestamp
- `click.png` — screenshot with red dot at click point (click-family only)

### Replay
```bash
cua-driver replay_trajectory '{"dir":"~/trajectories/run-1","delay_ms":500}'
```

**Caveat:** element_index doesn't survive across sessions (pid/window_id changes). Replay pixel + keyboard primitives, or use as regression artifact (diff failure/success patterns).

---

## Quick Reference: The Canonical Loop

```
1. launch_app({bundle_id})
   → {pid, windows: [{window_id, title, ...}]}

2. get_window_state({pid, window_id})
   → tree_markdown + screenshot + element_indices
   → [act]  # every action uses pid + window_id + element_index

3. get_window_state({pid, window_id})  # verify
   → check AX tree diff (value changed? window created? menu collapsed?)
   → if unchanged, action failed silently — say so
```

---

## Resources

- **cua-driver repo:** https://github.com/trycua/cua/tree/main/libs/cua-driver
- **macOS internals primer:** https://github.com/trycua/cua/blob/main/blog/inside-macos-window-internals.md
- **Install cua-driver:** `https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh`
- **Dev install:** `https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install-local.sh`

---

## Status

**Documentation:** ✅ Complete
**Forking:** ✅ Approved strategy
**Implementation:** 🔲 Ready to start (follow roadmap steps 1–10)
