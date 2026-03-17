// Action: Right Click
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

async function rightClick(x, y) {
    return await ipcRenderer.invoke('mouse:right-click', { x, y });
}

function register(ipcMain, BACKEND_URL) {
    ipcMain.handle('mouse:right-click', async (_event, { x, y }) => {
        try {
            await psProcess.run(`xdotool click 3`);
            return { success: true, x, y };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { rightClick, register };
