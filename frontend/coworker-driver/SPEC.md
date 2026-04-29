# Co-worker Mode — Functional Spec

**Status:** Approved design, ready to implement.
**Owner:** TBD
**Last updated:** 2026-04-29

## References

- **cua-driver source:** https://github.com/trycua/cua/tree/main/libs/cua-driver
- **cua-driver docs:** https://cua.ai/docs/cua-driver
- **cua-driver tool output format:** https://github.com/trycua/cua/blob/main/libs/cua-driver/docs/tool-output-format.md
- **Inside macOS Window Internals (background-computer-use blog):** https://github.com/trycua/cua/blob/main/blog/inside-macos-window-internals.md
- **Existing Emu permission docs:** `MACOS_PERMISSIONS.md`

---

## 1. Goal

Add a **co-worker** mode to Emu where the model still drives Emu's existing harness end-to-end, but the **physical actuation** of mouse/keyboard/screenshots happens via the [`cua-driver`](https://github.com/trycua/cua/tree/main/libs/cua-driver) Swift binary instead of `cliclick`/`CGEvent`/`desktopCapturer`. This lets the model click/type/scroll on a target window **without moving the user's cursor or stealing focus**, so the user can keep working in another window while the agent runs.

When the toggle is on, **only two things change** vs. today's `remote` mode:

1. **The system prompt** — backend selects a co-worker prompt instead of the default one, based on `agent_mode` already in the request payload.
2. **The execution layer** — frontend dispatcher routes to a new `frontend/cua-driver-commands/` folder instead of `frontend/actions/`, based on the same `agent_mode`.

**Everything else stays identical.** Same chat UI, same side-panel trace cards, same step badges, same Stop button (`POST /agent/stop`), same border window, same session/WebSocket plumbing. No menu-bar pill, no global hotkey, no overlay, no separate timeline.

## 2. Non-goals (v1)

- Element-indexed actions for non-trivial canvas/WebGL surfaces (Blender, games). cua-driver itself recommends pixel fallback there; we'll inherit that.
- A "watch the model work" preview window (model just acts; trace cards are the feedback).
- Hardened-runtime / notarized signing flow. We ship ad-hoc-signed today; entitlements work is deferred to first public DMG release (see §11).
- Per-app permission gating UI. cua-driver inherits Emu.app's Accessibility + Screen Recording grants — the user already grants both.
- Replacing the rest of Emu's tool surface (memory daemon, `use_skill`, `update_plan`, Hermes, etc.). All co-worker-irrelevant tools stay.
- Drag, relative move/drag, triple-click, get-mouse-position, horizontal-scroll. Deferred — co-worker action set is the §6 table only.

---

## 3. Today's architecture (where we're forking)

### 3.1 The `agent_mode` payload is already plumbed end-to-end

`frontend/state/store.js`:
```js
const AGENT_MODES = new Set(['coworker', 'remote']);
let _savedAgentMode = 'coworker';
try {
    const saved = localStorage.getItem('emu-agent-mode');
    if (AGENT_MODES.has(saved)) _savedAgentMode = saved;
} catch(e) {}

const state = {
    // ...
    agentMode: _savedAgentMode,
    // ...
};
```

`frontend/components/chrome/WindowHeader.js` (the existing toggle — **do not redesign**):
```js
const AGENT_MODES = ['coworker', 'remote'];
// ...
AGENT_MODES.forEach((mode) => {
    buttons[mode].addEventListener('click', () => {
        if (store.state.isGenerating) return;
        store.setAgentMode(mode);
        sync();
    });
});
```

`frontend/services/api.js` already sends it:
```js
async function postStep({ sessionId, userMessage, base64Screenshot, agentMode }) {
    return fetchWithTimeout(`${BACKEND_URL}/agent/step`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
            session_id:        sessionId,
            user_message:      userMessage || '',
            base64_screenshot: base64Screenshot || '',
            agent_mode:        agentMode || 'coworker',
        }),
    }, 120_000);
}
```

`backend/models/request.py` already accepts it:
```py
class AgentRequest(BaseModel):
    # ...
    agent_mode: Literal["coworker", "remote"] = Field(
        default="coworker",
        description="Selected frontend collaboration mode"
    )
```

`backend/context_manager/context.py` already stores it per session:
```py
def set_agent_mode(self, session_id: str, mode: str) -> None:
    if mode not in ("coworker", "remote"):
        raise ValueError(...)
    self._agent_mode[session_id] = mode
```

**It is currently a label only — nothing branches on it.** This spec adds the two branches.

### 3.2 Action dispatch funnel (frontend)

Single dispatcher: `frontend/actions/actionProxy.js` exports `ACTION_MAP` keyed by backend `ActionType` strings. Each entry calls one of `frontend/actions/*.js`, which in turn invokes an IPC channel registered in `main.js` via `frontend/actions/index.js#registerAll`. Most leaf actions shell out to `cliclick` / `CGEvent` / `osascript` via `psProcess`.

This is the only seam we need to touch on the frontend. We do **not** modify `actionProxy.js`'s remote (cliclick) leaves — we add a sibling co-worker dispatch tree and pick which one to call based on `store.state.agentMode`.

### 3.3 Backend prompt builder

`backend/prompts/__init__.py`:
```py
from .system_prompt import SYSTEM_PROMPT, build_system_prompt, get_static_prompt
```

