// Action: Keyboard (key_press + type_text)
//
// key_press:  Press a key (with optional modifiers) via keybd_event.
// type_text:  Type a string via SendKeys.
//
// Both use the persistent psProcess to avoid spawn overhead.
const { ipcRenderer } = require('electron');


// ── Virtual-key code lookup ──────────────────────────────────────────────

const VK = {
    // Modifiers
    win: 0x5B, lwin: 0x5B, rwin: 0x5C,
    ctrl: 0x11, control: 0x11,
    alt: 0x12, menu: 0x12,
    shift: 0x10,

    // Navigation
    enter: 0x0D, return: 0x0D,
    tab: 0x09,
    escape: 0x1B, esc: 0x1B,
    space: 0x20,
    backspace: 0x08,
    delete: 0x2E, del: 0x2E,
    insert: 0x2D,

    // Arrow keys
    up: 0x26, down: 0x28, left: 0x25, right: 0x27,

    // Page keys
    home: 0x24, end: 0x23,
    pageup: 0x21, pagedown: 0x22,

    // Function keys
    f1: 0x70, f2: 0x71, f3: 0x72, f4: 0x73,
    f5: 0x74, f6: 0x75, f7: 0x76, f8: 0x77,
    f9: 0x78, f10: 0x79, f11: 0x7A, f12: 0x7B,

    // Misc
    capslock: 0x14, numlock: 0x90, scrolllock: 0x91,
    printscreen: 0x2C, pause: 0x13,
};

function getVK(key) {
    const lower = key.toLowerCase();
    if (VK[lower] !== undefined) return VK[lower];
    // Single character — VK code equals the uppercase char code for A-Z / 0-9
    if (key.length === 1) {
        const code = key.toUpperCase().charCodeAt(0);
        if ((code >= 0x30 && code <= 0x39) || (code >= 0x41 && code <= 0x5A)) return code;
    }
    return null;
}

// ── Renderer-side functions (called from actionProxy) ────────────────────

async function keyPress(key, modifiers = []) {
    return await ipcRenderer.invoke('keyboard:key-press', { key, modifiers });
}

async function typeText(text) {
    return await ipcRenderer.invoke('keyboard:type', { text });
}

// ── Main-process IPC registration ────────────────────────────────────

function register(ipcMain) {
    const psProcess = require('../process/psProcess');

    // ── key_press ────────────────────────────────────────────────────────
    ipcMain.handle('keyboard:key-press', async (_event, { key, modifiers = [] }) => {
        const cmds = [];

        // Press modifiers down
        for (const mod of modifiers) {
            const vk = getVK(mod);
            if (vk == null) return { success: false, error: `Unknown modifier: ${mod}` };
            cmds.push(`[W.U32]::keybd_event(${vk}, 0, 0, 0)`);
        }

        // Press main key down + up
        const mainVk = getVK(key);
        if (mainVk == null) return { success: false, error: `Unknown key: ${key}` };
        cmds.push(`[W.U32]::keybd_event(${mainVk}, 0, 0, 0)`);   // key down
        cmds.push(`Start-Sleep -Milliseconds 30`);
        cmds.push(`[W.U32]::keybd_event(${mainVk}, 0, 2, 0)`);   // key up  (KEYEVENTF_KEYUP = 2)

        // Release modifiers in reverse order
        for (const mod of [...modifiers].reverse()) {
            const vk = getVK(mod);
            cmds.push(`[W.U32]::keybd_event(${vk}, 0, 2, 0)`);
        }

        try {
            await psProcess.run(cmds.join('; '));
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });

    // ── type_text ────────────────────────────────────────────────────────
    ipcMain.handle('keyboard:type', async (_event, { text }) => {
        // For long text (>50 chars), clipboard paste is instant and reliable.
        // SendKeys types character-by-character which times out on long strings.
        const PASTE_THRESHOLD = 50;

        try {
            if (text.length > PASTE_THRESHOLD) {
                // Save current clipboard, paste text, restore clipboard
                const cmds = [
                    `$_prev = Get-Clipboard -ErrorAction SilentlyContinue`,
                    `Set-Clipboard -Value ${psStringLiteral(text)}`,
                    `Start-Sleep -Milliseconds 50`,
                    `[System.Windows.Forms.SendKeys]::SendWait('^v')`,
                    `Start-Sleep -Milliseconds 100`,
                    `if ($_prev) { Set-Clipboard -Value $_prev } else { Set-Clipboard -Value '' }`,
                ];
                await psProcess.run(cmds.join('; '));
            } else {
                // Short text — SendKeys is fine
                const escaped = text.replace(/([+^%~{}[\]()])/g, '{$1}');
                const psStr = escaped.replace(/'/g, "''");
                await psProcess.run(`[System.Windows.Forms.SendKeys]::SendWait('${psStr}')`);
            }
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

/**
 * Safely encode a string as a PowerShell single-quoted literal.
 * Handles embedded single quotes and newlines.
 */
function psStringLiteral(str) {
    // Single quotes inside PS single-quoted strings are doubled
    const escaped = str.replace(/'/g, "''");
    return `'${escaped}'`;
}

module.exports = { keyPress, typeText, register };
