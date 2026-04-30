# Emu-Driver Integration Plan — End-to-End

**Goal:** Wire the forked `emu-cua-driver` Swift binary (at `frontend/coworker-mode/emu-driver/`) into Emu's coworker mode, end-to-end, so the model can drive native macOS apps in the background while the user keeps focus.

This is the canonical implementation roadmap. It supersedes the loose checklists in `coworker-driver/SPEC.md §14`, `coworker-driver/SUMMARY.md`, and `frontend/COWORKER_MODE_SETUP.md`. Status flags below are reconciled against the current tree on `claude/macos-linux-compatibility-Kmd2Z`.

---

## 0. Current State Snapshot

### ✅ Already in place
| Layer | Artifact | Notes |
|---|---|---|
| Fork | `frontend/coworker-mode/emu-driver/` | Separate git repo, upstream `trycua/cua` tracked. 172 files copied. |
| Driver binary | `emu-cua-driver` / `EmuCuaDriver.app` | Phase 1 complete: product/app/runtime surfaces are Emu-branded while Swift target/module names stay upstream-compatible. |
| Frontend process | `frontend/process/EmuCuaDriverProcess.js` | Spawn + JSON-RPC stdio pump, lifecycle stubs, expects binary named `emu-cua-driver`. |
| Frontend IPC | `frontend/cua-driver-commands/{index.js,actionProxy.js}` | `emu-cua:*` channels registered, `ACTION_MAP` covers click family + scroll + type + hotkey + screenshot + window-state + launch + list-apps. |
| Executor branch | `frontend/actions/executor.js` | Branches on `store.state.agentMode === 'coworker'`. |
| Main process | `main.js` | Loads `EmuCuaDriverProcess`, registers IPC, calls `.stop()` on `will-quit`. |
| Mode toggle | `frontend/state/store.js`, `frontend/components/chrome/WindowHeader.js`, `frontend/services/api.js` | Existing toggle defaults to `"coworker"`, persists to `localStorage`, locks while generating, and sends `agent_mode` in `/agent/step`. **Do not redesign.** |
| Backend request | `backend/models/request.py` | `agent_mode: Literal["coworker","remote"]` field, default `"coworker"`. |
| Backend context | `backend/context_manager/context.py` | `set_agent_mode()` + propagation to `AgentRequest.agent_mode`. |
| Docs | `coworker-driver/SPEC.md`, `SKILL.md`, `WEB_APPS.md`, `TESTS.md`, `RECORDING.md`, `emu-driver/UPSTREAM_CHANGES.md` | Complete; repo/fork operations are consolidated into `UPSTREAM_CHANGES.md`. |

### 🔲 Missing / Incomplete
| Layer | Gap |
|---|---|
| Lazy start | `main.js` claims "emu-cua-driver is lazy-started on first co-worker action" but no code path actually calls `emuCuaDriverProcess.start({ app })`. IPC will fail with `emu-cua-driver not running`. |
| Backend prompt | `backend/prompts/system_prompt.py` has no `agent_mode` parameter. `emu_coworker_system_prompt.py` doesn't exist. The model is told nothing about the new tool surface. |
| Backend tools | `raise_app.py` returns plain strings (no `{pid, windows: [...]}`) — coworker mode needs structured output to seed `pid`/`window_id`. `list_running_apps` tool not created. `dispatcher.py` doesn't register it. |
| Action model | `backend/models/actions.py` `Action` has no `pid`, `window_id`, or `element_index` fields. Frontend `actionProxy` reads them but model can never populate them. |
| Capture path | `frontend/services/captureForStep.js` not created. Per-step screenshots in coworker mode should come from `emu-cua:screenshot` (target window only), not `desktopCapturer`. |
| MCP handshake | `EmuCuaDriverProcess.start()` does not send MCP `initialize`; some servers tolerate this, but the spec requires the initialize envelope before `tools/call`. |
| Packaging | `electron-builder` config has no `extraResources` entry for the bundled `emu-cua-driver` binary. |
| Permissions | No coworker-specific check; relies on Emu's existing AX/Screen Recording grants inheriting to the child. Untested. |
| Tests | `Tests/integration/*` exists in fork but no Emu-side smoke test ties the loop together. |