`backend/prompts/system_prompt.py:24`:
```py
def build_system_prompt(
    workspace_context: str = "",
    session_id: str = "",
    bootstrap_mode: bool = False,
    bootstrap_content: str = "",
    device_details: dict | None = None,
    use_omni_parser: bool = False,
    hermes_setup_mode: bool = False,
) -> str:
    ...
```

Called from `backend/context_manager/context.py:96` and `:512`. We add an `agent_mode` parameter and branch.

### 3.4 Backend tool dispatcher

`backend/tools/dispatcher.py#execute_agent_tool` is a flat `if/elif` over tool name. We branch its registration / availability by mode (the dispatcher itself stays).

### 3.5 Existing memory daemon (parallel pattern we'll reuse)

`daemon/launchd/com.emu.memory-daemon.plist.template` is the model for **how Emu installs a long-running helper**, but the cua-driver process is **not** a launchd daemon — it's a child process owned by Electron main, started/stopped with the app. Pattern reference only:
```xml
<key>ProgramArguments</key>
<array>
    <string>/bin/bash</string>
    <string>{{REPO}}/daemon/launchd/run.sh</string>
</array>
```

The Emu memory daemon is unchanged by this spec — it keeps running on its 120-second tick, separate concern.

---

## 4. emu-cua-driver — what it is and how it runs

### 4.1 The binary

emu-cua-driver ships as `EmuCuaDriver.app` containing a single binary at `Contents/MacOS/emu-cua-driver`. The fork is installed from:

```bash
# From the forked repo at frontend/coworker-mode/emu-driver/
npm run build    # generates EmuCuaDriver.app
```

…installs `/Applications/EmuCuaDriver.app` and symlinks `~/.local/bin/emu-cua-driver`.

### 4.2 Subcommands we care about (from `Sources/EmuCuaDriverCLI/EmuCuaDriverCommand.swift`)

```
emu-cua-driver mcp                   # MCP stdio server — persistent, what Emu spawns
emu-cua-driver call <tool> <json>    # one-shot; auto-forwards to running daemon
emu-cua-driver list-tools            # tool catalog
emu-cua-driver serve                 # background daemon w/ Unix socket (optional)
emu-cua-driver check_permissions     # verify AX + Screen Recording grants
```

### 4.3 Tools the co-worker mode uses

Surveyed from `Sources/CuaDriverServer/Tools/*.swift`. These are the only ones v1 maps to:

| Tool | Required args | Optional args |
|---|---|---|
| `screenshot` | — | `window_id` |
| `list_apps` | — | — |
| `launch_app` | `bundle_id` or `name` | — |
| `get_window_state` | `pid`, `window_id` | — |
| `click` | `pid` | `element_index` **or** (`window_id`,`x`,`y`) |
| `double_click` | `pid` | same as click |
| `right_click` | `pid` | same as click |
| `scroll` | `pid`, `direction` | `amount` (default 3), `element_index`, `window_id` |
| `type_text` | `pid`, `text` | `element_index`, `window_id` |
| `hotkey` | `pid`, `keys` (array) | — |

`screenshot` returns a SOM payload; the human-readable text portion looks like (from `docs/tool-output-format.md`):
```
✅ Screenshot — 1920x1080 png

On-screen windows:
- Terminal (pid 7476) "cua — Claude Code" [window_id: 2102]
- Google Chrome (pid 13313) "Download — Blender" [window_id: 1941]
→ Call get_window_state(pid, window_id) to inspect a window's UI.
```
And `get_window_state` returns the AX outline with `[N]`-indexed nodes, e.g.:
```
✅ Blender — 11 elements, turn 3 + screenshot
- AXApplication "Blender"
  - [0] AXWindow "* Untitled - Blender 5.1.1" actions=[AXRaise]
    - [1] AXButton ...
```
The `[N]` numbers are the **`element_index`** values the model passes back to `click`/`type_text`/`scroll`.

### 4.4 Permissions

`cua-driver check_permissions` confirms:
- **Accessibility** — required.
- **Screen Recording** — required for `screenshot` / `get_window_state` SOM mode.

These are the **same two permissions Emu already requires** today (`MACOS_PERMISSIONS.md`). Because the cua-driver process runs as a **child of Emu.app** (see §5), and is invoked by the same user, the Accessibility + Screen Recording grants on Emu.app cover it.

> ⚠️ Reality check during implementation: macOS sometimes requires the **child binary path** to be added to the AX list independently. If `check_permissions` reports denied while Emu has both grants, we surface a one-time "Grant cua-driver" CTA in the existing permissions UI (same dialogs already wired in `main.js` lines 123-158). No new permission UI surface — reuse what's there.

---

## 5. Bundling & process lifecycle

### 5.1 Where the binary lives

**Dev (source checkout):**
- Developer runs the cua-driver installer once: `/bin/bash -c "$(curl -fsSL …/install.sh)"`.
- Emu resolves the binary at `~/.local/bin/cua-driver` (or `/Applications/CuaDriver.app/Contents/MacOS/cua-driver` as fallback).

**Packaged (DMG):**
- We bundle `cua-driver` inside `Emu.app/Contents/Resources/cua-driver/cua-driver` via `electron-builder`'s `extraResources`.
- At runtime, Emu prefers the bundled binary (`process.resourcesPath`).

This mirrors the existing `backendProcess.js` pattern (`frontend/process/backendProcess.js:23-42`):
```js
function _resolveBackendCommand(app) {
    if (app && app.isPackaged) {
        const resourcesPath = process.resourcesPath;
        const candidates = [
            path.join(resourcesPath, 'backend', 'emu-backend'),
            // ...
        ];
        for (const c of candidates) {
            if (fs.existsSync(c)) return { cmd: c, args: [], cwd: path.dirname(c) };
        }
        return null;
    }
    // dev branch ...
}
```

