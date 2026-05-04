# Emu-Driver Integration Plan — End-to-End

**Goal:** Wire the forked `emu-cua-driver` Swift binary (at `frontend/coworker-mode/emu-driver/`) into Emu's coworker mode, end-to-end, so the model can drive native macOS apps in the background while the user keeps focus.

This is the canonical implementation roadmap. It supersedes the old loose setup and summary checklists; stale standalone setup/summary docs were removed after the current README files were updated. Status flags below are reconciled against the current tree on `claude/macos-linux-compatibility-Kmd2Z`.

---

## 0. Current State Snapshot

### ✅ Already in place
| Layer | Artifact | Notes |
|---|---|---|
| Fork | `frontend/coworker-mode/emu-driver/` | Separate git repo, upstream `trycua/cua` tracked. 172 files copied. |
| Driver binary | `emu-cua-driver` / `EmuCuaDriver.app` | Phase 1 complete: product/app/runtime surfaces are Emu-branded while Swift target/module names stay upstream-compatible. |
| Frontend process | `frontend/process/EmuCuaDriverProcess.js` | Starts Electron-owned `emu-cua-driver serve --no-relaunch`, configures cursor/permissions, and exposes driver calls for renderer IPC. |
| Frontend IPC | `frontend/cua-driver-commands/index.js` | `emu-cua:*` channels registered for target-window capture and operator/renderer IPC helpers. Interactive coworker work is dispatched server-side through backend `cua_*` function tools. |
| Executor branch | `frontend/actions/executor.js` | Branches on `store.state.agentMode === 'coworker'`. |
| Main process | `main.js` | Loads `EmuCuaDriverProcess`, registers IPC, calls `.stop()` on `will-quit`. |
| Mode toggle | `frontend/state/store.js`, `frontend/components/chrome/WindowHeader.js`, `frontend/services/api.js` | Existing toggle defaults to `"coworker"`, persists to `localStorage`, locks while generating, and sends `agent_mode` in `/agent/step`. **Do not redesign.** |
| Backend request | `backend/models/request.py` | `agent_mode: Literal["coworker","remote"]` field, default `"coworker"`. |
| Backend context | `backend/context_manager/context.py` | `set_agent_mode()` + propagation to `AgentRequest.agent_mode`. |
| Capture path | `frontend/services/captureForStep.js`, `frontend/cua-driver-commands/*` | Coworker per-step capture prefers target-window screenshots via `emu-cua:screenshot`, with desktop capture fallback. |
| Permissions UX | `main.js`, `preload.js`, `frontend/components/chrome/PermissionsCard.js` | Missing TCC grants trigger a non-blocking Emu-styled card with direct System Settings links and polling rechecks. |
| Packaging config | `package.json` | `build:driver`, `pack`, and `dist` scripts build the release driver first; electron-builder copies it to `Resources/emu-cua-driver/emu-cua-driver`. |
| Docs | `coworker-driver/README.md`, `SKILL.md`, `WEB_APPS.md`, `TESTS.md`, `RECORDING.md`, `emu-driver/UPSTREAM_CHANGES.md` | Complete; repo/fork operations are consolidated into `UPSTREAM_CHANGES.md`. |

### 🔲 Remaining / Manual validation
| Layer | Gap |
|---|---|
| Phase 7 smoke | T1–T4 and failure probes still need to be run on a clean macOS install with real TCC prompts and documented in `frontend/coworker-driver/TESTS.md`. |
| Release signing | Public-DMG hardened runtime / notarization entitlements remain intentionally deferred; current pack flow uses ad-hoc signing for v1 dev packaging. |

---

## 1. Architecture Recap (Authoritative)

```
┌─────────────────────────── Electron main ───────────────────────────┐
│                                                                     │
│  EmuCuaDriverProcess  ── spawn ──▶  emu-cua-driver serve --no-relaunch │
│       ▲                                  │ daemon socket / CLI call │
│       │ callTool(name, args)             ▼                          │
│       │                            macOS AX / SkyLight / CGEvent    │
│       │                                                             │
│  ipcMain.handle('emu-cua:*')  ◀── IPC ◀── renderer                  │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
┌─────────────────────── Renderer (Chat page) ────────────────────────┐
│  executor.js rejects non-done coworker Action JSON                  │
│       │                                                             │
│       └─▶ POST /action/complete to backend for done/failure feedback │
└─────────────────────────────────────────────────────────────────────┘
                                   ▲
┌──────────────────────────── Backend ────────────────────────────────┐
│  AgentRequest.agent_mode = "coworker"                               │
│  build_system_prompt(agent_mode="coworker") ──▶ coworker prompt     │
│  Tool dispatcher: raise_app (JSON), list_running_apps (new)         │
│  Tool args carry pid/window_id/element_index for cua_* calls        │
└─────────────────────────────────────────────────────────────────────┘
```

