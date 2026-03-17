// Action: Left Click Open (double-click)
// Both clicks run inside the persistent shell process — no spawn overhead,
// so they reliably land within the double-click time window.
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

async function leftClickOpen(x, y) {
    return await ipcRenderer.invoke('mouse:double-click', { x, y });
}

function register(ipcMain, BACKEND_URL) {
    ipcMain.handle('mouse:double-click', async (_event, { x, y }) => {
        try {
            await psProcess.run(
                `xdotool click --repeat 2 --delay 50 1`
            );
            return { success: true, x, y };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { leftClickOpen, register };

