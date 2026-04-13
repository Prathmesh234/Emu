// Action: Navigate (mouse move)
// Uses cliclick on macOS, xdotool on Linux.
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

const isMac = process.platform === 'darwin';

async function navigateMouse(x, y) {
    return await ipcRenderer.invoke('mouse:move', { x, y });
}

function register(ipcMain, BACKEND_URL) {
    ipcMain.handle('mouse:move', async (_event, { x, y }) => {
        console.log(`[navigate] mouse:move invoked x=${x} y=${y}`);
        try {
            const cmd = isMac
                ? `cliclick m:${x},${y}`
                : `xdotool mousemove ${x} ${y}`;
            await psProcess.run(cmd);
            console.log(`[navigate] mouse:move OK x=${x} y=${y}`);
            return { success: true, x, y };
        } catch (err) {
            console.error(`[navigate] mouse:move FAILED x=${x} y=${y}:`, err.message);
            return { success: false, error: err.message };
        }
    });
}

module.exports = { navigateMouse, register };
