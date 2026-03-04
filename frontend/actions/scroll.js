// Action: Scroll
// Moves the cursor to (x, y) then fires MOUSEEVENTF_WHEEL via the persistent
// PowerShell process. Works on any scrollable surface.
//
// direction: 'up' | 'down'
// amount:    number of "notches" to scroll (1 notch = WHEEL_DELTA = 120 units)
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

async function scroll(x, y, direction = 'down', amount = 3) {
    return await ipcRenderer.invoke('mouse:scroll', { x, y, direction, amount });
}

function register(ipcMain, BACKEND_URL) {
    ipcMain.handle('mouse:scroll', async (_event, { x, y, direction = 'down', amount = 3 }) => {
        try {
            // WHEEL_DELTA = 120 per notch; positive = up, negative = down
            const delta = direction === 'up' ? 120 * amount : -120 * amount;

            await psProcess.run([
                // Move cursor to the target element first so the OS routes the
                // scroll to the correct window/control
                `[System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point(${x}, ${y})`,
                // MOUSEEVENTF_WHEEL = 0x0800 (2048); dwData = wheel delta
                `[W.U32]::mouse_event(0x0800, 0, 0, ${delta}, 0)`
            ].join('; '));

            return { success: true, x, y, direction, amount };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { scroll, register };
