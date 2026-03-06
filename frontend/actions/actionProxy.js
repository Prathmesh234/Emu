// frontend/actions/actionProxy.js
//
// Maps backend ActionType → frontend IPC channel + params.
// Single source of truth for dispatching model actions.

const { leftClick }      = require('./leftClick');
const { rightClick }     = require('./rightClick');
const { leftClickOpen }  = require('./leftClickOpen');
const { tripleClick }    = require('./tripleClick');
const { navigateMouse }  = require('./navigate');
const { scroll }         = require('./scroll');
const { captureScreenshot } = require('./screenshot');
const { keyPress, typeText } = require('./keyboard');
const { shellExec }      = require('./exec');

/**
 * ActionType enum values coming from the backend (models/actions.py)
 * mapped to { label, icon, dispatch(action) }
 */
const ACTION_MAP = {
    screenshot: {
        label: 'Screenshot',
        icon:  '📸',
        ipc:   'screenshot:capture',
        dispatch: async () => {
            const result = await captureScreenshot();
            return { success: result.success, base64: result.base64 };
        },
        describe: () => 'Capture screenshot',
    },
    left_click: {
        label: 'Left Click',
        icon:  '🖱️',
        ipc:   'mouse:left-click',
        dispatch: () => leftClick(),
        describe: () => 'Left click',
    },
    right_click: {
        label: 'Right Click',
        icon:  '🖱️',
        ipc:   'mouse:right-click',
        dispatch: () => rightClick(),
        describe: () => 'Right click',
    },
    double_click: {
        label: 'Double Click',
        icon:  '🖱️',
        ipc:   'mouse:double-click',
        dispatch: () => leftClickOpen(),
        describe: () => 'Double click',
    },
    triple_click: {
        label: 'Triple Click',
        icon:  '🖱️',
        ipc:   'mouse:triple-click',
        dispatch: () => tripleClick(),
        describe: () => 'Triple click (select line)',
    },
    mouse_move: {
        label: 'Mouse Move',
        icon:  '↗️',
        ipc:   'mouse:move',
        dispatch: (a) => navigateMouse(a.coordinates.x, a.coordinates.y),
        describe: (a) => `Move cursor to (${a.coordinates.x}, ${a.coordinates.y})`,
    },
    scroll: {
        label: 'Scroll',
        icon:  '📜',
        ipc:   'mouse:scroll',
        dispatch: (a) => scroll(0, 0, a.direction, a.amount || 3),
        describe: (a) => `Scroll ${a.direction} ${a.amount || 3} notches`,
    },
    type_text: {
        label: 'Type Text',
        icon:  '⌨️',
        ipc:   'keyboard:type',
        dispatch: (a) => typeText(a.text),
        describe: (a) => `Type "${a.text}"`,
    },
    key_press: {
        label: 'Key Press',
        icon:  '⌨️',
        ipc:   'keyboard:key-press',
        dispatch: (a) => keyPress(a.key, a.modifiers || []),
        describe: (a) => {
            const mods = (a.modifiers || []).join('+');
            return mods ? `Press ${mods}+${a.key}` : `Press ${a.key}`;
        },
    },
    wait: {
        label: 'Wait',
        icon:  '⏳',
        ipc:   null,
        dispatch: (a) => new Promise(r => setTimeout(r, a.ms || 1000)),
        describe: (a) => `Wait ${a.ms || 1000}ms`,
    },
    shell_exec: {
        label: 'Shell Exec',
        icon:  '💻',
        ipc:   'shell:exec',
        dispatch: (a) => shellExec(a.command),
        describe: (a) => `Run: ${(a.command || '').slice(0, 60)}`,
    },
    done: {
        label: 'Done',
        icon:  '✅',
        ipc:   null,
        dispatch: null,
        describe: () => 'Task complete',
    },
};

/**
 * Race a promise against a timeout.  Rejects with a descriptive error
 * if the promise doesn't settle within `ms` milliseconds.
 */
function withTimeout(promise, ms, label) {
    let timer;
    const timeout = new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms);
    });
    return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

const ACTION_TIMEOUT_MS = 10_000;   // 10 s — generous for IPC + psProcess

/**
 * Execute a backend action object.
 * @param {object} action - The action from AgentResponse (has .type + params)
 * @returns {{ success: boolean, ipc: string|null, description: string }}
 */
async function dispatchAction(action) {
    const entry = ACTION_MAP[action.type];
    if (!entry) {
        console.warn('[actionProxy] unknown action type:', action.type);
        return { success: false, ipc: null, description: `Unknown: ${action.type}` };
    }

    const description = entry.describe(action);

    if (!entry.dispatch) {
        return { success: true, ipc: entry.ipc, description, needsSpecialHandling: true };
    }

    try {
        console.log(`[actionProxy] dispatching ${action.type}...`);
        const result = await withTimeout(
            entry.dispatch(action),
            ACTION_TIMEOUT_MS,
            action.type
        );
        console.log(`[actionProxy] ${action.type} done`, result);
        return {
            success: result?.success !== false,
            ipc: entry.ipc,
            description,
            output: result?.output ?? null,
        };
    } catch (err) {
        console.error(`[actionProxy] ${action.type} failed:`, err);
        return { success: false, ipc: entry.ipc, description, error: err.message };
    }
}

/**
 * Get a human-readable description of an action without executing it.
 */
function describeAction(action) {
    const entry = ACTION_MAP[action.type];
    return entry ? entry.describe(action) : `Unknown action: ${action.type}`;
}

/**
 * Get the display icon for an action type.
 */
function actionIcon(actionType) {
    return ACTION_MAP[actionType]?.icon || '❓';
}

module.exports = { ACTION_MAP, dispatchAction, describeAction, actionIcon };
