// frontend/cua-driver-commands/actionProxy.js
//
// Co-worker mode action dispatcher. Maps backend ActionType → emu-cua-driver
// IPC channels. Similar shape to frontend/actions/actionProxy.js but routes
// to MCP tools via IPC instead of cliclick/CGEvent.
//
// Action shape in co-worker mode includes pid + window_id + element_index
// (or pixel coordinates as fallback for canvas apps).

const { ipcRenderer } = require('electron');

const ACTION_TIMEOUT_MS = 15_000;

// Maps action.type to IPC channel name and description.
// Each entry has:
//   - label: Human-readable name
//   - icon: Emoji for UI
//   - ipc: IPC channel name (cua-driver-commands/index.js handles these)
//   - dispatch: async fn(action) → result (can invoke ipcRenderer or return directly)
//   - describe: fn(action) → description for trace cards
const ACTION_MAP = {
    screenshot: {
        label: 'Screenshot',
        icon: '📸',
        ipc: 'emu-cua:screenshot',
        dispatch: async (a) => ipcRenderer.invoke('emu-cua:screenshot', {
            window_id: a.window_id,
            return_image: true,
        }),
        describe: () => 'Capture target window',
    },

    left_click: {
        label: 'Left Click',
        icon: '🖱️',
        ipc: 'emu-cua:click',
        dispatch: async (a) => {
            const args = _clickArgs(a);
            return ipcRenderer.invoke('emu-cua:click', args);
        },
        describe: (a) => a.element_index != null
            ? `Click element [${a.element_index}]`
            : `Click at (${a.coordinates?.x}, ${a.coordinates?.y})`,
    },

    right_click: {
        label: 'Right Click',
        icon: '🖱️',
        ipc: 'emu-cua:right-click',
        dispatch: async (a) => {
            const args = _clickArgs(a);
            return ipcRenderer.invoke('emu-cua:right-click', args);
        },
        describe: (a) => a.element_index != null
            ? `Right click element [${a.element_index}]`
            : `Right click at (${a.coordinates?.x}, ${a.coordinates?.y})`,
    },

    double_click: {
        label: 'Double Click',
        icon: '🖱️',
        ipc: 'emu-cua:double-click',
        dispatch: async (a) => {
            const args = _clickArgs(a);
            return ipcRenderer.invoke('emu-cua:double-click', args);
        },
        describe: (a) => a.element_index != null
            ? `Double click element [${a.element_index}]`
            : `Double click at (${a.coordinates?.x}, ${a.coordinates?.y})`,
    },

    triple_click: {
        label: 'Triple Click',
        icon: '🖱️',
        ipc: null, // Not implemented in v1
        dispatch: null,
        describe: () => 'Triple click (not in co-worker v1)',
    },

    // navigate_and_click, navigate_and_right_click → just use click/right_click
    // (no cursor movement in co-worker mode; target app stays in background)
    navigate_and_click: {
        label: 'Click',
        icon: '🖱️',
        ipc: 'emu-cua:click',
        dispatch: async (a) => {
            const args = _clickArgs(a);
            return ipcRenderer.invoke('emu-cua:click', args);
        },
        describe: (a) => a.element_index != null
            ? `Click element [${a.element_index}]`
            : `Click at (${a.coordinates?.x}, ${a.coordinates?.y})`,
    },

    navigate_and_right_click: {
        label: 'Right Click',
        icon: '🖱️',
        ipc: 'emu-cua:right-click',
        dispatch: async (a) => {
            const args = _clickArgs(a);
            return ipcRenderer.invoke('emu-cua:right-click', args);
        },
        describe: (a) => a.element_index != null
            ? `Right click element [${a.element_index}]`
            : `Right click at (${a.coordinates?.x}, ${a.coordinates?.y})`,
    },

    navigate_and_triple_click: {
        label: 'Triple Click',
        icon: '🖱️',
        ipc: null, // Not implemented in v1
        dispatch: null,
        describe: () => 'Triple click (not in co-worker v1)',
    },

    mouse_move: {
        label: 'Mouse Move',
        icon: '↗️',
        ipc: null, // Not in co-worker (no shared cursor)
        dispatch: null,
        describe: () => 'Mouse move (not in co-worker mode)',
    },

    relative_mouse_move: {
        label: 'Relative Mouse Move',
        icon: '↗️',
        ipc: null, // Not in co-worker (no shared cursor)
        dispatch: null,
        describe: () => 'Relative mouse move (not in co-worker mode)',
    },

    get_mouse_position: {
        label: 'Get Mouse Position',
        icon: '📍',
        ipc: null, // Not in co-worker (no shared cursor)
        dispatch: null,
        describe: () => 'Get mouse position (not in co-worker mode)',
    },

    scroll: {
        label: 'Scroll',
        icon: '📜',
        ipc: 'emu-cua:scroll',
        dispatch: async (a) => ipcRenderer.invoke('emu-cua:scroll', {
            pid: a.pid,
            direction: a.direction || 'down',
            amount: a.amount || 3,
            element_index: a.element_index,
            window_id: a.window_id,
        }),
        describe: (a) => `Scroll ${a.direction || 'down'} ${a.amount || 3}`,
    },

    horizontal_scroll: {
        label: 'Horizontal Scroll',
        icon: '📜',
        ipc: 'emu-cua:scroll',
        dispatch: async (a) => ipcRenderer.invoke('emu-cua:scroll', {
            pid: a.pid,
            direction: a.direction || 'right',
            amount: a.amount || 3,
            element_index: a.element_index,
            window_id: a.window_id,
        }),
        describe: (a) => `Scroll ${a.direction || 'right'} ${a.amount || 3} (horizontal)`,
    },

    type_text: {
        label: 'Type Text',
        icon: '⌨️',
        ipc: 'emu-cua:type',
        dispatch: async (a) => ipcRenderer.invoke('emu-cua:type', {
            pid: a.pid,
            text: a.text,
            element_index: a.element_index,
            window_id: a.window_id,
        }),
        describe: (a) => `Type "${a.text}"`,
    },

    key_press: {
        label: 'Key Press',
        icon: '⌨️',
        ipc: 'emu-cua:hotkey',
        dispatch: async (a) => ipcRenderer.invoke('emu-cua:hotkey', {
            pid: a.pid,
            keys: [...(a.modifiers || []), a.key],
        }),
        describe: (a) => {
            const mods = (a.modifiers || []).join('+');
            return mods ? `Press ${mods}+${a.key}` : `Press ${a.key}`;
        },
    },

    drag: {
        label: 'Drag',
        icon: '↔️',
        ipc: null, // Not in v1
        dispatch: null,
        describe: () => 'Drag (not in co-worker v1)',
    },

    relative_drag: {
        label: 'Relative Drag',
        icon: '↔️',
        ipc: null, // Not in v1
        dispatch: null,
        describe: () => 'Relative drag (not in co-worker v1)',
    },

    // wait, shell_exec, memory_read, done — copied verbatim from remote mode
    wait: {
        label: 'Wait',
        icon: '⏳',
        ipc: null,
        dispatch: (a) => new Promise(r => setTimeout(r, a.ms || 1000)),
        describe: (a) => `Wait ${a.ms || 1000}ms`,
    },

    shell_exec: {
        label: 'Shell Exec',
        icon: '💻',
        ipc: 'shell:exec',
        dispatch: (a) => {
            // Remote mode uses shellExec from shell.js; for now fallback
            // to IPC if available, else no-op. Can be extended later.
            return Promise.resolve({ success: false, output: 'shell_exec not yet implemented in coworker mode' });
        },
        describe: (a) => `Run: ${(a.command || '').slice(0, 60)}`,
    },

    memory_read: {
        label: 'Memory Read',
        icon: '📖',
        ipc: 'memory:read',
        dispatch: (a) => ipcRenderer.invoke('memory:read', { path: a.path }),
        describe: (a) => `Read: ${a.path || '(no path)'}`,
    },

    done: {
        label: 'Done',
        icon: '✅',
        ipc: null,
        dispatch: null,
        describe: () => 'Task complete',
    },
};

