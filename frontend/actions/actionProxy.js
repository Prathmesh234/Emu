// frontend/actions/actionProxy.js
//
// Maps backend ActionType → frontend IPC channel + params.
// Single source of truth for dispatching model actions.
//
// Supports both regular mode and coworker mode (skylight/cua):
// - Reads EMU_COWORKER_MODE environment variable
// - Routes interactive actions to coworker backend if enabled
// - Falls back to regular dispatch on error or when mode is disabled

const { leftClick }      = require('./leftClick');
const { rightClick }     = require('./rightClick');
const { leftClickOpen }  = require('./leftClickOpen');
const { tripleClick }    = require('./tripleClick');
const { navigateMouse }  = require('./navigate');
const { drag }           = require('./drag');
const { scroll }         = require('./scroll');
const { captureScreenshot, getScaleFactors, getScreenDimensions } = require('./screenshot');
const { keyPress, typeText } = require('./keyboard');
const { shellExec }      = require('./exec');
const { ipcRenderer }    = require('electron');

// ─── Coworker mode initialization ────────────────────────────────────────
let coworkerMode = null;
let coworkerModule = null;
let lastCoworkerPid = null;
let lastCoworkerPidTime = 0;
const PID_CACHE_DURATION_MS = 2000;

function getCoworkerMode() {
    if (coworkerMode !== null) return coworkerMode;
    
    const modeStr = process.env.EMU_COWORKER_MODE || '';
    if (modeStr.toLowerCase() === 'skylight') {
        coworkerMode = 'skylight';
    } else if (modeStr.toLowerCase() === 'cua') {
        coworkerMode = 'cua';
    } else {
        coworkerMode = null;
    }
    
    if (coworkerMode) {
        console.log(`[actionProxy] coworker mode enabled: ${coworkerMode}`);
        loadCoworkerModule();
    }
    
    return coworkerMode;
}

function loadCoworkerModule() {
    if (!coworkerMode) return null;
    if (coworkerModule) return coworkerModule;
    
    try {
        if (coworkerMode === 'skylight') {
            coworkerModule = require('../actions-coworker/skylight');
        } else if (coworkerMode === 'cua') {
            coworkerModule = require('../actions-coworker/cua-shell');
        }
        
        if (coworkerModule && coworkerModule.events) {
            console.log(`[actionProxy] loaded coworker module: ${coworkerMode}`);
            return coworkerModule;
        } else {
            console.warn(`[actionProxy] coworker module missing events exports`);
            coworkerModule = null;
            return null;
        }
    } catch (err) {
        console.error(`[actionProxy] failed to load coworker module (${coworkerMode}):`, err.message);
        coworkerModule = null;
        return null;
    }
}

