// Action: Right Click
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

async function rightClick(x, y) {
    return await ipcRenderer.invoke('mouse:right-click', { x, y });
}

function register(ipcMain, BACKEND_URL) {
    ipcMain.handle('mouse:right-click', async (_event, { x, y }) => {
        try {
            await psProcess.run(
                `[W.U32]::mouse_event(8,0,0,0,0); Start-Sleep -Milliseconds 30; [W.U32]::mouse_event(16,0,0,0,0)`
            );
            return { success: true, x, y };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { rightClick, register };

