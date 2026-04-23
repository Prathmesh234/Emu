// Action: Relative Mouse Move
// Moves the cursor by an offset from its current position.
//
// macOS: cliclick supports relative coordinates with explicit + / − sign,
//        e.g.  cliclick m:+10,-5
// Linux: xdotool mousemove_relative -- 10 -5
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

const isMac = process.platform === 'darwin';

async function relativeMove(dxPx, dyPx) {
    return await ipcRenderer.invoke('mouse:relative-move', { dxPx, dyPx });
}

// cliclick requires an explicit sign before relative offsets.
function _signed(n) {
    const v = Math.round(n);
    return v >= 0 ? `+${v}` : `${v}`;     // negative numbers already include "−"
}

function register(ipcMain) {
    ipcMain.handle('mouse:relative-move', async (_event, { dxPx, dyPx }) => {
        try {
            if (isMac) {
                const cmd = `cliclick m:${_signed(dxPx)},${_signed(dyPx)}`;
                console.log(`[relative_mouse_move] ${cmd}`);
                await psProcess.run(cmd);
            } else {
                await psProcess.run(`xdotool mousemove_relative -- ${Math.round(dxPx)} ${Math.round(dyPx)}`);
            }
            return { success: true, dxPx, dyPx };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { relativeMove, register };