async function getTargetPIDForCoordinates(x, y) {
    const now = Date.now();
    if (lastCoworkerPid && (now - lastCoworkerPidTime) < PID_CACHE_DURATION_MS) {
        return lastCoworkerPid;
    }
    
    try {
        if (ipcRenderer && typeof ipcRenderer.invoke === 'function') {
            const pid = await ipcRenderer.invoke('coworker:get-pid-at-coordinates', { x, y });
            if (pid) {
                lastCoworkerPid = pid;
                lastCoworkerPidTime = now;
                return pid;
            }
        }
    } catch (err) {
        console.debug(`[actionProxy] failed to get PID for (${x}, ${y}):`, err.message);
    }
    
    try {
        const focusedWindow = require('electron').BrowserWindow.getFocusedWindow?.();
        if (focusedWindow && focusedWindow.webContents.getOSProcessId) {
            const pid = focusedWindow.webContents.getOSProcessId();
            if (pid) {
                lastCoworkerPid = pid;
                lastCoworkerPidTime = now;
                return pid;
            }
        }
    } catch (err) {
        console.debug(`[actionProxy] failed to get focused window PID:`, err.message);
    }
    
    return null;
}

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
        coworkerDispatch: async (action, module, pid) => {
            if (!pid) throw new Error('No target PID for coworker click');
            return await module.events.dispatchClick(action.coordinates.x, action.coordinates.y, pid);
        },
        describe: () => 'Left click',
    },
    right_click: {
        label: 'Right Click',
        icon:  '🖱️',
        ipc:   'mouse:right-click',
        dispatch: () => rightClick(),
        coworkerDispatch: async (action, module, pid) => {
            if (!pid) throw new Error('No target PID for coworker right-click');
            return await module.events.dispatchRightClick(action.coordinates.x, action.coordinates.y, pid);
        },
        describe: () => 'Right click',
    },
    double_click: {
        label: 'Double Click',
        icon:  '🖱️',
        ipc:   'mouse:double-click',
        dispatch: () => leftClickOpen(),
        coworkerDispatch: async (action, module, pid) => {
            if (!pid) throw new Error('No target PID for coworker double-click');
            return await module.events.dispatchDoubleClick(action.coordinates.x, action.coordinates.y, pid);
        },
        describe: () => 'Double click',
    },
    triple_click: {
        label: 'Triple Click',
        icon:  '🖱️',
        ipc:   'mouse:triple-click',
        dispatch: () => tripleClick(),
        coworkerDispatch: async (action, module, pid) => {
            if (!pid) throw new Error('No target PID for coworker triple-click');
            return await module.events.dispatchTripleClick(action.coordinates.x, action.coordinates.y, pid);
        },
        describe: () => 'Triple click (select line)',
    },
    mouse_move: {
        label: 'Mouse Move',
        icon:  '↗️',
        ipc:   'mouse:move',
        dispatch: (a) => {
            const { screenWidth, screenHeight } = getScreenDimensions();
            const absX = Math.round(a.coordinates.x * screenWidth);
            const absY = Math.round(a.coordinates.y * screenHeight);
            console.log(`[mouse_move] denorm (${a.coordinates.x}, ${a.coordinates.y}) → (${absX}, ${absY}) [screen: ${screenWidth}x${screenHeight}]`);
            return navigateMouse(absX, absY);
        },
        coworkerDispatch: async (action, module, pid) => {
            if (!pid) throw new Error('No target PID for coworker mouse-move');
            return await module.events.dispatchMouseMove(action.coordinates.x, action.coordinates.y, pid);
        },
        describe: (a) => `Move cursor to (${a.coordinates.x}, ${a.coordinates.y})`,
    },
    drag: {
        label: 'Drag',
        icon:  '↔️',
        ipc:   'mouse:drag',
        dispatch: (a) => {
            const { screenWidth, screenHeight } = getScreenDimensions();
            const startX = Math.round(a.coordinates.x * screenWidth);
            const startY = Math.round(a.coordinates.y * screenHeight);
            const endX = Math.round(a.end_coordinates.x * screenWidth);
            const endY = Math.round(a.end_coordinates.y * screenHeight);
            console.log(`[drag] denorm (${a.coordinates.x},${a.coordinates.y}) → (${startX},${startY}) to (${a.end_coordinates.x},${a.end_coordinates.y}) → (${endX},${endY}) [screen: ${screenWidth}x${screenHeight}]`);
            return drag(startX, startY, endX, endY);
        },
        coworkerDispatch: async (action, module, pid) => {
            if (!pid) throw new Error('No target PID for coworker drag');
            await module.events.dispatchMouseMove(action.coordinates.x, action.coordinates.y, pid);
            return await module.events.dispatchMouseMove(action.end_coordinates.x, action.end_coordinates.y, pid);
        },
        describe: (a) => `Drag from (${a.coordinates.x}, ${a.coordinates.y}) to (${a.end_coordinates.x}, ${a.end_coordinates.y})`,
    },
    scroll: {
        label: 'Scroll',
        icon:  '📜',
        ipc:   'mouse:scroll',
        dispatch: (a) => scroll(a.direction, a.amount || 5),
        coworkerDispatch: async (action, module, pid) => {
            if (!pid) throw new Error('No target PID for coworker scroll');
            return await module.events.dispatchScroll(action.direction, action.amount || 5, pid);
        },
        describe: (a) => `Scroll ${a.direction} ${a.amount || 5} notches`,
    },
    type_text: {
        label: 'Type Text',
        icon:  '⌨️',
        ipc:   'keyboard:type',
        dispatch: (a) => typeText(a.text),
        coworkerDispatch: async (action, module, pid) => {
            if (!pid) throw new Error('No target PID for coworker type-text');
            return await module.events.dispatchTypeText(action.text, pid);
        },
        describe: (a) => `Type "${a.text}"`,
    },
    key_press: {
        label: 'Key Press',
        icon:  '⌨️',
        ipc:   'keyboard:key-press',
        dispatch: (a) => keyPress(a.key, a.modifiers || []),
        coworkerDispatch: async (action, module, pid) => {
            if (!pid) throw new Error('No target PID for coworker key-press');
            return await module.events.dispatchKeyboard(action.key, action.modifiers || [], pid);
        },
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
    memory_read: {
        label: 'Memory Read',
        icon:  '📖',
        ipc:   'memory:read',
        dispatch: (a) => ipcRenderer.invoke('memory:read', { path: a.path }),
        describe: (a) => `Read: ${a.path || '(no path)'}`,
    },
    done: {
        label: 'Done',
        icon:  '✅',
        ipc:   null,
        dispatch: null,
        describe: () => 'Task complete',
    },
};