---

## 1. Architecture Recap (Authoritative)

```
┌─────────────────────────── Electron main ───────────────────────────┐
│                                                                     │
│  EmuCuaDriverProcess  ── spawn ──▶  emu-cua-driver mcp  (stdio)     │
│       ▲                                  │ (JSON-RPC 2.0)           │
│       │ callTool(name, args)             ▼                          │
│       │                            macOS AX / SkyLight / CGEvent    │
│       │                                                             │
│  ipcMain.handle('emu-cua:*')  ◀── IPC ◀── renderer                  │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
┌─────────────────────── Renderer (Chat page) ────────────────────────┐
│  executor.js ──▶ cua-driver-commands/actionProxy.js                 │
│       │            (ACTION_MAP keyed by action.type)                │
│       │                                                             │
│       └─▶ POST /action/complete to backend                          │
└─────────────────────────────────────────────────────────────────────┘
                                   ▲
┌──────────────────────────── Backend ────────────────────────────────┐
│  AgentRequest.agent_mode = "coworker"                               │
│  build_system_prompt(agent_mode="coworker") ──▶ coworker prompt     │
│  Tool dispatcher: raise_app (JSON), list_running_apps (new)         │
│  Action model: pid, window_id, element_index optional fields        │
└─────────────────────────────────────────────────────────────────────┘
```

