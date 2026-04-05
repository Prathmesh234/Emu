// Action: Left Click
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

async function leftClick(x, y) {
    return await ipcRenderer.invoke('mouse:left-click', { x, y });
}

function register(ipcMain, BACKEND_URL) {
    ipcMain.handle('mouse:left-click', async (_event, { x, y }) => {
        try {
            await psProcess.run(
                `[W.U32]::mouse_event(2,0,0,0,0); [W.U32]::mouse_event(4,0,0,0,0)`
            );
            return { success: true, x, y };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { leftClick, register };

