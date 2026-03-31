// Action: Keyboard (key_press + type_text)
//
// macOS: cliclick kp: for key presses, t: for typing text.
//        For modifier combos, uses osascript with System Events.
// Linux: xdotool key / xdotool type.

const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

const isMac = process.platform === 'darwin';

// ── cliclick kp: key name lookup (macOS, no modifiers) ──────────────────
// Maps agent key names → cliclick kp: key names (string-based).
// Only special/navigation keys are here — letters, numbers, and symbols
// are typed via `cliclick t:` instead.
// Reference: cliclick -h (kp: command section)

const CLICLICK_KEY_MAP = {
    enter: 'return', return: 'return',   // cliclick kp:enter = numpad Enter (rare on Macs); always use 'return'
    tab: 'tab',
    space: 'space',
    escape: 'esc', esc: 'esc',
    backspace: 'delete', delete: 'delete',   // "delete" = backspace in cliclick
    forwarddelete: 'fwd-delete',
    up: 'arrow-up', down: 'arrow-down', left: 'arrow-left', right: 'arrow-right',
    home: 'home', end: 'end',
    pageup: 'page-up', pagedown: 'page-down',
    f1: 'f1', f2: 'f2', f3: 'f3', f4: 'f4',
    f5: 'f5', f6: 'f6', f7: 'f7', f8: 'f8',
    f9: 'f9', f10: 'f10', f11: 'f11', f12: 'f12',
    f13: 'f13', f14: 'f14', f15: 'f15', f16: 'f16',
    mute: 'mute', volumeup: 'volume-up', volumedown: 'volume-down',
};

// ── osascript key code lookup (macOS, modifier combos) ──────────────────
// Maps key names → macOS virtual key codes for osascript System Events.
// Used ONLY when modifiers are present (cmd+c, ctrl+shift+a, etc.)
// Reference: https://eastmanreference.com/complete-list-of-applescript-key-codes

const MAC_KEY_CODES = {
    enter: 36, return: 36,
    tab: 48,
    space: 49,
    escape: 53, esc: 53,
    backspace: 51, delete: 51,
    forwarddelete: 117,
    up: 126, down: 125, left: 123, right: 124,
    home: 115, end: 119,
    pageup: 116, pagedown: 121,
    f1: 122, f2: 120, f3: 99, f4: 118,
    f5: 96, f6: 97, f7: 98, f8: 100,
    f9: 101, f10: 109, f11: 103, f12: 111,
    capslock: 57,
    // Letters
    a: 0, b: 11, c: 8, d: 2, e: 14, f: 3, g: 5, h: 4,
    i: 34, j: 38, k: 40, l: 37, m: 46, n: 45, o: 31, p: 35,
    q: 12, r: 15, s: 1, t: 17, u: 32, v: 9, w: 13, x: 7,
    y: 16, z: 6,
    // Numbers
    0: 29, 1: 18, 2: 19, 3: 20, 4: 21,
    5: 23, 6: 22, 7: 26, 8: 28, 9: 25,
    // Symbols
    '-': 27, '=': 24, '[': 33, ']': 30,
    '\\': 42, ';': 41, "'": 39, ',': 43,
    '.': 47, '/': 44, '`': 50,
};

// Maps modifier names to osascript modifier syntax
const MAC_MODIFIER_MAP = {
    cmd: 'command down', command: 'command down', meta: 'command down',
    ctrl: 'control down', control: 'control down',
    alt: 'option down', option: 'option down',
    shift: 'shift down',
    fn: 'fn down',
};

// ── xdotool key name lookup (Linux) ──────────────────────────────────
const XDOTOOL_KEY_MAP = {
    win: 'super', cmd: 'super', command: 'super', meta: 'super',
    ctrl: 'ctrl', control: 'ctrl',
    alt: 'alt', menu: 'alt',
    shift: 'shift',
    enter: 'Return', return: 'Return',
    tab: 'Tab',
    escape: 'Escape', esc: 'Escape',
    space: 'space',
    backspace: 'BackSpace',
    delete: 'Delete', del: 'Delete',
    insert: 'Insert',
    up: 'Up', down: 'Down', left: 'Left', right: 'Right',
    home: 'Home', end: 'End',
    pageup: 'Prior', pagedown: 'Next',
    f1: 'F1', f2: 'F2', f3: 'F3', f4: 'F4',
    f5: 'F5', f6: 'F6', f7: 'F7', f8: 'F8',
    f9: 'F9', f10: 'F10', f11: 'F11', f12: 'F12',
};

// ── Renderer-side functions (called from actionProxy) ────────────────

async function keyPress(key, modifiers = []) {
    return await ipcRenderer.invoke('keyboard:key-press', { key, modifiers });
}

async function typeText(text) {
    return await ipcRenderer.invoke('keyboard:type', { text });
}

