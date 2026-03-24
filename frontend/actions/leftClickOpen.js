// Action: Left Click Open (double-click)
// Uses cliclick on macOS, xdotool on Linux.
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

const isMac = process.platform === 'darwin';

async function leftClickOpen(x, y) {
    return await ipcRenderer.invoke('mouse:double-click', { x, y });
}

function register(ipcMain, BACKEND_URL) {
    ipcMain.handle('mouse:double-click', async (_event, { x, y }) => {
        try {
            const cmd = isMac
                ? `cliclick dc:.`   // double-click at current cursor position
                : `xdotool click --repeat 2 --delay 50 1`;
            await psProcess.run(cmd);
            return { success: true, x, y };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { leftClickOpen, register };