### 5.2 New file: `frontend/process/EmuCuaDriverProcess.js`

Owns the emu-cua-driver subprocess — start, stop, MCP request/response over stdio, restart on crash. Started from `main.js` next to `backendProcess.start(...)`.

```js
// frontend/process/EmuCuaDriverProcess.js
//
// Lifecycle for the emu-cua-driver MCP stdio child process.
// Started in co-worker mode only (lazy: spawned on first co-worker step
// in a session, kept alive until the app quits).

const path = require('path');
const fs = require('fs');
const os = require('os');
const { spawn } = require('child_process');

let _child = null;
let _nextId = 1;
const _pending = new Map(); // id -> { resolve, reject, timeout }
let _stdoutBuf = '';

function _resolveBinary(app) {
    if (app && app.isPackaged) {
        const p = path.join(process.resourcesPath, 'emu-cua-driver', 'emu-cua-driver');
        if (fs.existsSync(p)) return p;
    }
    const local = path.join(os.homedir(), '.local', 'bin', 'emu-cua-driver');
    if (fs.existsSync(local)) return local;
    const appBin = '/Applications/EmuCuaDriver.app/Contents/MacOS/emu-cua-driver';
    if (fs.existsSync(appBin)) return appBin;
    return null;
}

function start({ app }) {
    if (_child) return true;
    const bin = _resolveBinary(app);
    if (!bin) {
        console.warn('[emu-cua-driver] binary not found — co-worker mode unavailable');
        return false;
    }

    console.log(`[emu-cua-driver] spawning ${bin} mcp`);
    _child = spawn(bin, ['mcp'], { stdio: ['pipe', 'pipe', 'pipe'] });

    _child.stdout.setEncoding('utf8');
    _child.stdout.on('data', (chunk) => {
        _stdoutBuf += chunk;
        let nl;
        while ((nl = _stdoutBuf.indexOf('\n')) !== -1) {
            const line = _stdoutBuf.slice(0, nl).trim();
            _stdoutBuf = _stdoutBuf.slice(nl + 1);
            if (!line) continue;
            try {
                const msg = JSON.parse(line);
                const pending = _pending.get(msg.id);
                if (pending) {
                    _pending.delete(msg.id);
                    clearTimeout(pending.timeout);
                    if (msg.error) pending.reject(new Error(msg.error.message || 'emu-cua-driver error'));
                    else           pending.resolve(msg.result);
                }
            } catch (err) {
                console.warn('[emu-cua-driver] non-JSON stdout line:', line);
            }
        }
    });
    _child.stderr.on('data', (d) => process.stderr.write(`[emu-cua-driver] ${d}`));
    _child.on('exit', (code, signal) => {
        console.warn(`[emu-cua-driver] exited code=${code} signal=${signal}`);
        _child = null;
        for (const { reject, timeout } of _pending.values()) {
            clearTimeout(timeout);
            reject(new Error('emu-cua-driver exited'));
        }
        _pending.clear();
    });

    // MCP `initialize` handshake.
    _send({
        jsonrpc: '2.0',
        id: _nextId++,
        method: 'initialize',
        params: {
            protocolVersion: '2025-03-26',
            capabilities: {},
            clientInfo: { name: 'emu', version: require('../../package.json').version },
        },
    }).catch((err) => console.warn('[emu-cua-driver] initialize failed:', err.message));

    return true;
}

function stop() {
    if (!_child) return;
    try { _child.kill('SIGTERM'); } catch (_) {}
    _child = null;
}

function _send(msg, timeoutMs = 15_000) {
    return new Promise((resolve, reject) => {
        if (!_child) return reject(new Error('emu-cua-driver not running'));
        const id = msg.id;
        const timeout = setTimeout(() => {
            _pending.delete(id);
            reject(new Error(`emu-cua-driver request ${msg.method} timed out`));
        }, timeoutMs);
        _pending.set(id, { resolve, reject, timeout });
        _child.stdin.write(JSON.stringify(msg) + '\n');
    });
}

async function callTool(name, args) {
    if (!_child) start({ app: require('electron').app });
    if (!_child) throw new Error('emu-cua-driver unavailable');
    return _send({
        jsonrpc: '2.0',
        id: _nextId++,
        method: 'tools/call',
        params: { name, arguments: args || {} },
    });
}

module.exports = { start, stop, callTool };
```

### 5.3 Wiring into `main.js`

Add to the `app.whenReady().then(...)` block in `main.js`, alongside `backendProcess.start(...)` and `daemonInstaller.maybeInstall(...)`:

```js
// main.js — additions inside app.whenReady()
const emuCuaDriverProcess = require('./frontend/process/EmuCuaDriverProcess');
// (lazy — don't start until first co-worker step). But register IPC up front:
require('./frontend/cua-driver-commands').registerAll(ipcMain, {
    callTool: emuCuaDriverProcess.callTool,
    getMainWindow: () => mainWindow,
});
```

And in `app.on('will-quit', ...)`:
```js
emuCuaDriverProcess.stop();
```

The emu-cua-driver child is **lazy-started** the first time a co-worker action is dispatched (via `emuCuaDriverProcess.callTool` calling `start()` if not already running). This means a user who only runs in remote mode never spawns it.

---

## 6. The new `frontend/cua-driver-commands/` folder

