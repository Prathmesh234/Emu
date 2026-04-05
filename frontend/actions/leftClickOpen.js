// Action: Left Click Open (double-click)
// Both clicks run inside the persistent psProcess — no spawn overhead,
// so they reliably land within Windows' double-click time window.
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

async function leftClickOpen(x, y) {
    return await ipcRenderer.invoke('mouse:double-click', { x, y });
}

function register(ipcMain, BACKEND_URL) {
    ipcMain.handle('mouse:double-click', async (_event, { x, y }) => {
        try {
            await psProcess.run(
                `[W.U32]::mouse_event(2,0,0,0,0); [W.U32]::mouse_event(4,0,0,0,0); Start-Sleep -Milliseconds 50; [W.U32]::mouse_event(2,0,0,0,0); [W.U32]::mouse_event(4,0,0,0,0)`
            );
            return { success: true, x, y };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { leftClickOpen, register };


