// Action: Scroll
// Moves the cursor to (x, y) then fires MOUSEEVENTF_WHEEL via the persistent
// PowerShell process. Works on any scrollable surface.
//
// direction: 'up' | 'down'
// amount:    number of "notches" to scroll (1 notch = WHEEL_DELTA = 120 units)
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

async function scroll(direction = 'down', amount = 3) {
    return await ipcRenderer.invoke('mouse:scroll', { direction, amount });
}

function register(ipcMain, BACKEND_URL) {
    ipcMain.handle('mouse:scroll', async (_event, { direction = 'down', amount = 3 }) => {
        try {
            // WHEEL_DELTA = 120 per notch; positive = up, negative = down
            const delta = direction === 'up' ? 120 * amount : -120 * amount;

            // 1. Fire a zero-pixel MOUSEEVENTF_MOVE so the target window
            //    receives WM_MOUSEMOVE and registers the cursor hovering.
            // 2. Brief sleep to let the app process the move.
            // 3. Fire MOUSEEVENTF_WHEEL at the current cursor position.
            await psProcess.run([
                `[W.U32]::mouse_event(0x0001, 0, 0, 0, 0)`,
                `Start-Sleep -Milliseconds 100`,
                `[W.U32]::mouse_event(0x0800, 0, 0, ${delta}, 0)`,
            ].join('; '));

            return { success: true, direction, amount };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { scroll, register };