Mirror the existing `frontend/actions/` shape — one file per action, each exporting `{ <fn>, register }`, plus an `index.js` barrel.

### 6.1 Action map (v1 only)

| Backend `ActionType` | cua-driver tool | Args mapping |
|---|---|---|
| `screenshot` | `screenshot` | `{ window_id? }` (session-scoped target) |
| `left_click` | `click` | `{ pid, element_index }` or `{ pid, x, y }` (pixel fallback) |
| `right_click` | `right_click` | same |
| `double_click` | `double_click` | same |
| `triple_click` | *not in v1* | — |
| `navigate_and_click` | folded into `left_click` (no separate "navigate" — cua-driver clicks where the model says, no cursor move) | — |
| `navigate_and_right_click` | folded into `right_click` | — |
| `navigate_and_triple_click` | *not in v1* | — |
| `mouse_move` | *not in v1* (no shared cursor) | — |
| `relative_mouse_move` | *not in v1* | — |
| `drag`, `relative_drag` | *not in v1* | — |
| `scroll` | `scroll` | `{ pid, direction, amount, element_index?, window_id? }` |
| `horizontal_scroll` | `scroll` with horizontal direction | same |
| `type_text` | `type_text` | `{ pid, text, element_index? }` |
| `key_press` | `hotkey` | `{ pid, keys: [<modifiers>..., <key>] }` |
| `wait` | (renderer-side `setTimeout` — unchanged) | — |
| `shell_exec` | (renderer shellExec — unchanged) | — |
| `done` | (no-op — unchanged) | — |

### 6.2 The dispatcher branch

Modify `frontend/actions/executor.js` to read mode and pick a dispatcher. **This is the only file in `frontend/actions/` that we touch.**

```js
// frontend/actions/executor.js — modified
const { dispatchAction: dispatchRemote } = require('./actionProxy');
const { dispatchAction: dispatchCoworker } = require('../cua-driver-commands/actionProxy');
const store = require('../state/store');
const api = require('../services/api');

async function executeAction(action, stepEl) {
    const dispatch = store.state.agentMode === 'coworker'
        ? dispatchCoworker
        : dispatchRemote;
    console.log(`[executeAction] mode=${store.state.agentMode} dispatching ${action.type}`);
    const result = await dispatch(action);
    // ... rest is byte-identical to today (badge update + notifyActionComplete)
}
```

### 6.3 `frontend/cua-driver-commands/actionProxy.js` (sibling of `frontend/actions/actionProxy.js`)

Same shape: `ACTION_MAP` keyed on backend `ActionType` strings, each entry's `dispatch()` calls into `emuCuaDriverProcess.callTool(...)` via IPC.

```js
// frontend/cua-driver-commands/actionProxy.js
const { ipcRenderer } = require('electron');

const ACTION_MAP = {
    screenshot: {
        label: 'Screenshot', icon: '📸', ipc: 'emu-cua:screenshot',
        dispatch: async (a) => ipcRenderer.invoke('emu-cua:screenshot', { window_id: a.window_id }),
        describe: () => 'Capture window screenshot',
    },
    left_click: {
        label: 'Left Click', icon: '🖱️', ipc: 'emu-cua:click',
        dispatch: async (a) => ipcRenderer.invoke('emu-cua:click', _clickArgs(a)),
        describe: (a) => a.element_index != null
            ? `Left click on element [${a.element_index}]`
            : `Left click at (${a.coordinates?.x}, ${a.coordinates?.y})`,
    },
    right_click: {
        label: 'Right Click', icon: '🖱️', ipc: 'emu-cua:right-click',
        dispatch: async (a) => ipcRenderer.invoke('emu-cua:right-click', _clickArgs(a)),
        describe: () => 'Right click',
    },
    double_click: {
        label: 'Double Click', icon: '🖱️', ipc: 'emu-cua:double-click',
        dispatch: async (a) => ipcRenderer.invoke('emu-cua:double-click', _clickArgs(a)),
        describe: () => 'Double click',
    },
    // navigate_and_click → just left_click (no cursor move in co-worker mode)
    navigate_and_click: {
        label: 'Click', icon: '🖱️', ipc: 'emu-cua:click',
        dispatch: async (a) => ipcRenderer.invoke('emu-cua:click', _clickArgs(a)),
        describe: (a) => a.element_index != null
            ? `Click element [${a.element_index}]`
            : `Click at (${a.coordinates?.x}, ${a.coordinates?.y})`,
    },
    navigate_and_right_click: { /* same pattern */ },
    scroll: {
        label: 'Scroll', icon: '📜', ipc: 'emu-cua:scroll',
        dispatch: (a) => ipcRenderer.invoke('emu-cua:scroll', {
            pid: a.pid,
            direction: a.direction,
            amount: a.amount || 3,
            element_index: a.element_index,
            window_id: a.window_id,
        }),
        describe: (a) => `Scroll ${a.direction} ${a.amount || 3}`,
    },
    horizontal_scroll: { /* same with direction left/right */ },
    type_text: {
        label: 'Type', icon: '⌨️', ipc: 'emu-cua:type',
        dispatch: (a) => ipcRenderer.invoke('emu-cua:type', {
            pid: a.pid,
            text: a.text,
            element_index: a.element_index,
        }),
        describe: (a) => `Type "${a.text}"`,
    },
    key_press: {
        label: 'Key Press', icon: '⌨️', ipc: 'emu-cua:hotkey',
        dispatch: (a) => ipcRenderer.invoke('emu-cua:hotkey', {
            pid: a.pid,
            keys: [...(a.modifiers || []), a.key],
        }),
        describe: (a) => `Press ${[...(a.modifiers || []), a.key].join('+')}`,
    },
    // wait, shell_exec, done, memory_read — copy from actions/actionProxy.js verbatim
    // (these don't touch the actuator).
};

function _clickArgs(a) {
    // Element-indexed first, pixel fallback only when element_index is absent.
    if (a.element_index != null) {
        return { pid: a.pid, element_index: a.element_index, window_id: a.window_id };
    }
    return {
        pid: a.pid,
        x: a.coordinates?.x ?? a.x,
        y: a.coordinates?.y ?? a.y,
        window_id: a.window_id,
    };
}

// dispatchAction + withTimeout + describeAction are copied byte-identical
// from frontend/actions/actionProxy.js (only ACTION_MAP differs).
async function dispatchAction(action) {
    const entry = ACTION_MAP[action.type];
    if (!entry) return { success: false, ipc: null, description: `Unknown: ${action.type}` };
    const description = entry.describe(action);
    if (!entry.dispatch) return { success: true, ipc: entry.ipc, description };
    try {
        const result = await entry.dispatch(action);
        return { success: result?.success !== false, ipc: entry.ipc, description, output: result?.output ?? null };
    } catch (err) {
        return { success: false, ipc: entry.ipc, description, error: err.message };
    }
}

module.exports = { ACTION_MAP, dispatchAction };
```