**Core invariants** (do not violate during implementation):
- No foreground change. Never call `open -a`, `osascript … activate`, `cliclick`, or `CGEventPost(.cghidEventTap)` from coworker paths.
- Every action must be bracketed by `get_window_state(pid, window_id)` (the model's responsibility, but the prompt must say so).
- `element_index` is per `(pid, window_id)`, generated fresh each snapshot. Never reuse across turns.

---

## 2. Phases and Deliverables

The plan is split into **9 phases**. Phases 1–3 are blockers (binary + branding + lifecycle). Phases 4–6 light up the model surface. Phase 7 is QA. Phase 8 is permissions UX. Phase 9 is packaging/release.

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
**Status:** ✅ Finished.
**Outcome:** Existing mode toggle remains unchanged visually, but coworker startup and backend state are reliable.

3.1 `frontend/state/store.js` kept as-is: `agentMode` defaults to `"coworker"`, persists to `emu-agent-mode`, validates allowed values via `AGENT_MODES`.
3.2 `frontend/components/chrome/WindowHeader.js` kept as-is visually: the radiogroup toggle locks via `setModeDisabled(true)` during generation (driven from `Chat.syncGeneratingUI`).
3.3 `frontend/services/api.js#postStep()` kept sending `agent_mode` in the `/agent/step` body.
3.4 Eager startup in `main.js` (mode-independent): right after registering the `emu-cua:ensure-started` IPC handler, the main process calls `emuCuaDriverProcess.ensureStarted({ app })` fire-and-forget. This pays the spawn + MCP `initialize` + `check_permissions` cost once at app launch regardless of whether the persisted/active mode is `coworker` or `remote`, so the first coworker action never blocks on cold start. Failures (missing binary, denied AX/Screen Recording) are logged on the main process and surface naturally via the existing per-action error path. The `emu-cua:ensure-started` IPC channel remains registered for explicit re-checks but is no longer invoked from the renderer at toggle time or on `Chat.mount`. The toggle button is a pure state mutation (no IPC, no permission UI side-effects), keeping the click instantaneous.
3.5 No new UI added: no trace tags, overlay, menu-bar pills, or hotkeys. Failure paths log to console only, matching the spec freeze on non-toggle UI.

### Phase 4 — Backend Prompt Plumbing
**Status:** ✅ Finished — prompt, tool catalogue, dispatcher branch, per-turn AX perception, and §4.8 sanity tests all landed and passed (8/8) on Windows with a stubbed driver.

**Completed (2026-04-29):**
- ✅ 4.1 New file `backend/prompts/coworker_system_prompt.py` — standalone, no imports from `system_prompt.py`. Renders ~22.6 KB. Sections in order: `<identity>` → `<output_protocol>` → `<actions>` → `<perception>` → `<addressing>` → `<example>` → `<planning>` → `<anti_loop>` → `<error_handling>` → `<debugging>` → `<skills_system>` → `<tools>` → `<device>` → `<session>` → workspace_context appended.
- ✅ 4.2 `<perception>` block — header line + screenshot + `tree_markdown` + element_count + AX/screenshot source-of-truth contract + index lifecycle + first-turn fallback. Capture-mode discussion intentionally collapsed to `som` only per user direction.
- ✅ 4.3 `<example>` — Finder "Open Recent" walk-through, element-indexed click + re-snapshot + pixel fallback variant + final `done` action.
- ✅ `<actions>` (separate section) — explicit `done` JSON shape with three use cases: TASK COMPLETE, CLARIFICATION NEEDED, STUCK / CANNOT PROCEED. All three use the same `done` envelope (`{"action":{"type":"done"},"done":true,"final_message":"..."}`). This is the only action JSON in coworker mode.
- ✅ `<debugging>` block — covers `cua_check_permissions`, `cua_get_config`, `cua_get_screen_size`, `cua_get_cursor_position`, `cua_get_agent_cursor_state`, `cua_set_agent_cursor_enabled`, `cua_set_agent_cursor_motion`, with diagnose-once discipline.
- ✅ 4.4 `<tools>` — single channel, two groups. **Group A (control plane):** `update_plan`, `read_plan`, `write_session_file`, `read_session_file`, `list_session_files`, `use_skill`, `create_skill`, `read_memory`, `compact_context`, `shell_exec`, `raise_app`, `list_running_apps`, `invoke_hermes`, `check_hermes`, `cancel_hermes`, `list_hermes_jobs`. **Group B (`cua_*` driver tools):** discovery (`cua_list_apps`, `cua_list_windows`, `cua_launch_app`); perception (`cua_screenshot`, `cua_get_window_state`); click family (`cua_click`, `cua_right_click`, `cua_double_click` — all dual-mode element-or-pixel, only `pid` strictly required); scroll (`cua_scroll` — `by ∈ line|page` covers both line and page-sized scrolls); text (`cua_type_text`, `cua_type_text_chars`, `cua_set_value`); keys (`cua_press_key`, `cua_hotkey`); cursor / drag (`cua_move_cursor`, `cua_drag`); diagnostics (`cua_check_permissions`, `cua_get_config`, `cua_get_screen_size`, `cua_get_cursor_position`, `cua_get_agent_cursor_state`, `cua_set_agent_cursor_enabled`, `cua_set_agent_cursor_motion`). NO cliclick fallback. NO `cua_wait` (does not exist in the driver). NO `cua_page` (the driver's `page` tool is a JS/DOM browser primitive, not page-scroll — use `cua_scroll(by="page")` instead). NO `finish_task` tool — completion uses the `done` action JSON instead.
- ✅ 4.5 (system-prompt branch only) — Caller-side branch in `backend/context_manager/context.py` at BOTH call sites: `_get` (line ~96) and `reset_with_summary` (line ~517). When `self._agent_mode.get(session_id) == "coworker"`, calls `build_coworker_system_prompt`; otherwise unchanged. `system_prompt.py` byte-identical (regression-tested via SHA256).
- ✅ 4.7 `backend/prompts/__init__.py` — re-exports `build_coworker_system_prompt`.

**Verification done:**
- All 14 required prompt sections + every documented tool name present in rendered prompt.
- No `<channels>`, `<window_management>`, `OmniParser`, `capture_mode=vision/ax`, cliclick mentions, or `finish_task` mentions leaked in.
- Workspace context, session id, device info round-trip correctly.
- Remote prompt SHA256 unchanged → `system_prompt.py` truly zero-diff.
- `py_compile` clean on `prompts/coworker_system_prompt.py`, `prompts/__init__.py`, `context_manager/context.py`.

**Files touched:**
- `backend/prompts/coworker_system_prompt.py` (new, ~470 lines after condensation)
- `backend/prompts/__init__.py` (re-export added)
- `backend/context_manager/context.py` (2 system-prompt call sites branched on `agent_mode`; `_coworker_target` map + `set_/get_/clear_coworker_target`; clear on `clear_session`)
- `backend/tools/coworker_tools.py` (new — `COWORKER_DRIVER_TOOLS_OPENAI`, `COWORKER_DRIVER_TOOL_NAMES`, `call_driver_tool`, `format_driver_result_for_model`)
- `backend/tools/dispatcher.py` (new branch at line ~198 routing `list_running_apps` + every `cua_*` to `call_driver_tool`; `_maybe_update_coworker_target` opportunistic tracking)
- `backend/providers/agent_tools.py` (mode-aware `get_agent_tools_openai`, `get_agent_tool_names`, `tools_for_anthropic`, `tools_for_gemini`)
- All 12 provider clients (`azure_openai`, `baseten`, `bedrock`, `claude`, `fireworks`, `gemini`, `h_company`, `modal`, `openai_compatible`, `openai_provider`, `openrouter`, `together_ai`) — switched to per-call mode-aware tool list using `agent_req.agent_mode`
- `backend/main.py` (`_inject_coworker_perception(session_id)` called when `req.agent_mode == "coworker"` after `set_agent_mode`; parses driver structuredContent — `tree_markdown`, `screenshot_png_b64` — and injects via `add_user_message` + `add_screenshot_turn`)

**Completed (rest — Phase 4.5 catalogue + 4.6 perception):**
- ✅ 4.5 (rest) Tool catalogue branch — `backend/tools/coworker_tools.py:COWORKER_DRIVER_TOOLS_OPENAI` carries OpenAI-format function specs for every `cua_*` driver tool, derived directly from the Swift `inputSchema` literals in `frontend/coworker-mode/emu-driver/Sources/CuaDriverServer/Tools/*.swift`. `backend/providers/agent_tools.py` exposes `get_agent_tools_openai(agent_mode)` which appends the coworker spec list only when `agent_mode == "coworker"`. All 12 provider clients now call this per-request using `agent_req.agent_mode`, so `cua_*` tools are advertised exclusively in coworker mode and the remote-mode tool catalogue is byte-identical to before.
- ✅ 4.5 (rest) Tool dispatch branch — `backend/tools/dispatcher.py` line ~198 adds a single `elif name == "list_running_apps" or name in COWORKER_DRIVER_TOOL_NAMES:` arm that maps `list_running_apps → list_apps`, strips the `cua_` prefix, and shells out via `call_driver_tool` (which `subprocess.run`s `emu-cua-driver call <tool> <json-args>`). Errors are surfaced as `tool_error`-shaped strings via `format_driver_result_for_model`, never raised. `_maybe_update_coworker_target` opportunistically captures `(pid, window_id)` from explicit args or from `cua_launch_app`'s `windows[0].window_id` so the perception injector has a target.
- ✅ 4.6 Per-turn AX perception — `_inject_coworker_perception` in `backend/main.py` reads `_coworker_target` from the context manager, calls `get_window_state` via `call_driver_tool`, and if successful injects a `[coworker_perception]` user message containing the `tree_markdown` (capped at 6000 chars) plus the JPEG screenshot from `screenshot_png_b64` (the field the CLI's `mergeImageContentIntoJSON` splices the MCP image block into). On driver failure, the stale target is cleared so the next turn won't re-fail. Skipped silently on the first turn before any `(pid, window_id)` is known.

**Verification done (this round):**
- Cross-checked every `cua_*` spec against the live Swift `inputSchema` in `frontend/coworker-mode/emu-driver/Sources/CuaDriverServer/Tools/`.
- Confirmed dispatcher's `cua_*` branch covers every entry in `COWORKER_DRIVER_TOOL_NAMES` (no manual per-tool list — it auto-inherits any addition).
- Confirmed `_maybe_update_coworker_target` reads `cua_launch_app`'s actual structuredContent shape (`pid` + `windows: [{window_id, ...}]`) per `LaunchAppTool.swift:LaunchResult/WindowRow` CodingKeys.
- Confirmed `_inject_coworker_perception` reads `tree_markdown` (matches `AppStateSnapshot.CodingKeys`) and `screenshot_png_b64` (matches CLI `mergeImageContentIntoJSON` splice).
- Confirmed all 12 provider clients pass `agent_req.agent_mode` into the mode-aware tool helpers.

**Verification done (comprehensive Phase 4 sweep):**
- Catalogue ↔ Swift registry: 23 `cua_*` specs map 1:1 against `ToolRegistry.default`'s 30 handlers. Driver tools deliberately NOT exposed to the agent: `get_accessibility_tree` (subsumed by `get_window_state`), `set_recording`, `get_recording_state`, `replay_trajectory`, `set_config`, `zoom`, `page` — all are non-agent operations or operator-only.
- Catalogue ↔ prompt index: every spec name appears in the prompt's `<tools>` Group B index, and the index lists no phantom tools (the only `cua_wait` / `cua_page` mentions are explicit "NO such tool" disclaimers).
- `COWORKER_DRIVER_TOOL_NAMES` is derived as a set comprehension from `COWORKER_DRIVER_TOOLS_OPENAI`, so spec/dispatcher drift is impossible by construction.
- Provider sweep: every one of the 12 provider clients (`azure_openai`, `baseten`, `bedrock`, `claude`, `fireworks`, `gemini`, `h_company`, `modal`, `openai_compatible`, `openai_provider`, `openrouter`, `together_ai`) calls the mode-aware helper (`get_agent_tools_openai` / `tools_for_anthropic` / `tools_for_gemini`) with `agent_req.agent_mode` at request time.
- main.py step ordering: `set_agent_mode` runs before the first context turn, so `_get`'s lazy system-prompt build picks up coworker mode correctly. `_inject_coworker_perception` fires after user-input turns are added but before the model call.
- Hardening: `format_driver_result_for_model` now strips `screenshot_png_b64` from the model-facing text channel (replaced with `_screenshot_omitted_bytes` count) so direct `cua_screenshot` / `cua_get_window_state` tool calls don't blow the 8 KB cap with base64 noise. The actual image still flows through `_inject_coworker_perception` as a real image content block.
- All Phase-4 files compile clean (only pre-existing optional-dep import warnings for `dotenv` / `google.genai` — unrelated).

**Completed (4.8 sanity tests — executed and passed, then artifact removed):**
- ✅ 4.8 — A standalone 8-check sanity suite was authored, executed against the live workspace on Windows (no macOS / no real driver needed — the Swift driver was stubbed via `unittest.mock.patch("tools.coworker_tools.call_driver_tool", ...)`, and the Swift `ToolRegistry.default` was parsed as text for the drift check). All 8 checks passed:
  1. **Unit** — `build_coworker_system_prompt` renders all required `<tag>` sections and round-trips workspace_context / session_id / device_details. Forbidden remote-mode tokens (`<channels>`, `<output_format>`, `<window_management>`, `OmniParser`, `capture_mode=vision/ax`, `cliclick`, `finish_task`) appear ONLY inside explicit "NEVER / forbidden / does-not-use" disclaimers — bare occurrences are rejected.
  2. **Drift A (control plane)** — every name in the prompt's Group A index appears in the dispatcher's live `elif name == "..."` chain.
  3. **Drift B (driver)** — every `cua_*` spec name maps (after stripping `cua_`) to a real handler in Swift `ToolRegistry.default`. Parsed from the Swift source via regex; `list_running_apps` is treated as the `list_apps` alias.
  4. **Regression** — (a) remote-mode tool catalogue matches a frozen 16-name snapshot and leaks no `cua_*` names; coworker mode is a strict superset. (b) Remote system prompt SHA256 was recorded; remote prompt confirmed to mention no `cua_*` tools and no coworker perception block.
  5. **Integration (stubbed driver)** — (a) dispatcher routes `cua_launch_app` → driver `launch_app` and `list_running_apps` → driver `list_apps`, with `_maybe_update_coworker_target` stashing `(pid, window_id)` from the stubbed launch result. (b) `format_driver_result_for_model` strips `screenshot_png_b64` from the model-facing text channel. (c) `_inject_coworker_perception` is a silent no-op when no target is set; with a target + stubbed driver returning `tree_markdown` + base64 image, it adds an AX-tree user message AND a screenshot turn to history (and does NOT leak the raw base64 into the text turn).
- The test file (`backend/test_coworker_phase4.py`) was deleted after the green run — Phase 4 is locked. Re-author from this spec if drift is suspected later.

**Architecture pivot — coworker is single-channel, tools-only.**
Unlike remote mode (which has TWO output channels — function-calls for control-plane and JSON-action text for desktop control), coworker mode has ONE: the function-calling API. *Every* control-plane primitive (plan, memory, sessions, hermes, shell) AND *every* driver action (click, type, scroll, screenshot, snapshot, launch, hotkey) is registered as a function tool. The model's plain-text output is reserved exclusively for final user-facing messages — never for action JSON. There is no `<channels>` section, no `<output_format>` JSON shape, no parsing of model text into actions. This makes the loop simpler, cheaper to validate, and impossible to misroute.

4.1 New file `backend/prompts/coworker_system_prompt.py` — fully self-contained, does not import from `system_prompt.py`. Voice, structure, tag style, and section ordering mirror the remote prompt as closely as possible (same `<tag>` blocks, same imperative tone, same level of specificity); only the coworker-specific facts differ. Exposes:
   ```python
   def build_coworker_system_prompt(
       workspace_context: str = "",
       session_id: str = "",
       device_details: dict | None = None,
   ) -> str: ...
   ```
   Sections (composed in this order, with fresh coworker-tailored copy that mirrors the remote prompt's voice):
   - `<identity>` — same Emu character/voice as remote, restated locally; explicit "coworker mode — never steal foreground" rule.
   - `<output_protocol>` — single-channel rule: every action is a function-tool call; plain text is reserved for the final user-facing message; emit `finish_task(message)` (or natural completion) when done. Forbids `open -a`, `osascript activate`, `cliclick` on the agent path, and any `CGEventPost` route.
   - `<perception>` — see 4.2 for the exact contents.
   - `<addressing>` — every interactive driver tool MUST carry `pid` and `window_id`; clicks/typing/scrolling carry either `element_index` (preferred — resolves on the driver to the cached AXUIElement) or pixel `(x, y)` as a fallback. Element-index is per-`(pid, window_id)` and per-snapshot; reusing across turns is undefined.
   - `<example>` — see 4.3 for the worked walkthrough.
   - `<planning>` — same plan-first discipline and `update_plan` cadence as remote, restated locally.
   - `<anti_loop>` — same repeat-action heuristics and escape paths, restated locally.
   - `<error_handling>` — same backoff, retry budget, escalation rules, restated locally; plus coworker-specific entries: missing AX/Screen Recording grant → surface to the user via the permissions widget; `pid`/`window_id` no longer valid (window closed, app quit) → re-discover via `list_apps`/`list_windows` rather than retry blindly; sparse Chromium AX tree → retry `get_window_state` once.
   - `<skills_system>` — same skill discovery and load-on-demand contract, restated locally.
   - `<debugging>` — coworker-only block. When something feels off (clicks miss, tree empty, app unresponsive, cursor invisible), the model should reach for the diagnostic tools BEFORE blindly retrying: `cua_check_permissions` (verifies AX + Screen Recording grants), `cua_get_config` (current driver capture/cursor settings), `cua_get_agent_cursor_state` (is the agent cursor visible? where is it?), `cua_get_cursor_position` (real cursor location), `cua_set_agent_cursor_enabled`/`cua_set_agent_cursor_motion` (toggle the agent cursor overlay so the user can see what the model is doing). Use these to disambiguate "permission denied" vs "stale window" vs "wrong target" without breaking the no-foreground contract. Keep it lightweight — call once, read the result, decide.
   - `<tools>` — single combined catalogue (no Channel-1/Channel-2 split). See 4.4.
   - `<device>` — device info template, filled per-call from `device_details` (same shape as remote: `os_name`, `arch`, `screen_width`, `screen_height`, `scale_factor`).
   - Session block — date/time/session_id/project_root/emu_dir, same shape as remote's `_SESSION_BLOCK`.
   - `workspace_context` — AGENTS.md plug-in, appended verbatim if non-empty (same convention as remote).

   Note: "restated locally" means we copy the topic/intent into fresh coworker-aware copy, not import strings from `system_prompt.py`. `system_prompt.py` stays untouched.

4.2 `<perception>` block must spell out, concretely, what the model receives every turn so it can rely on it without guessing:
   - One vision content block: a PNG screenshot of **only the target window** (cropped to its on-screen bounds, including the titlebar). Not the desktop, not other windows.
   - One fenced Markdown text block (`tree_markdown`) labelled with `pid` and `window_id`, containing a hierarchical render of the window's accessibility tree. Every actionable node is tagged `[element_index N]`. Containers without an action role are not tagged but are kept for structure.
   - A short header line: `Target: <app_name> pid=<pid> window_id=<wid> capture_mode=<som|vision|ax>`.
   - An `element_count` integer (advisory) so the model can sanity-check.
   - Source of truth contract: the AX tree is authoritative for element identity; the screenshot is authoritative for visual disambiguation when several elements share the same role/title. When they disagree (rare), prefer the AX tree.
   - First turn / unknown target: if no `pid`/`window_id` is set yet (no `raise_app`/`launch_app` has succeeded), the perception block is omitted and only the desktop image (if any) is sent. The model must call discovery tools (`list_apps`, `list_running_apps`, `raise_app`, `launch_app`) before any element-indexed action.
   - Index lifecycle: `[element_index N]` is valid only against the most recent `get_window_state` snapshot for that exact `(pid, window_id)`. The next snapshot replaces the index map. Reusing an old index is undefined behaviour.
   - Capture-mode notes: `som` ships both AX tree + screenshot (default); `vision` ships screenshot only (no element_index — pair with pixel `(x,y)`); `ax` ships AX tree only (no screenshot).

4.3 `<example>` block — concrete worked walkthrough showing the model how to choose. Tools-only flavour:
   - Scenario: user asked "open the Recent files menu in Finder".
   - Step 1: Receive perception. Header reads `Target: Finder pid=812 window_id=4507 capture_mode=som`. The screenshot shows a Finder window. The AX tree contains lines such as:
     ```
     - AXMenuBar
       - AXMenuBarItem "File" [element_index 14]
         - AXMenu
           - AXMenuItem "New Folder" [element_index 15]
           - AXMenuItem "Open Recent" [element_index 23]
     ```
   - Step 2: Decide. The user wants the "Open Recent" submenu under File. The desired state is the submenu visible, which requires clicking File first to expose the menu, then clicking Open Recent.
   - Step 3: Call the tool `cua_left_click(pid=812, window_id=4507, element_index=14)`. **Do not** include `x,y` when an element_index is available. **Do not** emit JSON in plain text — call the function tool directly.
   - Step 4: Wait for the next perception turn. The new AX tree will contain the now-expanded menu with fresh indices (the previous index 14 is no longer valid for the menu state). Re-locate `Open Recent` in the new tree before clicking, calling `cua_get_window_state(pid=812, window_id=4507)` first if you need a fresh snapshot.
   - Step 5: Pixel fallback. If perception arrives with `capture_mode=vision` (no AX tree), or the desired element is not tagged (e.g., a custom canvas), call `cua_left_click(pid=812, window_id=4507, x=120, y=40)`. Always pair pixel coordinates with `pid`+`window_id`.
   - Step 6: When the task is complete, call `finish_task(message="Opened the Recent files menu in Finder.")` (or, if no `finish_task` tool exists yet in the runtime, end the turn with a plain-text final message and no tool call).

4.4 `<tools>` — single combined catalogue, no channel split. Two groups inside the same section:

   Group A — **Control-plane tools** (mirrors the remote `<agent_tools>` minus the channel-2 warnings). Enumerate every tool registered in `backend/tools/dispatcher.py`. At time of writing: `update_plan`, `read_plan`, `use_skill`, `create_skill`, `read_memory`, `write_session_file`, `read_session_file`, `list_session_files`, `compact_context`, `invoke_hermes`, `check_hermes`, `cancel_hermes`, `list_hermes_jobs`, `shell_exec`, `raise_app`, plus the new `list_running_apps` added in Phase 5. The implementor MUST grep `backend/tools/dispatcher.py` for the live `elif name == "..."` chain at implementation time and reconcile any additions/deletions before merging. Each entry gets the same one-line description and argument shape as the remote prompt's `<agent_tools>` section.

   Group B — **Driver tools** (NEW — these replace what was Channel 2 in remote mode). Coworker mode exposes the driver as first-class function tools, namespaced `cua_*` to avoid collision and to make routing trivial. Signatures below are derived from `frontend/coworker-mode/emu-driver/Sources/CuaDriverServer/Tools/*.swift` and MUST match those schemas exactly — when the driver schema changes, update both this section AND the prompt's `<tools>` Group B AND `backend/tools/coworker_tools.py:COWORKER_DRIVER_TOOLS_OPENAI` together.

   Discovery / target selection:
   - `cua_list_apps()` — running regular apps with `pid`, `name`, `bundle_id`, `front_window_id`. No params.
   - `cua_list_windows(pid?, on_screen_only?)` — layer-0 windows with `window_id`, `pid`, `app_name`, `title`, `bounds`, `z_index`, `is_on_screen`, `on_current_space`, `space_ids`. `on_screen_only` defaults `false` so minimized / off-Space windows are surfaced. Use this — not `cua_list_apps` — for any window-level reasoning.
   - `cua_launch_app(bundle_id?, name?, urls?, electron_debugging_port?, webkit_inspector_port?, creates_new_application_instance?, additional_arguments?)` — hidden-launch primitive (never raises a window). Returns `pid`, `bundle_id`, `name`, plus a `windows` array (same shape as `cua_list_windows`) so the caller can skip a `cua_list_windows` round-trip. At least one of `bundle_id` / `name` must be provided; `bundle_id` wins when both are given. NOT a generic launcher — strictly background-launch; if the user wants the app frontmost they switch via Dock/Cmd-Tab.

   Perception:
   - `cua_screenshot(format?, quality?, window_id?)` — capture via ScreenCaptureKit. ALL params optional. Without `window_id` captures the full main display; with `window_id` captures just that window. `format` ∈ `png|jpeg` (default `png`); `quality 1-95` (JPEG only). Returns base64 image content block.
   - `cua_get_window_state(pid, window_id, query?, javascript?)` — walks `pid`'s AX tree, returns Markdown tagged with `[element_index N]` plus a screenshot of the specified `window_id`. **Required: `pid`, `window_id`** — `window_id` MUST belong to `pid` and be on the user's current Space. Mints a fresh index map and invalidates the previous one for that `(pid, window_id)`. Optional `query` (case-insensitive substring) trims the rendered Markdown while preserving ancestors and index numbers — element_index values are unchanged. Optional `javascript` runs in the browser tab co-located with the snapshot (Chromium/Safari only; requires "Allow JavaScript from Apple Events"). Capture mode (`som` / `vision` / `ax`) is governed by the persistent `set_config capture_mode` setting, not a per-call arg.

   Click family — every click tool requires only `pid`. Element-indexed and pixel modes are mutually exclusive: provide EITHER `element_index` + `window_id`, OR `x` + `y`. Never both. Window-local pixel coordinates use the same coordinate space as the PNG returned by `cua_get_window_state` (top-left origin of the target's window, including titlebar):
   - `cua_click(pid, element_index?, window_id?, x?, y?, action?, modifier?, count?, from_zoom?)` — left-click. **There is no `button` param** — for right-clicks use `cua_right_click`. Element-indexed path: optional `action ∈ press|show_menu|pick|confirm|cancel|open` (default `press`); other params (modifier, count, from_zoom) are ignored on this path. Pixel path: optional `count ∈ 1|2|3` (single/double/triple), `modifier` array (cmd/shift/option/ctrl), `from_zoom` boolean (when true, `x/y` are coords in the last `cua_zoom` image and the driver maps them back).
   - `cua_right_click(pid, element_index?, window_id?, x?, y?, modifier?)` — element-indexed path performs `AXShowMenu` on the cached element. Pixel path synthesizes a right-mouse-down/up pair (Chromium web content has a known Coercion-to-left-click caveat). **No `count`** — single right-click only. `modifier` is pixel-path only.
   - `cua_double_click(pid, element_index?, window_id?, x?, y?, modifier?)` — element-indexed path performs `AXOpen` if advertised, else falls back to a pixel double-click at the element's center. Pixel path posts a stamped double-click (clickState 1→2). **No `count`** — always 2. `modifier` is pixel-path only.

   Scroll:
   - `cua_scroll(pid, direction, amount?, by?, element_index?, window_id?)` — required: `pid`, `direction` ∈ `up|down|left|right`. Optional: `amount` (1-50, default 3 keystroke repetitions), `by` ∈ `line|page` (default `line`). Implementation note: scroll posts synthesized arrow-key (line) or PageUp/PageDown (page) keystrokes via the auth-signed `SLEventPostToPid` path because `CGEventCreateScrollWheelEvent2` is silently dropped by Chromium. Optional `element_index` + `window_id` focuses the element first; skip them when focus was already established by a prior click. There is NO separate `cua_page` tool — page-sized scrolls use `cua_scroll(by="page")`.

   Text input:
   - `cua_type_text(pid, text, element_index?, window_id?)` — required: `pid`, `text`. Inserts via `AXSetAttribute(kAXSelectedText)`. Works for standard Cocoa text fields/views. Does not synthesize keystrokes — Return/Tab/etc. go through `cua_press_key` / `cua_hotkey`. Optional `element_index` + `window_id` pre-focuses the element. For Chromium/Electron inputs that don't implement `kAXSelectedText`, fall back to `cua_type_text_chars`.
   - `cua_type_text_chars(pid, text, delay_ms?)` — required: `pid`, `text`. Character-by-character via `CGEvent.postToPid` with `CGEventKeyboardSetUnicodeString` (bypasses VK mapping; transmits accents/symbols/emoji verbatim). `delay_ms 0-200` (default 30) spaces successive characters so autocomplete/IME can keep up. Use this when `cua_type_text` silently drops characters. Caller must focus the receiving element first (e.g. via `cua_click`).
   - `cua_set_value(pid, window_id, element_index, value)` — ALL FOUR required. Two modes: (a) `AXPopUpButton` / HTML `<select>` — finds the child option whose title/value matches `value` (case-insensitive) and `AXPress`es it directly; the native popup menu is never opened, no focus steal. (b) Other elements — writes `AXValue` directly (sliders, steppers, date pickers, native text fields). For free-form text in WebKit inputs, use `cua_type_text_chars` — AXValue writes are ignored by WebKit.

   Keys:
   - `cua_press_key(pid, key, modifiers?, element_index?, window_id?)` — required: `pid`, `key`. Single key press delivered via SkyLight's auth-signed `SLEventPostToPid` (works on backgrounded Chromium). Key vocabulary: `return, tab, escape, up, down, left, right, space, delete, home, end, pageup, pagedown, f1-f12`, letters, digits. Optional `modifiers` array (cmd/shift/option/ctrl/fn). Optional `element_index` + `window_id` pre-focuses the element via `AXSetAttribute(kAXFocused, true)` before the key fires. For true combinations (cmd+c) prefer `cua_hotkey` for clarity.
   - `cua_hotkey(pid, keys)` — required: `pid`, `keys` (array of ≥2 strings). Modifiers first, one non-modifier last, e.g. `["cmd","c"]`, `["cmd","shift","p"]`. Recognized modifiers: cmd/command, shift, option/alt, ctrl/control, fn.

   Cursor / drag:
   - `cua_move_cursor(x, y)` — required: `x`, `y` in **screen points** (NOT window-local, NOT pid-routed). Uses `CGWarpMouseCursorPosition`. **No `pid`, no `window_id`, no relative `dx/dy`.** Coworker discipline: this is a real cursor warp visible to the user; reach for it only when an interaction genuinely requires the cursor to be somewhere specific (rare in coworker mode — driver tools don't need the cursor on-target).
   - `cua_drag(pid, from_x, from_y, to_x, to_y, window_id?, duration_ms?, steps?, modifier?, button?, from_zoom?)` — required: `pid`, `from_x`, `from_y`, `to_x`, `to_y` in window-local screenshot pixels (same space as `cua_get_window_state` PNG). Optional `window_id` (when omitted the driver picks the frontmost window of `pid`; pass when the target has multiple windows). `duration_ms` (0-10000, default 500), `steps` (1-200, default 20), `modifier` array (held across the entire gesture — option-drag duplicates, shift-drag axis-constrains), `button` ∈ `left|right|middle` (default left), `from_zoom` boolean. Frontmost target uses `.cghidEventTap` (real cursor visibly traces the path — unavoidable for AppKit drag sources). Backgrounded target uses the auth-signed pid-routed path (cursor-neutral; some OpenGL canvases may filter it).

   Diagnostics (see `<debugging>`):
   - `cua_check_permissions(prompt?)` — Accessibility + Screen Recording grant state. `prompt` defaults `true` (raises the system dialogs for missing grants — safe to call repeatedly because Apple's request APIs no-op when already granted). Pass `prompt=false` for a read-only status check.
   - `cua_get_config()` — current capture/cursor configuration. Useful when `cua_get_window_state` returned no tree (capture_mode might be `vision`).
   - `cua_get_screen_size()` — display pixel dimensions (useful when planning pixel-fallback clicks against `vision` capture mode).
   - `cua_get_cursor_position()` — current OS cursor x/y in screen points.
   - `cua_get_agent_cursor_state()` — `{enabled, x, y, motion}` for the agent-cursor overlay.
   - `cua_set_agent_cursor_enabled(enabled)` — toggle the visible agent cursor overlay (off by default).
   - `cua_set_agent_cursor_motion(start_handle?, end_handle?, arc_size?, arc_flow?, spring?, glide_duration_ms?, dwell_after_click_ms?, idle_hide_ms?)` — tune the agent cursor's Bezier-arc + spring-settle motion. ALL fields optional; only the knobs you pass change. Defaults: start_handle=0.3, end_handle=0.3, arc_size=0.25, arc_flow=0.0, spring=0.72, glide_duration_ms=750, dwell_after_click_ms=400, idle_hide_ms=3000. **There is no `instant`/`smooth` enum** — earlier drafts of this PLAN named one; the driver actually exposes the eight numeric knobs above.

   Tools deliberately NOT exposed in coworker mode (kept on the driver but not advertised to the LLM in v1):
   - `cua_wait` — does not exist in the driver. Do not invent it; if a settle-pause is needed, call `cua_get_window_state` again (fresh AX tree implicitly settles).
   - `cua_page` — the driver's `page` tool is a JS/DOM browser primitive (`execute_javascript` / `get_text` / `query_dom` / `enable_javascript_apple_events`), NOT a page-scroll. Page-sized scrolls use `cua_scroll(by="page")`. The browser-JS surface can be added later behind a separate `cua_page_*` namespace if a workflow needs it.
   - `cua_get_accessibility_tree` — superseded by `cua_get_window_state` for coworker reasoning.
   - `cua_zoom`, `cua_set_recording`, `cua_get_recording_state`, `cua_replay_trajectory`, `cua_set_config`, `cua_image_resize_registry` — operator/recording surfaces; not part of the agent loop.

   **No cliclick fallback needed.** The emu-driver / MCP covers every action coworker mode requires natively, all on the no-foreground SkyLight path:
   - triple-click → `cua_click(..., count=3)` (pixel path — element-indexed clicks are always single).
   - mouse_move → `cua_move_cursor` (uses screen-point coordinates).
   - drag / relative_drag → `cua_drag`.
   - get_mouse_position → `cua_get_cursor_position`.
   - single key press → `cua_press_key`.
   The prompt should state the rule in one line: "Every interactive primitive is a `cua_*` tool — never shell out to `cliclick`, `osascript activate`, or `open -a` from the agent path."

4.5 Dispatcher / runtime wiring — minimal change to existing code path:
   - **System prompt branch.** At the single call site that builds the system prompt for an agent step (in `backend/context_manager/context.py`), wrap with a branch:
     ```python
     if agent_mode == "coworker":
         from backend.prompts.coworker_system_prompt import build_coworker_system_prompt
         prompt = build_coworker_system_prompt(workspace_context=..., session_id=..., device_details=...)
     else:
         prompt = build_system_prompt(...)  # untouched
     ```
     Do NOT add an `agent_mode` parameter to `build_system_prompt`. Branching happens in the caller, keeping `system_prompt.py` zero-diff.
   - **Tool catalogue branch.** The function-tool catalogue published to the LLM must include the `cua_*` driver tools (and `cua_cliclick`, and `finish_task`) ONLY when `agent_mode == "coworker"`. In remote mode they are absent. Concretely: add a coworker-only tool spec list in `backend/tools/dispatcher.py` (or a sibling `backend/tools/coworker_tools.py`), and merge it into the catalogue when assembling the request.
   - **Tool dispatch branch.** Each `cua_*` call in the dispatcher's `elif name == ...` chain forwards to the corresponding `emu-cua-driver` MCP tool by shelling out (`emu-cua-driver call <tool> <json-args>`) or via a thin Python MCP client. Errors are surfaced as `tool_error` payloads, not raised, so the model can recover.
   - **Action JSON parsing.** In coworker mode, the response parser MUST NOT attempt to parse driver actions out of model plain text — the only actions are tool calls. Plain text is treated as the final user-facing message (or an interim narration if no tool call was made). This is the simplification the architecture earns.

4.6 Per-turn AX tree wiring — required for `<perception>` to be true:
   - When `agent_mode == "coworker"`, the agent loop must call the driver's `get_window_state(pid, window_id)` at the top of each turn for the active target window, then place the returned `tree_markdown` and image content block into the user-message content alongside the screenshot.
   - Mechanically: extend the per-step request handler in `backend/main.py` (or the equivalent step assembler) to emit a `coworker_perception` block containing `{tree_markdown, element_count, screenshot_image_block, window_id, pid, capture_mode}` before the user message. Image goes in as a vision content block; tree goes in as a fenced Markdown text block.
   - If `pid`/`window_id` is unknown on the first turn (no `raise_app`/`launch_app` yet), skip the snapshot and let the model call discovery tools first. Document this fallback in `<perception>`.

4.7 `backend/prompts/__init__.py` — re-export `build_coworker_system_prompt` for symmetry with `build_system_prompt`. `system_prompt.py` exports stay as-is.

4.8 Sanity tests:
   - Unit: `build_coworker_system_prompt(workspace_context="…AGENTS.md…", session_id="s1", device_details={...})` returns a string that contains `<identity>`, `<output_protocol>`, `<perception>`, `<addressing>`, `<example>`, `<tools>`, the AGENTS.md content, the session id, and the device info. Verify it does NOT mention `<channels>`, `<output_format>` JSON, the remote-only `<window_management>`, or omniparser/desktop-screenshot vision blocks.
   - Tool-catalog drift (control plane): assert that the names enumerated under Group A are a superset/match of the live `elif name == ...` chain in `backend/tools/dispatcher.py`.
   - Tool-catalog drift (driver): assert that the `cua_*` tool names enumerated under Group B match the IPC-wrapped tool names in `frontend/cua-driver-commands/index.js` (modulo the `cua_` prefix).
   - Regression: rendering the remote prompt before and after this phase produces byte-identical output (proves `system_prompt.py` is untouched).
   - Integration: with a stubbed driver returning a known `tree_markdown`, verify the per-turn user message contains both the image block and the AX tree text in coworker mode, and only the image in remote mode. Verify the tool catalogue passed to the LLM in coworker mode includes `cua_*` tools and excludes them in remote mode.




### Phase 5 — Backend Tools (raise_app + list_running_apps)
**Status:** ✅ Finished — `raise_app` is mode-aware, target tracking fires on coworker raises, and `list_running_apps` is exposed via the existing `cua_*` dispatch arm.

**Outcome:** Model has structured discovery primitives that return real `pid`/`window_id` values without ever stealing the foreground in coworker mode.

**Completed (2026-04-30):**

5.1 ✅ `backend/tools/raise_app.py` — `handle_raise_app(app_name, agent_mode="remote")` now branches:
   - `agent_mode == "remote"` → existing `osascript activate` path, byte-identical (factored into `_raise_via_osascript` so the validation guard is shared).
   - `agent_mode == "coworker"` → `_raise_via_driver` calls `call_driver_tool("launch_app", {"name": app_name})` and returns the driver's structured JSON (`{pid, bundle_id, name, windows: [...]}`) on success, or a structured `ERROR: coworker raise_app failed to launch '<name>': <reason>` on driver failure. **Never invokes osascript in coworker mode** — preserves the no-foreground contract.

5.2 ✅ `list_running_apps` — kept inline in the dispatcher's `cua_*` arm rather than as a separate file. The route at `backend/tools/dispatcher.py` line ~198 (`elif name == "list_running_apps" or name in COWORKER_DRIVER_TOOL_NAMES`) already maps `list_running_apps → driver list_apps` via `call_driver_tool`. The OpenAI spec is published in `COWORKER_DRIVER_TOOLS_OPENAI` (coworker mode only). Adding a `backend/tools/list_running_apps.py` wrapper would have been a redundant ~10 lines for zero functional gain — intentional deviation from the spec sketch.

5.3 ✅ `backend/tools/dispatcher.py`:
   - `execute_agent_tool(...)` gained `agent_mode: str = "remote"` kwarg.
   - `raise_app` arm now passes `agent_mode` to `handle_raise_app` AND, on coworker success, opportunistically parses the returned JSON and calls `_maybe_update_coworker_target(...)` so the next perception turn has a `(pid, window_id)`. This mirrors the existing `cua_launch_app` tracking behaviour.
   - `list_running_apps` was already registered + advertised in Phase 4; no additional wiring needed.

5.4 ✅ Transport: shells out via `emu-cua-driver call <tool> <json>` (already implemented in `tools/coworker_tools.py:call_driver_tool` with the `$EMU_CUA_DRIVER_BIN` → `~/.local/bin` → `/Applications` → PATH precedence). No Python MCP client needed for v1.

**Also touched:**
- `backend/main.py` line ~506 — passes `agent_mode=req.agent_mode` into `execute_agent_tool`.
- `backend/providers/agent_tools.py` — appended a paragraph to the `raise_app` tool description making the mode-aware behaviour explicit to the model: in coworker mode it returns `{pid, bundle_id, name, windows: [...]}` JSON without raising a window or stealing focus, and the model should use the returned `pid` + `windows[0].window_id` as the target for subsequent `cua_*` calls. Tool catalogue surface in both modes is otherwise unchanged.

**Verification done (Windows, stubbed driver — no macOS needed):**
- `handle_raise_app('Finder', agent_mode='remote')` on Windows hits the macOS guard → `ERROR: raise_app only works on macOS (detected: Windows)`. Remote path byte-identical to pre-change.
- `handle_raise_app('', agent_mode='coworker')` → validation guard fires before mode dispatch.
- `handle_raise_app('Finder', agent_mode='coworker')` with stubbed `call_driver_tool` returning a launch payload → returns parseable JSON with `pid=812`, `windows[0].window_id=4507`.
- Coworker driver failure (binary missing) → surfaced as `ERROR: coworker raise_app failed to launch 'Finder': binary missing`.
- Full dispatcher round-trip in coworker mode: tool fires, driver stubbed, `cm.get_coworker_target('s1') == (812, 4507)` after the call.
- Same dispatcher path in remote mode: no driver call, no target tracking, returns the osascript guard string.

**No edits to:** the coworker prompt (already tells the model to prefer `cua_launch_app` directly; `raise_app` works as a near-alias), provider tool catalogues except for the description addendum, frontend code, or driver source.

### Phase 6 — Capture Path (Action-model fields obsolete)
**Status:** ✅ Finished (2026-04-30) — coworker capture flows through emu-cua-driver target-window screenshots; remote path unchanged.
**Outcome:** Per-step screenshots in coworker mode flow from the target window via `emu-cua:screenshot`, not the whole desktop. Frontend knows the active `(pid, window_id)` because the backend surfaces it on `/agent/step`.

**Architectural note (post-Phase-4 pivot):** Coworker mode is single-channel — every interactive primitive is a function-tool call dispatched server-side via `call_driver_tool`. Real desktop actions (`cua_click`, `cua_type_text`, …) never travel through a renderer action proxy; `frontend/actions/executor.js` rejects non-`done` coworker Action JSON before dispatch. That makes the original §6.1 (extending `Action` with `pid`/`window_id`/`element_index`) **dead weight** and we are skipping it. The model addresses targets via tool-call arguments parsed by `coworker_tools.COWORKER_DRIVER_TOOLS_OPENAI`.

6.1 ~~`Action` field extension~~ — **SKIPPED.** Single-channel design means `pid`/`window_id`/`element_index` belong on tool-call args, not the Action model. No pydantic root validator needed.

6.2 `frontend/services/captureForStep.js` — new, ~30 lines. Single function `captureForStep()`:
   - If `store.state.agentMode === 'coworker'` and `store.state.coworkerTarget` has `pid && window_id`, invoke `emu-cua:screenshot` with the target `window_id` (the screenshot tool does not take `pid`) and return `{success, base64, error}`.
   - Else fall through to the existing `captureScreenshot()` (desktopCapturer / native screencapture).
   - On coworker capture failure, fall back to remote capture once with a warning, so a stale window never wedges the loop.

6.3 Wire `captureForStep` into `pages/Chat.js#continueLoop` (the only per-step screenshot call site for `postStep`). The other `captureScreenshot` reference in `frontend/actions/actionProxy.js` is the remote `screenshot` action and stays unchanged.

6.4 ✅ Already done: `frontend/cua-driver-commands/index.js#_extractBase64` returns the image block as base64 alongside text output.

6.5 Surface `(pid, window_id)` to the frontend.
   - `backend/main.py` populates `coworker_target` on the WebSocket `step` event payload (the per-step transport that drives the renderer loop). Pulled from `context_manager.get_coworker_target(session_id)` and only set when `req.agent_mode == "coworker"`. Sends `null` to explicitly clear a stale target; key omitted entirely in remote mode.
   - `AgentResponse` and the HTTP `/agent/step` JSON body are intentionally NOT extended — `frontend/services/api.js#postStep` doesn't read the response body, and adding the field there would be dead weight.
   - `frontend/state/store.js` adds `coworkerTarget: null` and `setCoworkerTarget(target)` (clears on null/missing pid/window_id).
   - `frontend/pages/Chat.js#handleWsMessage` step case persists `data.coworker_target` via `store.setCoworkerTarget` whenever the key is present (including explicit null clears). Remote-mode steps omit the key, so the existing target is left intact across mode switches.
   - `frontend/services/captureForStep.js` reads `store.state.coworkerTarget` to decide which capture path to use.

6.6 Action-set audit (unchanged from prior decisions, restated for QA):
- Supported in v1 (coworker tool surface): `cua_click` family, `cua_scroll`, `cua_type_text`/`cua_type_text_chars`/`cua_set_value`, `cua_press_key`/`cua_hotkey`, `cua_screenshot`, `cua_get_window_state`, `cua_launch_app`, `cua_list_apps`/`cua_list_windows`, `cua_move_cursor`, `cua_drag`, plus diagnostics.
- Plain Action types are not used for coworker interaction. `frontend/actions/executor.js` allows only `done` in coworker mode and rejects all other Action JSON so stale remote actions cannot bypass the backend `cua_*` workflow.
- The obsolete renderer coworker `ACTION_MAP` in `frontend/cua-driver-commands/actionProxy.js` was removed after the single-channel pivot; `frontend/cua-driver-commands/index.js` remains for IPC handlers used by capture, permission checks, and operator-facing calls.

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

### Phase 8 — User Experience Refinement
**Status:** ✅ Finished (2026-05-02) — missing Accessibility / Screen Recording grants now surface through an Emu-styled, non-blocking renderer card.
**Outcome:** When `emu-cua-driver` reports a missing TCC permission, the user sees an in-app permission widget that opens the exact System Settings pane on click — they never have to navigate Settings manually.

**Completed (2026-05-02):**
- ✅ `frontend/components/chrome/PermissionsCard.js` renders the modal-style card with Emu typography, two permission rows, inline SVG glyphs, `Allow` buttons, waiting state, auto-dismiss, outside-click dismissal, Esc dismissal, and dialog/group ARIA wiring.
- ✅ `frontend/styles/chrome/permissions-card.css` is imported from `frontend/styles/index.css` and uses existing Emu tokens rather than custom colors or spacing primitives.
- ✅ `main.js` emits `emu-cua:permissions-required` after eager driver startup and after renderer-side driver IPC calls that return permission failures.
- ✅ `preload.js` exposes the receive allowlist for `emu-cua:permissions-required` and invoke allowlist entries for permission rechecks and target-window screenshots.
- ✅ `frontend/pages/Chat.js` subscribes once at mount, lazy-instantiates the card, wires `Allow` to `permissions:open`, and wires polling to `emu-cua:recheck-permissions`.
- ✅ `EmuCuaDriverProcess.recheckPermissions()` is public and reuses the daemon when available, or starts it before checking.

8.1 New component `frontend/components/chrome/PermissionsCard.js`
- Centered modal-style card (Emu Design System v1: serif title, soft border, dark-mode aware), sized comfortably for two permission rows. Reuses existing tokens from `style.css` (no new color or spacing primitives).
- Structure (DOM only — visual treatment must read like the rest of Emu, not the reference screenshot):
  - Header: small Emu wordmark/glyph, title `"Enable Emu Coworker Mode"`, subtitle `"Emu needs these permissions to control apps on your Mac. Permissions are only used while Coworker mode is running."`
  - One row per missing permission, each row shows:
    - Left: SF-symbol-style glyph (inline SVG, accessibility figure for AX, camera/screen glyph for Screen Recording).
    - Center: row title + one-line description.
      - Accessibility → `"Allows Emu to read app interfaces and dispatch input."`
      - Screen Recording → `"Lets Emu see the target window between actions."`
    - Right: primary `Allow` button.
- Buttons must use the existing primary-button style (matches Composer send button), not a custom blue.
- Card has a subtle backdrop overlay (semi-opaque) but is **non-blocking**: clicking outside dismisses (rechecking happens via the existing per-action error path; the user can also re-summon it by retrying).
- Public API: `PermissionsCard({ missing, onAllow, onDismiss })` returns `{ element, update(missing), close() }` so the same node can re-render after a permission flips.

8.2 Trigger surface — main process drives, renderer just renders
- Add IPC channel `emu-cua:permissions-required` (one-way, main → renderer) carrying `{ missing: ['accessibility'|'screen', ...] }`.
- In `main.js`, after the eager `emuCuaDriverProcess.ensureStarted({ app })` resolves and at every subsequent `callTool` failure that returns `permissionsRequired: true`, emit this channel to all renderer windows so the widget appears as soon as Emu knows.
- Add to `preload.js` `ALLOWED_RECEIVE_CHANNELS` (introduce the receive allowlist if not present) and expose `electronAPI.on('emu-cua:permissions-required', cb)`.

8.3 Renderer wiring
- `pages/Chat.js` subscribes once at `mount()`. When a payload arrives, it calls `PermissionsCard.show(missing)` (lazy-instantiated) and replaces it with `update()` if already open.
- `Allow` click → `ipcRenderer.invoke('permissions:open', kind)` where `kind` is `'accessibility'` or `'screen'`. The existing handler (`main.js:175`) already maps to the precise pane URL:
  - Accessibility: `x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility`
  - Screen Recording: `x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture`
- After a successful click, the row enters a "Waiting for permission…" state with a small spinner. The widget polls via a new IPC `emu-cua:recheck-permissions` (calls `emuCuaDriverProcess._checkPermissions()` indirectly through a public wrapper) every ~2 s while focused; when granted, the row collapses and the card auto-dismisses when no rows remain.

8.4 Public wrapper on `EmuCuaDriverProcess`
- Export `recheckPermissions()` that calls the existing internal `_checkPermissions()` only if the child is up; otherwise re-runs `ensureStarted()`. This keeps the polling loop in 8.3 simple and avoids exposing private symbols.

8.5 Visual reference vs Emu identity
- The reference screenshot is a layout cue only. Final widget must use Emu's serif/italic title style, Emu's button radius and surface tints, and Emu's dark-mode palette so it reads as part of the app, not as a system-style alert. Do **not** copy gradient app icons, blue accent buttons, or chrome from the reference.

8.6 Accessibility & keyboard
- Tab order: first row `Allow` → second row `Allow` → close (Esc).
- `role="dialog"` with `aria-labelledby` pointing at the title; `aria-modal="false"` because the card is dismissable and non-blocking.
- Each row title/description is announced as a single landmark (`role="group"` with `aria-labelledby`).

8.7 Test matrix (manual, before release)
- Cold start with both permissions missing → card appears within ~1 s of app launch, two rows visible.
- Click Allow on Accessibility → System Settings opens directly on Privacy → Accessibility pane.
- Grant Accessibility, return to Emu → Accessibility row disappears within ~2 s; Screen Recording row remains.
- Grant Screen Recording → card auto-closes.
- Toggle to remote mode while card is open → card stays open (permissions are still useful for the next coworker session); pressing Esc dismisses.
- Crash the driver mid-session, then run a coworker action while AX is denied → card re-appears, action fails with the existing error path.

### Phase 9 — Packaging & Release
**Status:** ✅ Finished for v1 dev packaging (2026-05-02); notarized public-DMG signing remains deferred per §5.
**Outcome:** A built Emu app/DMG includes `emu-cua-driver`; first-run users can use coworker mode without separate installs.

9.1 ✅ `electron-builder` config — `package.json` now adds `extraResources`:
```json
"extraResources": [
  { "from": "frontend/coworker-mode/emu-driver/.build/release/emu-cua-driver",
    "to": "emu-cua-driver/emu-cua-driver" }
]
```
9.2 ✅ Pre-build hook: root `npm run build:driver` delegates to `frontend/coworker-mode/emu-driver/scripts/build-app.sh release`; `npm run pack` and `npm run dist` run it before `electron-builder`.
9.3 ✅ Notarization posture: current v1 pack flow uses ad-hoc signing; hardened/notarized signing stays deferred to the public-DMG phase.
9.4 ✅ `EmuCuaDriverProcess._resolveBinary` packaged path (`process.resourcesPath/emu-cua-driver/emu-cua-driver`) matches the `extraResources.to` path.
9.5 ✅ First-run missing-binary UX is covered by the existing startup failure/permission card path plus the per-action error surface; no separate toggle-time dialog was added to preserve the Phase 3 UI freeze.
9.6 ✅ Document helper ownership for dev/release:
- Emu memory daemon remains launchd-owned and unchanged.
- `emu-cua-driver serve --no-relaunch` is Electron-main-owned and app-lifetime only; the backend and renderer IPC paths call through its daemon socket / CLI forwarding so AX element state stays warm.
- `emu-cua-driver mcp` remains available for external MCP clients, but Emu does not use it for the integrated coworker path.
9.7 Public-DMG deferred entitlements from the spec: when hardened runtime/notarization is enabled, re-sign embedded `emu-cua-driver` with `disable-library-validation`, `allow-dyld-environment-variables`, and `automation.apple-events` entitlements before sealing the DMG.

---

## 3. Critical Open Questions (resolve before Phase 4)

1. **Binary invocation surface for backend tools** — Python MCP client vs shelling out to `emu-cua-driver call`? *Default: shell out for v1.*
2. **Mode default in fresh sessions** — spec and current code default to `"coworker"`. Do not flip this in implementation unless the product decision changes.
3. **Single child vs per-session children** — `EmuCuaDriverProcess` keeps one global child. Is that fine for multiple concurrent sessions? *Yes for v1; cua-driver is stateless per call. Element-index cache is per `(pid, window_id)` so cross-session collisions are unlikely.*
4. **`element_index` validation** — resolved by the Phase-4 single-channel pivot: `element_index` lives on `cua_*` tool arguments, not renderer `Action`, so no Action-model validator is needed.
5. **Horizontal scroll conflict** — resolved as deferred/no-op in renderer coworker actions; the model uses `cua_scroll(direction="left"|"right")`.

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

- Overview: `frontend/coworker-driver/README.md`
- Skill: `frontend/coworker-driver/SKILL.md`
- Tests: `frontend/coworker-driver/TESTS.md`
- Web apps: `frontend/coworker-driver/WEB_APPS.md`
- Fork operations and divergences: `frontend/coworker-mode/emu-driver/UPSTREAM_CHANGES.md`
- Upstream: https://github.com/trycua/cua/tree/main/libs/cua-driver
- macOS internals: https://github.com/trycua/cua/blob/main/blog/inside-macos-window-internals.md