function withTimeout(promise, ms, label) {
    let timer;
    const timeout = new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms);
    });
    return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

const ACTION_TIMEOUT_MS = 15_000;

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

    const mode = getCoworkerMode();
    const shouldUseCoworker = mode && entry.coworkerDispatch && action.coordinates && !['screenshot', 'done', 'shell_exec', 'memory_read', 'wait'].includes(action.type);

    let dispatcher = entry.dispatch;
    let routeInfo = 'regular';

    if (shouldUseCoworker && coworkerModule) {
        try {
            const pid = await getTargetPIDForCoordinates(action.coordinates.x, action.coordinates.y);
            if (pid) {
                console.log(`[actionProxy:coworker] routing ${action.type} to ${mode} backend (pid=${pid})`);
                dispatcher = async () => entry.coworkerDispatch(action, coworkerModule, pid);
                routeInfo = `coworker/${mode}`;
            } else {
                console.warn(`[actionProxy] coworker enabled but no PID found, falling back to regular dispatch`);
            }
        } catch (pidErr) {
            console.warn(`[actionProxy] failed to get target PID, falling back to regular dispatch:`, pidErr.message);
        }
    }

    try {
        console.log(`[actionProxy] dispatching ${action.type} via ${routeInfo}...`);
        const result = await withTimeout(dispatcher(action), ACTION_TIMEOUT_MS, action.type);
        console.log(`[actionProxy] ${action.type} (${routeInfo}) done`, result);
        return { success: result?.success !== false, ipc: entry.ipc, description, output: result?.output ?? null, route: routeInfo };
    } catch (err) {
        const errorMsg = err.message;
        console.error(`[actionProxy] ${action.type} (${routeInfo}) failed:`, errorMsg);
        
        if (shouldUseCoworker && routeInfo.startsWith('coworker/')) {
            console.warn(`[actionProxy] coworker dispatch failed, attempting fallback to regular dispatch`);
            try {
                const fallbackResult = await withTimeout(entry.dispatch(action), ACTION_TIMEOUT_MS, `${action.type}-fallback`);
                console.log(`[actionProxy] ${action.type} fallback succeeded`);
                return { success: fallbackResult?.success !== false, ipc: entry.ipc, description, output: fallbackResult?.output ?? null, route: 'fallback' };
            } catch (fallbackErr) {
                console.error(`[actionProxy] fallback also failed:`, fallbackErr.message);
                return { success: false, ipc: entry.ipc, description, error: `${mode} backend: ${errorMsg}; fallback: ${fallbackErr.message}`, route: routeInfo };
            }
        }
        
        return { success: false, ipc: entry.ipc, description, error: errorMsg, route: routeInfo };
    }
}

function describeAction(action) {
    const entry = ACTION_MAP[action.type];
    return entry ? entry.describe(action) : `Unknown action: ${action.type}`;
}

function actionIcon(actionType) {
    return ACTION_MAP[actionType]?.icon || '❓';
}

const initialMode = getCoworkerMode();
if (initialMode) {
    console.log(`[actionProxy] initialized with coworker mode: ${initialMode}`);
} else {
    console.log(`[actionProxy] running in regular mode (no EMU_COWORKER_MODE set)`);
}

module.exports = { ACTION_MAP, dispatchAction, describeAction, actionIcon, getCoworkerMode };