### 6.4 `frontend/cua-driver-commands/index.js` — IPC registration

```js
// frontend/cua-driver-commands/index.js
//
// Registers IPC handlers that thin-wrap emuCuaDriverProcess.callTool().
// Each handler: parse args, call MCP tool, map result.

function registerAll(ipcMain, deps) {
    const { callTool } = deps;

    const wrap = (toolName) => async (_event, args) => {
        try {
            const result = await callTool(toolName, args);
            return { success: !result?.isError, output: _summarize(result) };
        } catch (err) {
            return { success: false, error: err.message };
        }
    };

    ipcMain.handle('emu-cua:screenshot',   wrap('screenshot'));
    ipcMain.handle('emu-cua:click',        wrap('click'));
    ipcMain.handle('emu-cua:right-click',  wrap('right_click'));
    ipcMain.handle('emu-cua:double-click', wrap('double_click'));
    ipcMain.handle('emu-cua:scroll',       wrap('scroll'));
    ipcMain.handle('emu-cua:type',         wrap('type_text'));
    ipcMain.handle('emu-cua:hotkey',       wrap('hotkey'));
    ipcMain.handle('emu-cua:list-apps',    wrap('list_apps'));
    ipcMain.handle('emu-cua:launch-app',   wrap('launch_app'));
    ipcMain.handle('emu-cua:get-window-state', wrap('get_window_state'));
}

function _summarize(result) {
    // MCP CallTool.Result has { content: [{type, text|data}], isError, structuredContent }.
    // Return text content concatenated for trace cards; image bytes are
    // handled separately by the screenshot IPC (returns base64).
    if (!result?.content) return null;
    return result.content.filter(c => c.type === 'text').map(c => c.text).join('\n');
}

module.exports = { registerAll };
```

### 6.5 Screenshot path divergence

In **remote** mode, screenshots come from Electron's `desktopCapturer` (`frontend/actions/screenshot.js`). In **co-worker** mode they come from `emu-cua:screenshot` (emu-cua-driver), which captures **only the target window**, occluded-safe, no user-cursor pollution.

The renderer's screenshot caller must branch on mode the same way `executor.js` does. Cleanest spot: wherever the renderer currently calls `captureScreenshot()` to build the `base64_screenshot` payload for `postStep()`. Add a thin wrapper:

```js
// frontend/services/captureForStep.js (new)
const store = require('../state/store');
const remote = require('../actions/screenshot');
const { ipcRenderer } = require('electron');

async function captureForStep(sessionTarget /* { pid, window_id } | null */) {
    if (store.state.agentMode === 'coworker' && sessionTarget?.window_id) {
        const r = await ipcRenderer.invoke('emu-cua:screenshot', {
            window_id: sessionTarget.window_id,
            return_image: true,
        });
        return { success: r.success, base64: r.base64 };
    }
    return remote.captureScreenshot();
}
module.exports = { captureForStep };
```

`emu-cua:screenshot` IPC handler (`cua-driver-commands/index.js`) needs an extra branch when `return_image: true` to extract the image content block from the MCP result and base64-encode it. emu-cua-driver's MCP `screenshot` tool returns the PNG as an image content block:
```js
const imgBlock = result.content.find(c => c.type === 'image');
return { success: true, base64: imgBlock?.data, output: _summarize(result) };
```

---

## 7. Backend changes

### 7.1 New file: `backend/prompts/emu_coworker_system_prompt.py`

Skeleton:

