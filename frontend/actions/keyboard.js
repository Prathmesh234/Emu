// Action: Keyboard (key_press + type_text)
//
// key_press:  Press a key (with optional modifiers) via xdotool key.
// type_text:  Type a string via xdotool type.
//
// Both use the persistent shell process to avoid spawn overhead.

const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

const isMac = process.platform === 'darwin';

// ── xdotool key name lookup ──────────────────────────────────────────────
// Maps common key names to xdotool-compatible key names.

const KEY_MAP = {
    // Modifiers
    win: 'super', lwin: 'super', rwin: 'super',
    ctrl: 'ctrl', control: 'ctrl',
    alt: 'alt', menu: 'alt',
    shift: 'shift',
    cmd: 'super', command: 'super', meta: 'super',

    // Navigation
    enter: 'Return', return: 'Return',
    tab: 'Tab',
    escape: 'Escape', esc: 'Escape',
    space: 'space',
    backspace: 'BackSpace',
    delete: 'Delete', del: 'Delete',
    insert: 'Insert',

    // Arrow keys
    up: 'Up', down: 'Down', left: 'Left', right: 'Right',

    // Page keys
    home: 'Home', end: 'End',
    pageup: 'Prior', pagedown: 'Next',

    // Function keys
    f1: 'F1', f2: 'F2', f3: 'F3', f4: 'F4',
    f5: 'F5', f6: 'F6', f7: 'F7', f8: 'F8',
    f9: 'F9', f10: 'F10', f11: 'F11', f12: 'F12',

    // Misc
    capslock: 'Caps_Lock', numlock: 'Num_Lock', scrolllock: 'Scroll_Lock',
    printscreen: 'Print', pause: 'Pause',
};

function getXdotoolKey(key) {
    const lower = key.toLowerCase();
    if (KEY_MAP[lower] !== undefined) return KEY_MAP[lower];
    // Single character — xdotool accepts lowercase letters and digits directly
    if (key.length === 1) return key.toLowerCase();
    return null;
}

// ── Renderer-side functions (called from actionProxy) ────────────────────

async function keyPress(key, modifiers = []) {
    return await ipcRenderer.invoke('keyboard:key-press', { key, modifiers });
}

async function typeText(text) {
    return await ipcRenderer.invoke('keyboard:type', { text });
}

// ── Main-process IPC registration ────────────────────────────────────────

function register(ipcMain) {

    // ── key_press ────────────────────────────────────────────────────────
    ipcMain.handle('keyboard:key-press', async (_event, { key, modifiers = [] }) => {
        // Build xdotool key combo string: "ctrl+shift+a"
        const parts = [];

        for (const mod of modifiers) {
            const mapped = getXdotoolKey(mod);
            if (mapped == null) return { success: false, error: `Unknown modifier: ${mod}` };
            parts.push(mapped);
        }

        const mainKey = getXdotoolKey(key);
        if (mainKey == null) return { success: false, error: `Unknown key: ${key}` };
        parts.push(mainKey);

        const combo = parts.join('+');

        try {
            await psProcess.run(`xdotool key --clearmodifiers ${combo}`);
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });

    // ── type_text ────────────────────────────────────────────────────────
    ipcMain.handle('keyboard:type', async (_event, { text }) => {
        // For long text (>50 chars), clipboard paste is instant and reliable.
        // xdotool type types character-by-character which is slow on long strings.
        const PASTE_THRESHOLD = 50;

        try {
            if (text.length > PASTE_THRESHOLD) {
                // Save current clipboard, paste text, restore clipboard
                if (isMac) {
                    const cmds = [
                        `_prev=$(pbpaste 2>/dev/null || true)`,
                        `echo -n ${shellEscape(text)} | pbcopy`,
                        `sleep 0.05`,
                        `xdotool key --clearmodifiers super+v`,
                        `sleep 0.1`,
                        `echo -n "$_prev" | pbcopy`,
                    ];
                    await psProcess.run(cmds.join('; '));
                } else {
                    const cmds = [
                        `_prev=$(xclip -selection clipboard -o 2>/dev/null || true)`,
                        `echo -n ${shellEscape(text)} | xclip -selection clipboard`,
                        `sleep 0.05`,
                        `xdotool key --clearmodifiers ctrl+v`,
                        `sleep 0.1`,
                        `echo -n "$_prev" | xclip -selection clipboard`,
                    ];
                    await psProcess.run(cmds.join('; '));
                }
            } else {
                // Short text — xdotool type is fine
                await psProcess.run(`xdotool type --clearmodifiers -- ${shellEscape(text)}`);
            }
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

/**
 * Safely escape a string for use in a bash single-quoted context.
 * Handles embedded single quotes.
 */
function shellEscape(str) {
    // Wrap in single quotes, escape any embedded single quotes
    return "'" + str.replace(/'/g, "'\\''") + "'";
}

module.exports = { keyPress, typeText, register };