// ── Main-process IPC registration ────────────────────────────────────

function register(ipcMain) {

    // ── key_press ────────────────────────────────────────────────────
    ipcMain.handle('keyboard:key-press', async (_event, { key, modifiers = [] }) => {
        try {
            if (isMac) {
                return await _macKeyPress(key, modifiers);
            } else {
                return await _linuxKeyPress(key, modifiers);
            }
        } catch (err) {
            return { success: false, error: err.message };
        }
    });

    // ── type_text ────────────────────────────────────────────────────
    ipcMain.handle('keyboard:type', async (_event, { text }) => {
        try {
            if (isMac) {
                return await _macTypeText(text);
            } else {
                return await _linuxTypeText(text);
            }
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

// ── macOS implementations ────────────────────────────────────────────

async function _macKeyPress(key, modifiers = []) {
    const lower = key.toLowerCase();

    if (modifiers.length === 0) {
        // No modifiers — use cliclick
        const cliclickKey = CLICLICK_KEY_MAP[lower];
        if (cliclickKey) {
            // Special key (enter, tab, arrows, etc.) — use kp:
            await psProcess.run(`cliclick kp:${cliclickKey}`);
        } else if (key.length === 1) {
            // Single character (letter, number, symbol) — use t: to type it
            const escaped = key === "'" ? "\\'" : key;
            await psProcess.run(`cliclick t:'${escaped}'`);
        } else {
            return { success: false, error: `Unknown key: ${key}` };
        }
    } else {
        // Key press with modifiers — use osascript with System Events (needs numeric key codes)
        const keyCode = MAC_KEY_CODES[lower];
        if (keyCode === undefined) {
            return { success: false, error: `Unknown key for modifier combo: ${key}` };
        }

        const modList = [];
        for (const mod of modifiers) {
            const mapped = MAC_MODIFIER_MAP[mod.toLowerCase()];
            if (!mapped) return { success: false, error: `Unknown modifier: ${mod}` };
            modList.push(mapped);
        }
        const modString = `{${modList.join(', ')}}`;
        const script = `tell application "System Events" to key code ${keyCode} using ${modString}`;
        await psProcess.run(`osascript -e '${script}'`);
    }

    return { success: true };
}

async function _macTypeText(text) {
    // For short text, use cliclick t: (type text)
    // For long text, use clipboard paste via Cmd+V (much faster)
    const PASTE_THRESHOLD = 50;

    if (text.length > PASTE_THRESHOLD) {
        const cmds = [
            `_prev=$(pbpaste 2>/dev/null || true)`,
            `printf '%s' ${shellEscape(text)} | pbcopy`,
            `sleep 0.05`,
            // Cmd+V paste via cliclick: hold cmd, type v, release cmd
            `cliclick kd:cmd t:v ku:cmd`,
            `sleep 0.1`,
            `printf '%s' "$_prev" | pbcopy`,
        ];
        await psProcess.run(cmds.join('; '));
    } else {
        // cliclick t: types the given text into the frontmost app
        // Text with spaces must be single-quoted
        await psProcess.run(`cliclick t:${shellEscape(text)}`);
    }

    return { success: true };
}

// ── Linux implementations ────────────────────────────────────────────

async function _linuxKeyPress(key, modifiers = []) {
    const parts = [];

    for (const mod of modifiers) {
        const mapped = XDOTOOL_KEY_MAP[mod.toLowerCase()];
        if (!mapped) return { success: false, error: `Unknown modifier: ${mod}` };
        parts.push(mapped);
    }

    const mainKey = XDOTOOL_KEY_MAP[key.toLowerCase()] || (key.length === 1 ? key.toLowerCase() : null);
    if (!mainKey) return { success: false, error: `Unknown key: ${key}` };
    parts.push(mainKey);

    await psProcess.run(`xdotool key --clearmodifiers ${parts.join('+')}`);
    return { success: true };
}

async function _linuxTypeText(text) {
    const PASTE_THRESHOLD = 50;

    if (text.length > PASTE_THRESHOLD) {
        const cmds = [
            `_prev=$(xclip -selection clipboard -o 2>/dev/null || true)`,
            `printf '%s' ${shellEscape(text)} | xclip -selection clipboard`,
            `sleep 0.05`,
            `xdotool key --clearmodifiers ctrl+v`,
            `sleep 0.1`,
            `printf '%s' "$_prev" | xclip -selection clipboard`,
        ];
        await psProcess.run(cmds.join('; '));
    } else {
        await psProcess.run(`xdotool type --clearmodifiers -- ${shellEscape(text)}`);
    }

    return { success: true };
}

// ── Utility ──────────────────────────────────────────────────────────

function shellEscape(str) {
    return "'" + str.replace(/'/g, "'\\''") + "'";
}

module.exports = { keyPress, typeText, register };