```py
"""
backend/prompts/emu_coworker_system_prompt.py

System prompt for co-worker mode. Differs from the default prompt in:

  - Tool surface: model addresses windows by (pid, window_id) and AX nodes
    by element_index (from emu-cua-driver's screenshot/get_window_state SOM
    output) instead of normalized [0,1] pixel coordinates.
  - No cursor semantics: there is no shared cursor; "navigate then click"
    becomes a single click.
  - Targeting workflow: model must call list_apps OR raise_app first to
    learn the target {pid, window_id}, then act on it.
  - Background guarantee: actions do NOT raise the target window, do NOT
    move the user's cursor, and do NOT steal focus. The user is working
    alongside in another app.
"""

from datetime import datetime

def build_emu_coworker_system_prompt(
    workspace_context: str = "",
    session_id: str = "",
    device_details: dict | None = None,
) -> str:
    today = datetime.now().strftime("%A, %B %d, %Y")
    now = datetime.now().strftime("%H:%M")
    return _EMU_COWORKER_BASE.format(
        today=today, now=now, session_id=session_id,
        workspace_context=workspace_context,
        device_block=_format_device(device_details),
    )

_EMU_COWORKER_BASE = """\
You are Emu in CO-WORKER mode. The user is working alongside you in a
DIFFERENT window. Your actions must NOT move their cursor, raise the
target window to the foreground, or steal keyboard focus.

# Targeting

Every click/type/scroll requires a target process id (pid) and usually a
window_id and an element_index. Get these by:

  1. Call `raise_app(name)` (returns {pid, window_id}) to focus an app
     for AX-tree purposes; it does NOT raise the window visually.
  2. Or call `list_running_apps()` to enumerate all open windows.
  3. Then call `screenshot()` and/or `get_window_state(pid, window_id)`
     to see the SOM-indexed AX tree. Each interactable node has a
     `[N]` prefix — that N is the `element_index` you pass back.

# Action emission

Click an element:        {{"type": "left_click", "pid": <pid>, "window_id": <wid>, "element_index": <n>}}
Type into a field:       {{"type": "type_text", "pid": <pid>, "element_index": <n>, "text": "..."}}
Scroll inside a window:  {{"type": "scroll", "pid": <pid>, "window_id": <wid>, "direction": "down", "amount": 3}}
Hotkey:                  {{"type": "key_press", "pid": <pid>, "key": "t", "modifiers": ["cmd"]}}

Pixel fallback (canvas/WebGL only — Blender, games, browser <canvas>):
  {{"type": "left_click", "pid": <pid>, "window_id": <wid>, "x": 540, "y": 320}}

# Today
{today} {now}
Session: {session_id}
{device_block}

# Workspace
{workspace_context}
"""

def _format_device(d):
    if not d: return ""
    return f"System: {d.get('os_name','macOS')}"
```

### 7.2 Modify `backend/prompts/system_prompt.py#build_system_prompt`

Add `agent_mode` parameter and dispatch:

```py
def build_system_prompt(
    workspace_context: str = "",
    session_id: str = "",
    bootstrap_mode: bool = False,
    bootstrap_content: str = "",
    device_details: dict | None = None,
    use_omni_parser: bool = False,
    hermes_setup_mode: bool = False,
    agent_mode: str = "remote",  # NEW
) -> str:
    if bootstrap_mode:
        # ... unchanged
    if hermes_setup_mode:
        # ... unchanged
    if agent_mode == "coworker":
        from .emu_coworker_system_prompt import build_emu_coworker_system_prompt
        return build_emu_coworker_system_prompt(
            workspace_context=workspace_context,
            session_id=session_id,
            device_details=device_details,
        )
    # ... fall through to existing remote prompt body unchanged
```

### 7.3 Pipe `agent_mode` into the prompt builder

Two call sites in `backend/context_manager/context.py` (lines ~96 and ~512). Both have `session_id` available; both can pull `agent_mode` from `self._agent_mode.get(session_id, "coworker")`:

```py
# context.py (both call sites)
agent_mode = self._agent_mode.get(session_id, "coworker")
system_prompt = build_system_prompt(
    workspace_context=workspace_ctx,
    session_id=session_id,
    bootstrap_mode=bootstrap_mode,
    bootstrap_content=bootstrap_content,
    device_details=device_info,
    use_omni_parser=USE_OMNI_PARSER,
    hermes_setup_mode=hermes_setup_mode,
    agent_mode=agent_mode,  # NEW
)
```

### 7.4 Tool surface fork

The user requested **one new tool**: get the pid of the raised app. Cleanest is to **extend `raise_app`** to return `{pid, window_id, app_name}` instead of a status string when in co-worker mode, plus add a sibling `list_running_apps`.

`backend/tools/raise_app.py` — current return is a string (`"<name> is raised - continue"`). Modify to return JSON in co-worker mode:

```py
# backend/tools/raise_app.py — modified
import subprocess, json, platform

def handle_raise_app(app_name: str, agent_mode: str = "remote") -> str:
    # ... existing validation ...
    if platform.system() != "Darwin":
        return f"ERROR: raise_app only works on macOS"

    # Existing osascript activate (unchanged behavior in remote mode):
    script = f'tell application "{app_name}" to activate'
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)

    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or "(no stderr)"
        return f"ERROR: could not raise '{app_name}'. osascript exit={proc.returncode}: {err}"

    if agent_mode != "coworker":
        return f"{app_name} is raised - continue"

    # Co-worker mode: also resolve {pid, window_id} via NSRunningApplication
    # + AX. Cheapest path: shell out to emu-cua-driver `call list_apps`, then
    # filter by name. Match name case-insensitively.
    try:
        import shutil
        bin = shutil.which("emu-cua-driver") or "/Applications/EmuCuaDriver.app/Contents/MacOS/emu-cua-driver"
        out = subprocess.run([bin, "call", "list_apps", "--compact"],
                             capture_output=True, text=True, timeout=5)
        apps = json.loads(out.stdout)  # exact shape: see ListAppsTool
        match = next(
            (a for a in apps.get("apps", []) if a["name"].lower() == app_name.lower()),
            None,
        )
        if match:
            return json.dumps({
                "app_name": match["name"],
                "pid": match["pid"],
                "window_id": match.get("front_window_id"),
                "status": "raised",
            })
    except Exception as e:
        # Fall through with a structured error the model can parse.
        return json.dumps({"status": "raised_no_pid", "error": str(e), "app_name": app_name})

    return json.dumps({"status": "raised_no_match", "app_name": app_name})
```