/**
 * Helper to build click args. Prioritizes element_index over pixel fallback.
 */
function _clickArgs(a) {
    if (a.element_index != null) {
        return {
            pid: a.pid,
            element_index: a.element_index,
            window_id: a.window_id,
        };
    }
    // Pixel fallback for canvas/WebGL apps (requires brief foreground activation)
    return {
        pid: a.pid,
        x: a.coordinates?.x ?? a.x,
        y: a.coordinates?.y ?? a.y,
        window_id: a.window_id,
    };
}

/**
 * Race a promise against a timeout.
 */
function withTimeout(promise, ms, label) {
    let timer;
    const timeout = new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms);
    });
    return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

/**
 * Execute a backend action object in co-worker mode.
 */
async function dispatchAction(action) {
    const entry = ACTION_MAP[action.type];
    if (!entry) {
        console.warn('[emu-cua-driver actionProxy] unknown action type:', action.type);
        return { success: false, ipc: null, description: `Unknown: ${action.type}` };
    }

    const description = entry.describe(action);

    if (!entry.dispatch) {
        return { success: true, ipc: entry.ipc, description, needsSpecialHandling: true };
    }

    try {
        console.log(`[emu-cua-driver actionProxy] dispatching ${action.type}...`);
        const result = await withTimeout(
            entry.dispatch(action),
            ACTION_TIMEOUT_MS,
            action.type
        );
        console.log(`[emu-cua-driver actionProxy] ${action.type} done`, result);
        return {
            success: result?.success !== false,
            ipc: entry.ipc,
            description,
            output: result?.output ?? null,
            base64: result?.base64 ?? null,
        };
    } catch (err) {
        console.error(`[emu-cua-driver actionProxy] ${action.type} failed:`, err);
        return { success: false, ipc: entry.ipc, description, error: err.message };
    }
}

module.exports = {
    ACTION_MAP,
    dispatchAction,
};
