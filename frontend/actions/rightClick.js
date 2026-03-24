// Action: Right Click
// Uses cliclick on macOS, xdotool on Linux.
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

const isMac = process.platform === 'darwin';

async function rightClick(x, y) {
    return await ipcRenderer.invoke('mouse:right-click', { x, y });
}

function register(ipcMain, BACKEND_URL) {
    ipcMain.handle('mouse:right-click', async (_event, { x, y }) => {
        try {
            const cmd = isMac
                ? `cliclick rc:.`   // right-click at current cursor position
                : `xdotool click 3`;
            await psProcess.run(cmd);
            return { success: true, x, y };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { rightClick, register };