Add a new tool `list_running_apps`:

```py
# backend/tools/list_running_apps.py
import subprocess, shutil, json

def handle_list_running_apps() -> str:
    bin = shutil.which("emu-cua-driver") or "/Applications/EmuCuaDriver.app/Contents/MacOS/emu-cua-driver"
    out = subprocess.run([bin, "call", "list_apps", "--compact"],
                         capture_output=True, text=True, timeout=5)
    if out.returncode != 0:
        return f"ERROR: list_apps failed: {out.stderr.strip()}"
    return out.stdout.strip()
```

Wire both into `backend/tools/dispatcher.py#execute_agent_tool`:

```py
elif name == "raise_app":
    agent_mode = args.get("agent_mode") or context_manager._agent_mode.get(session_id, "remote")
    return handle_raise_app(args.get("app_name", ""), agent_mode=agent_mode)

elif name == "list_running_apps":
    return handle_list_running_apps()
```

### 7.5 Action models — extend for co-worker fields

`backend/models/response.py` (the AgentResponse / Action types). Add optional `pid`, `window_id`, `element_index` to the click/type/scroll action variants. They are ignored in remote mode and required in co-worker mode (the prompt enforces this; the dispatcher tolerates either shape).

---

## 8. Stop button — no changes needed

`frontend/services/api.js:88` already calls `POST /agent/stop`. `backend/main.py:670` already handles it by halting the agent loop. The loop is what drives both cliclick and cua-driver actions — same behavior, no work.

Note: an in-flight cua-driver `tools/call` may complete before the loop sees the stop signal. That's the same semantics today (a cliclick command in flight doesn't get cancelled mid-shell-out). No regression.

---

## 9. Permissions

Same as today's `MACOS_PERMISSIONS.md`. No new permissions surface in co-worker mode:

- **Accessibility** — required, already requested.
- **Screen Recording** — required, already requested.

Recommended **first co-worker run** flow:
1. App detects `agent_mode === 'coworker'` for the first time in this install.
2. Spawn `cua-driver mcp` lazily.
3. Send a `tools/call` for `check_permissions`. If denied for cua-driver specifically, surface the existing permissions UI (`main.js:145-158` `permissions:open` IPC) pointing the user at System Settings to add the cua-driver child binary path to the AX list. (In practice, since cua-driver is launched as a child of Emu.app, AX inherits — but `check_permissions` is the source of truth.)

---

## 10. Running the daemons (dev)

There are now **two** background helpers. Both keep their existing/current ownership.

### 10.1 Emu memory daemon (unchanged)

LaunchAgent installed at `~/Library/LaunchAgents/com.emu.memory-daemon.plist`. Already managed by `daemon/install_macos.py`. Runs every 120 s. **Not touched by this spec.**
```bash
python3 -m daemon.install_macos status
python3 -m daemon.install_macos run-now
python3 -m daemon.install_macos uninstall
```

### 10.2 emu-cua-driver MCP child process (new)

**Not a launchd daemon.** Owned by Electron main, lifecycle = app lifecycle. Lazy-started on first co-worker action; killed on `app.will-quit`.

**Dev one-time setup** (the developer installs emu-cua-driver on their machine; Emu picks it up):
```bash
# From frontend/coworker-mode/emu-driver/
npm run build    # generates EmuCuaDriver.app in /Applications/
emu-cua-driver check_permissions    # grant Accessibility + Screen Recording when prompted
```

**Verify it works standalone:**
```bash
emu-cua-driver list-tools
emu-cua-driver call list_apps
```

**Inside Emu (dev run):**
```bash
npm run dev    # spawns Electron → Emu starts backend → on first co-worker step, spawns emu-cua-driver mcp
```

**Manual smoke test of the MCP child the way Emu spawns it:**
```bash
emu-cua-driver mcp
# then on stdin paste a tools/call JSON-RPC envelope:
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_apps","arguments":{}}}
```

### 10.3 Optional: `emu-cua-driver serve` background daemon

emu-cua-driver has a **separate** `serve` mode (not what we use). It runs as a background daemon with a Unix socket so multiple short-lived `emu-cua-driver call` invocations share AppStateRegistry across runs. **We don't need this** — Emu owns a long-lived `emu-cua-driver mcp` child, so element_index state is already coherent within our process. Document for awareness only.

---

## 11. Shipping (open-source DMG plan)

**Phase 1 — pre-release / OSS dev:** ad-hoc signed Emu, drop `cua-driver` binary into `Emu.app/Contents/Resources/cua-driver/`. No notarization. Forks build locally with the same setup. Users who try the DMG do a one-time right-click → Open.

**Phase 2 — first public DMG release (deferred):**
- Apple Developer ID + notarization for Emu.app.
- Hardened runtime ON.
- The embedded `cua-driver` binary needs its own entitlements file at sign time:
  ```xml
  <!-- Resources/cua-driver/cua-driver.entitlements -->
  <plist version="1.0"><dict>
    <key>com.apple.security.cs.disable-library-validation</key><true/>
    <key>com.apple.security.cs.allow-dyld-environment-variables</key><true/>
    <key>com.apple.security.automation.apple-events</key><true/>
  </dict></plist>
  ```
