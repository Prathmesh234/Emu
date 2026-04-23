// Action: Double Click
// Double-click at the CURRENT cursor position (no navigation).
// Uses cliclick on macOS, xdotool on Linux.
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

const isMac = process.platform === 'darwin';

async function doubleClick() {
    return await ipcRenderer.invoke('mouse:double-click-current');
}

function register(ipcMain) {
    ipcMain.handle('mouse:double-click-current', async () => {
        try {
            const cmd = isMac
                ? `cliclick dc:.`   // double-click at current cursor position
                : `xdotool click --repeat 2 --delay 50 1`;
            await psProcess.run(cmd);
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { doubleClick, register };
