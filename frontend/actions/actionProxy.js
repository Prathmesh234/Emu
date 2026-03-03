// frontend/actions/actionProxy.js
//
// Maps backend ActionType → frontend IPC channel + params.
// Single source of truth for dispatching model actions.

const { leftClick }      = require('./leftClick');
const { rightClick }     = require('./rightClick');
const { leftClickOpen }  = require('./leftClickOpen');
const { navigateMouse }  = require('./navigate');
const { scroll }         = require('./scroll');
const { captureScreenshot } = require('./screenshot');

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
        dispatch: (a) => leftClick(a.coordinates.x, a.coordinates.y),
        describe: (a) => `Click at (${a.coordinates.x}, ${a.coordinates.y})`,
    },
    right_click: {
        label: 'Right Click',
        icon:  '🖱️',
        ipc:   'mouse:right-click',
        dispatch: (a) => rightClick(a.coordinates.x, a.coordinates.y),
        describe: (a) => `Right-click at (${a.coordinates.x}, ${a.coordinates.y})`,
    },
    double_click: {
        label: 'Double Click',
        icon:  '🖱️',
        ipc:   'mouse:double-click',
        dispatch: (a) => leftClickOpen(a.coordinates.x, a.coordinates.y),
        describe: (a) => `Double-click at (${a.coordinates.x}, ${a.coordinates.y})`,
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
        dispatch: (a) => scroll(a.coordinates.x, a.coordinates.y, a.direction, a.amount || 3),
        describe: (a) => `Scroll ${a.direction} ${a.amount || 3} notches at (${a.coordinates.x}, ${a.coordinates.y})`,
    },
    type_text: {
        label: 'Type Text',
        icon:  '⌨️',
        ipc:   'keyboard:type',
        dispatch: null,  // handled specially in app.js (needs psProcess)
        describe: (a) => `Type "${a.text}"`,
    },
    key_press: {
        label: 'Key Press',
        icon:  '⌨️',
        ipc:   'keyboard:key-press',
        dispatch: null,  // handled specially in app.js
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
    done: {
        label: 'Done',
        icon:  '✅',
        ipc:   null,
        dispatch: null,
        describe: () => 'Task complete',
    },
};

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
        // type_text, key_press, done — caller handles these
        return { success: true, ipc: entry.ipc, description, needsSpecialHandling: true };
    }

    try {
        const result = await entry.dispatch(action);
        return { success: result?.success !== false, ipc: entry.ipc, description };
    } catch (err) {
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