- Re-sign cua-driver with our Developer ID + the entitlements above before sealing the DMG.

These are post-v1 tasks — flagged here so they aren't forgotten.

---

## 12. UI inventory — what stays exactly the same

To eliminate ambiguity: every one of these stays byte-identical between modes.

- Mac chrome bar (`frontend/components/chrome/MacChrome.js`).
- Window header + agent-mode toggle + status pill (`WindowHeader.js`).
- Side panel + chat list + composer + suggestions.
- Step trace cards + action badges (resolved/failed) + step icons.
- Stop button + its `POST /agent/stop` wiring.
- Border window (`frontend/border.html`) — shows during execution in both modes.
- Screenshot capture trigger point (we swap *what* it calls under the hood, not *when*).
- Session lifecycle (`createSession`, `continueSession`, history sidebar).
- Settings, provider config, dark mode, dangerous mode, permissions UI.
- Memory daemon, Hermes, skills, plan, workspace files.

**Only files actually edited:**
- `main.js` — register cua-driver process + cua-driver-commands IPC, kill on quit.
- `frontend/actions/executor.js` — branch on `store.state.agentMode`.
- `backend/prompts/system_prompt.py` — accept `agent_mode`, dispatch.
- `backend/context_manager/context.py` — pass `agent_mode` into builder (2 call sites).
- `backend/tools/raise_app.py` — return JSON in co-worker mode.
- `backend/tools/dispatcher.py` — register `list_running_apps`, thread `agent_mode` to `raise_app`.
- `backend/models/response.py` — add optional `pid`/`window_id`/`element_index` action fields.

**New files:**
- `frontend/process/EmuCuaDriverProcess.js`
- `frontend/cua-driver-commands/index.js`
- `frontend/cua-driver-commands/actionProxy.js`
- `frontend/services/captureForStep.js`
- `backend/prompts/emu_coworker_system_prompt.py`
- `backend/tools/list_running_apps.py`
- (packaging) `Resources/emu-cua-driver/emu-cua-driver` binary + (post-v1) `emu-cua-driver.entitlements`

---

## 13. Failure modes & fallbacks

| Failure | Behavior |
|---|---|
| emu-cua-driver binary missing on dev machine | `emuCuaDriverProcess.start()` returns false; co-worker actions fail with `"emu-cua-driver unavailable"`. Surface a one-time toast: "Install emu-cua-driver: build from `frontend/coworker-mode/emu-driver`". Mode stays selectable so the user can run `check_permissions` and retry. |
| emu-cua-driver child crashes mid-step | `_child.on('exit')` clears `_pending` with reject. The step's IPC returns `{success:false, error:'emu-cua-driver exited'}`. Trace card shows `failed`. Next call lazy-restarts the process. |
| AX permission denied at runtime | `tools/call` returns `isError:true` with text "Accessibility not granted". IPC handler returns `{success:false, error}`. Trace shows `failed`. User opens existing permissions UI and grants; next step succeeds without restart. |
| Element_index stale after layout change | emu-cua-driver returns an error indicating index miss. Model retries with a fresh `screenshot` / `get_window_state` snapshot. Same retry loop today's prompt already encodes for misses. |
| Chromium right-click on web content | emu-cua-driver coerces to left-click silently (documented limitation). Co-worker prompt explicitly tells the model to use AX-indexed right-click on addressable elements only. |
| Canvas-app click (Blender/games) | Pixel fallback. Co-worker prompt directs the model to the `{pid, window_id, x, y}` shape for these apps and warns: this **does** require brief frontmost activation. |

---

## 14. Implementation order (suggested)

1. **Bring up emu-cua-driver locally** — build from fork, run `check_permissions`, run `emu-cua-driver mcp` and exchange a `tools/call list_apps` over stdin.
2. **`EmuCuaDriverProcess.js`** — get the spawn + JSON-RPC pump green with a unit-style test.
3. **`cua-driver-commands/index.js` + `actionProxy.js`** — wire the IPC handlers, smoke-test each one with a hand-crafted action object.
4. **`executor.js` branch** + `captureForStep.js`. Now the frontend can run co-worker actions end-to-end if the model emits the right shapes.
5. **`emu_coworker_system_prompt.py`** + `build_system_prompt(agent_mode=…)` plumbing. Now the backend produces co-worker shaped actions.
6. **`raise_app` JSON return** + `list_running_apps` tool.
7. **`response.py` action shape extension** for `pid`/`window_id`/`element_index`.
8. **End-to-end test:** "Open Chrome and search for ICML 2026" with the user typing in another window. Verify cursor doesn't move and Chrome doesn't raise.
9. **Packaging:** add `extraResources` for the emu-cua-driver binary in `electron-builder` config; verify packaged app spawns the bundled binary.
10. **(Deferred to public release)** Notarization + entitlements for the embedded binary.

---

## 15. Open questions for the implementer

- Does the renderer have a single screenshot call site for `postStep`, or is it scattered? If scattered, the `captureForStep` wrapper needs to be applied at every site (grep for `captureScreenshot(`).
- The model currently reasons about pixel coords and OmniParser-style detections. The co-worker prompt switches to AX `[N]` element indexes. Worth a short eval pass on a few real tasks before considering this done.
- `list_apps` JSON shape from cua-driver `--compact` — verify the field names (`name`, `pid`, `front_window_id`) match what we're parsing in `raise_app`. Adjust the parser if upstream renames.
