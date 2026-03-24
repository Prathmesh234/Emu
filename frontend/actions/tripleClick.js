// Action: Triple Click (select entire line/paragraph)
// Uses cliclick on macOS, xdotool on Linux.
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

const isMac = process.platform === 'darwin';

async function tripleClick() {
    return await ipcRenderer.invoke('mouse:triple-click');
}

function register(ipcMain) {
    ipcMain.handle('mouse:triple-click', async () => {
        try {
            const cmd = isMac
                ? `cliclick tc:.`   // triple-click at current cursor position
                : `xdotool click --repeat 3 --delay 30 1`;
            await psProcess.run(cmd);
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { tripleClick, register };