**Core invariants** (do not violate during implementation):
- No foreground change. Never call `open -a`, `osascript … activate`, `cliclick`, or `CGEventPost(.cghidEventTap)` from coworker paths.
- Every action must be bracketed by `get_window_state(pid, window_id)` (the model's responsibility, but the prompt must say so).
- `element_index` is per `(pid, window_id)`, generated fresh each snapshot. Never reuse across turns.

---

## 2. Phases and Deliverables

The plan is split into **8 phases**. Phases 1–3 are blockers (binary + branding + lazy start). Phases 4–6 light up the model surface. Phase 7 is QA. Phase 8 is packaging/release.

### Phase 1 — Build & Brand the Binary
**Status:** ✅ Finished.

**Outcome:** `~/.local/bin/emu-cua-driver` exists after `scripts/install-local.sh`, runs like the upstream `cua-driver` command, and advertises Emu runtime branding.

1.1 Binary/product rename
- `frontend/coworker-mode/emu-driver/Package.swift`: executable product is now `emu-cua-driver`.
- Swift target/module names intentionally remain upstream-compatible: `CuaDriverCore`, `CuaDriverServer`, and `CuaDriverCLI`. This is deliberate to minimize merge conflicts when pulling from `trycua/cua`.
- CLI command name is now `emu-cua-driver`.

1.2 App/runtime identity
- App bundle output is now `EmuCuaDriver.app`.
- Bundle identifier is now `com.emu.cuadriver`.
- Bundle executable is now `emu-cua-driver`.
- MCP `initialize` server identity reports `serverInfo.name = "emu-cua-driver"`.
- Daemon isolation paths now use `~/Library/Caches/emu-cua-driver` and `emu-cua-driver.sock` / `.pid` / `.lock`, preventing accidental connection to an upstream `cua-driver serve` daemon.

1.3 Branding and user-facing copy
- Permission UI and key CLI/server messages now use Emu-specific names.
- Config/logging/telemetry/recording subsystems now use Emu identity where relevant.
- Telemetry install recording now respects the opt-out path instead of preserving upstream's one-time bypass behavior.

1.4 Build/install/release scripts
- `scripts/build-app.sh` produces `.build/EmuCuaDriver.app/Contents/MacOS/emu-cua-driver`.
- `scripts/install-local.sh` installs `/Applications/EmuCuaDriver.app` and symlinks `~/.local/bin/emu-cua-driver`.
- `scripts/install.sh`, `scripts/uninstall.sh`, `scripts/test.sh`, and `scripts/build/build-release-notarized.sh` use Emu binary/app/package names.
- Integration test defaults now point at Emu build paths.

1.5 Upstream-sync documentation
- `frontend/coworker-mode/emu-driver/UPSTREAM_CHANGES.md` now documents the Phase 1 divergence.
- Added an upstream pull caution checklist covering runtime names, high-conflict files, daemon/TCC identity, and post-sync smoke commands.

1.6 Validation summary
- `swift build -c debug --product emu-cua-driver` succeeded.
- `swift build -c release --product emu-cua-driver` succeeded.
- `scripts/build-app.sh debug` succeeded.
- Installed command smoke succeeded:
  - `emu-cua-driver --version` → `0.0.13`
  - `emu-cua-driver list-tools` lists the expected tools.
- App bundle identity verified:
  - `CFBundleIdentifier` → `com.emu.cuadriver`
  - `CFBundleExecutable` → `emu-cua-driver`
- MCP initialize smoke returned `serverInfo.name = "emu-cua-driver"`.
- `swift test` is blocked by the local Swift toolchain failing before tests run with `no such module 'XCTest'`; product/app builds and CLI/MCP smoke checks are green.

### Phase 2 — Lazy Start Lifecycle
**Status:** ✅ Finished.
**Outcome:** First coworker action spawns the child; quit kills it cleanly.

2.1 `EmuCuaDriverProcess.callTool` — auto-start on first call if `_child` is null. Pass `app` reference (capture once at registration in `main.js`).
2.2 Add the MCP `initialize` handshake from the functional spec before the first `tools/call`:
```json
{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"emu"}}}
```
2.3 Register an IPC channel `emu-cua:ensure-started` for renderer-side eager start when switching to coworker mode.
2.4 Add a startup mutex (`_starting Promise`) so concurrent first actions do not spawn duplicate children.
2.5 Crash behavior must match the spec: clear/reject pending calls immediately; **do not restart in the exit handler**, but allow the next `callTool()` to lazy-start a fresh process.
2.6 First coworker run should call `check_permissions`; if denied, surface the existing permissions UI/CTA rather than creating a new permissions surface.
2.7 Verify `app.will-quit` `.stop()` actually fires before Electron exits.

### Phase 3 — Mode Toggle Integration (Mostly Existing)
**Outcome:** Existing mode toggle remains unchanged visually, but coworker startup and backend state are reliable.

3.1 Keep `frontend/state/store.js` as-is unless bugs are found: it already has `agentMode`, defaults to `"coworker"`, persists `emu-agent-mode`, and validates allowed values.
3.2 Keep `frontend/components/chrome/WindowHeader.js` as-is unless bugs are found: the spec explicitly says the existing toggle should not be redesigned and should lock while generating.
3.3 Keep `frontend/services/api.js#postStep()` sending `agent_mode`.
3.4 On switching to coworker, optionally call `emu-cua:ensure-started` so missing-binary/permission errors surface before a model step.
3.5 Do **not** add extra trace tags, overlay UI, menu-bar pills, or global hotkeys. The functional spec says the chat UI, side-panel trace cards, border window, Stop button, and session/WebSocket plumbing stay identical between modes.

### Phase 4 — Backend Prompt Plumbing
**Outcome:** Model receives a coworker-specific system prompt with the correct tool surface and invariants.

4.1 `backend/prompts/emu_coworker_system_prompt.py` — new file, ~50 lines. Must include:
   - The no-foreground contract.
   - The snapshot invariant (`get_window_state` before/after).
   - Element-index lifecycle.
   - Tool catalog: `launch_app`, `list_apps`, `list_windows`, `get_window_state`, `screenshot`, `click`, `type_text`, `press_key`, `hotkey`, `scroll`, `set_value`, plus the action-side `raise_app` and `list_running_apps`.
   - Required action fields: `pid`, `window_id`, `element_index` (or pixel fallback).

4.2 `backend/prompts/system_prompt.py` — add `agent_mode: Literal["coworker","remote"] = "remote"` parameter to `build_system_prompt()`. When `"coworker"`, delegate to `build_emu_coworker_system_prompt()` (similar to existing `bootstrap_mode` / `hermes_setup_mode` pattern at lines 41–53).

4.3 `backend/context_manager/context.py` — at every `build_system_prompt(...)` call site (grep for them), thread `agent_mode=self._agent_mode.get(session_id, "coworker")`.

4.4 `backend/prompts/__init__.py` — confirm no import changes are required. If any tests/import paths expect prompt builders to be re-exported, add the new builder there.

4.5 Sanity test: snapshot the rendered prompt for both modes; diff should only differ in the mode-specific block.

### Phase 5 — Backend Tools (raise_app + list_running_apps)
**Outcome:** Model has structured discovery primitives that return real `pid`/`window_id` values.

5.1 `backend/tools/raise_app.py` — branch on `agent_mode`:
   - `"remote"`: keep current osascript `activate` behavior, return string.
   - `"coworker"`: **do not use `osascript activate`**. Shell out to `emu-cua-driver call launch_app '{"name":"..."}'` (or call MCP via a thin Python helper). Return JSON: `{"pid": ..., "windows": [{"window_id": ..., "title": ...}, ...]}`. This preserves the no-foreground contract; do not copy the spec skeleton's remote-mode osascript behavior into the coworker path.

5.2 `backend/tools/list_running_apps.py` — new, ~10 lines. Wraps `emu-cua-driver call list_apps`. Returns `{"apps": [{"name", "pid", "front_window_id", "bundle_id"}, ...]}`.

5.3 `backend/tools/dispatcher.py`:
   - Import `handle_list_running_apps`.
   - Register name `list_running_apps` in the `elif name == ...` chain.
   - Update the tool catalog string at line ~178 to advertise it.
   - Thread `agent_mode` through `dispatch_tool(...)` so `raise_app` can branch.

5.4 Decide whether to use a Python MCP client or shell out. Recommendation: shell out via `emu-cua-driver call <tool> <json-args>` for v1 (simpler; the Swift CLI already exposes this in `CallCommand.swift`).

### Phase 6 — Action Model + Capture Path
**Outcome:** Model can emit `{type, pid, window_id, element_index}` and screenshots flow from the target window, not the whole desktop.

6.1 `backend/models/actions.py` — extend `Action`:
```python
pid: Optional[int] = Field(default=None, description="Target process ID (coworker mode)")
window_id: Optional[int] = Field(default=None, description="Target window ID (coworker mode)")
element_index: Optional[int] = Field(default=None, description="AX element index from last get_window_state (coworker mode)")
```
Validate that at least one of `(element_index, coordinates)` is present for click-family actions when `agent_mode == "coworker"` (cross-validator on the response, not the action itself, since Action doesn't know mode).

6.2 `frontend/services/captureForStep.js` — new, ~25 lines. Single function `captureForStep({pid, windowId})`:
   - If `store.state.agentMode === 'coworker'` and `pid && windowId`, invoke `emu-cua:screenshot` and return base64.
   - Else fall through to the existing `desktopCapturer` path.

6.3 Wire `captureForStep` into the per-step screenshot site (currently in `pages/Chat.js` or wherever `frontend/actions/screenshot.js` is invoked between steps).

6.4 `frontend/cua-driver-commands/index.js` — ensure `emu-cua:screenshot` extracts image content blocks and returns `{success, base64, output}`. The spec expects MCP screenshot results to contain `{type:"image", data:<base64>}` blocks, not only text summaries.

6.5 `backend/models/response.py` — confirm/extend that the response object surfaces `pid`/`window_id` so the frontend can pass them to `captureForStep`. (Likely already plumbed via `Action`; double-check.)

6.6 Action-set audit against the spec:
- Supported in v1: `screenshot`, `left_click`, `right_click`, `double_click`, `navigate_and_click` folded to click, `navigate_and_right_click` folded to right-click, `scroll`, `type_text`, `key_press`/hotkey, `wait`, `shell_exec`, `memory_read`, `done`.
- Deferred/no-op: `triple_click`, `navigate_and_triple_click`, `mouse_move`, `relative_mouse_move`, `drag`, `relative_drag`, `get_mouse_position`.
- `horizontal_scroll` is internally inconsistent in the spec: §2 lists it as a non-goal, while §6.1 maps it to `scroll` with a horizontal direction. Current code maps it. Before QA, decide whether to keep that implementation or intentionally return the deferred/no-op path.

### Phase 7 — Permissions + End-to-End Smoke
**Outcome:** Real workflows run successfully on a clean macOS install.

7.1 Permission inheritance check
- After Emu has AX + Screen Recording grants, run a coworker click. If `emu-cua-driver` reports denied, add the resolved binary path to AX list automatically (one-shot prompt in `EmuCuaDriverProcess.start` failure path, similar to existing `permissions:open` IPC at `main.js:152`).

7.2 Smoke tests (manual, captured as `coworker-driver/TESTS.md` items 1–4):
- **T1 Calculator** — `launch_app("Calculator")`, click 2, click +, click 3, click =, verify display.
- **T2 Finder** — `launch_app("Finder")`, click File menu, navigate Recent. Verify menu pagination via element_index.
- **T3 VS Code** — Open Cmd-Shift-P palette via hotkey; click an entry. (Chromium AX retry.)
- **T4 Chrome navigation** — `launch_app({bundle_id:"com.google.Chrome", urls:[...]})`. Verify no foreground steal.

7.3 Failure-mode probes:
- Minimized window keyboard commit → must use `set_value` not `press_key`.
- Sparse Chromium tree → retry once.
- Canvas app (Figma) → expect graceful decline.

7.4 Regression: with `agentMode='remote'`, full existing test suite still green.

7.5 Stop-button behavior requires no new backend endpoint. `POST /agent/stop` remains the single stop path. In-flight `emu-cua-driver` calls may complete before the agent loop observes stop, matching today's in-flight `cliclick` semantics.

7.6 Full functional-spec regression after smoke: run through `frontend/coworker-driver/TESTS.md` and document the result matrix in that file (or a dedicated test-results section), including the 13 natural-language app tests and the failure-mode probes.

### Phase 8 — Packaging & Release
**Outcome:** A built Emu DMG includes `emu-cua-driver`; first-run users can use coworker mode without separate installs.

8.1 `electron-builder` config — add `extraResources`:
```json
"extraResources": [
  { "from": "frontend/coworker-mode/emu-driver/.build/release/emu-cua-driver",
    "to": "emu-cua-driver/emu-cua-driver" }
]
```
8.2 Pre-build hook: ensure the fork's spec-compatible build command (`npm run build`, wrapping `swift build -c release` if needed) runs before `electron-builder pack`. Add an Emu-root `npm run build:driver` script that delegates to it.
8.3 Notarization: ad-hoc sign the bundled `emu-cua-driver` for v1 (matches upstream); defer hardened/notarized signing to Phase 2 (UPSTREAM_CHANGES §4).
8.4 `EmuCuaDriverProcess._resolveBinary` priority order is already correct (bundled → `~/.local/bin` → fallback). Verify the bundled path matches the `extraResources` `to:`.
8.5 First-run UX: if `_resolveBinary` returns null and user toggles coworker, show a dialog with "Build dev binary" or "Install via curl" links pointing at `frontend/coworker-mode/emu-driver/scripts/install-local.sh`.
8.6 Document helper ownership for dev/release:
- Emu memory daemon remains launchd-owned and unchanged.
- `emu-cua-driver mcp` is Electron-main-owned, lazy-started, app-lifetime only.
- `emu-cua-driver serve` exists but is optional and **not used by Emu** because the long-lived MCP child already preserves app/window state.
8.7 Public-DMG deferred entitlements from the spec: when hardened runtime/notarization is enabled, re-sign embedded `emu-cua-driver` with `disable-library-validation`, `allow-dyld-environment-variables`, and `automation.apple-events` entitlements before sealing the DMG.

---

## 3. Critical Open Questions (resolve before Phase 4)

1. **Binary invocation surface for backend tools** — Python MCP client vs shelling out to `emu-cua-driver call`? *Default: shell out for v1.*
2. **Mode default in fresh sessions** — spec and current code default to `"coworker"`. Do not flip this in implementation unless the product decision changes.
3. **Single child vs per-session children** — `EmuCuaDriverProcess` keeps one global child. Is that fine for multiple concurrent sessions? *Yes for v1; cua-driver is stateless per call. Element-index cache is per `(pid, window_id)` so cross-session collisions are unlikely.*
4. **`element_index` validation** — should backend reject `Action` with `element_index` set but no `pid`/`window_id`? *Yes; add a pydantic root validator in 6.1.*
5. **Horizontal scroll conflict** — resolve the spec's §2 vs §6.1 disagreement before final QA: keep current mapped implementation or treat as deferred/no-op.

---

## 4. Risk Register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Swift product rename breaks upstream cherry-picks | Med | Keep core/server module names; only the CLI target/product renamed. Document in UPSTREAM_CHANGES. |
| AX inheritance from Emu.app to child fails | Med | Phase 7.1 covers detection + auto-add; reuse existing AX-grant UI. |
| Chromium sparse AX trees on first call | High | Already handled in skill docs (retry once); make sure prompt mentions it. |
| Lazy-start race when two actions fire concurrently | Low | `_child` guard already exists; add a startup mutex (`_starting Promise`) to coalesce. |
| Backend `raise_app` JSON parsing fragile | Med | Wrap CLI call with structured error; fall back to current osascript path if `emu-cua-driver` missing. |
| User toggles to coworker before binary exists | High | Phase 8.5 first-run dialog. |
| MCP server rejects missing initialize handshake | Med | Phase 2.2 sends `initialize` before any tool call. |
| UI drift from functional spec | Med | Phase 3.5 and §5 freeze all non-toggle UI; no trace tags/overlays/menu-bar additions. |

---

## 5. Out of Scope (Phase 2, deferred)

- Notarized signing of bundled binary.
- Trajectory recording UI surface (`set_recording`, `replay_trajectory`).
- Drag / triple-click in coworker mode (currently no-op in `ACTION_MAP`).
- Relative move/drag and get-mouse-position in coworker mode.
- Linux compatibility for coworker mode (cua-driver is macOS-only by design).
- Multi-display targeting beyond what cua-driver already supports.

---

## 6. Done Definition

The integration is "done" when **all** of these are true:

- [ ] `npm start` from a clean checkout produces an Emu that, with mode toggle set to `coworker`, can run T1–T4 in §7.2 without ever stealing foreground.
- [ ] Toggling back to `remote` runs the existing test suite unchanged.
- [ ] Quitting Emu cleanly terminates `emu-cua-driver` (verified via `pgrep`).
- [ ] Built DMG includes `emu-cua-driver` and a fresh-install user (no `~/.local/bin/emu-cua-driver`) can use coworker mode after granting AX + Screen Recording.
- [ ] `UPSTREAM_CHANGES.md` lists every Emu divergence with commit hashes.
- [ ] `coworker-driver/TESTS.md` results documented for the released build.

---

## 7. References

- Spec: `frontend/coworker-driver/SPEC.md` (§14 = roadmap)
- Skill: `frontend/coworker-driver/SKILL.md`
- Tests: `frontend/coworker-driver/TESTS.md`
- Web apps: `frontend/coworker-driver/WEB_APPS.md`
- Fork operations and divergences: `frontend/coworker-mode/emu-driver/UPSTREAM_CHANGES.md`
- Upstream: https://github.com/trycua/cua/tree/main/libs/cua-driver
- macOS internals: https://github.com/trycua/cua/blob/main/blog/inside-macos-window-internals.md
