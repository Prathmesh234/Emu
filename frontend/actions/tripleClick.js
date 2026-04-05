// Action: Triple Click (select entire line/paragraph)
// Three rapid mouse_event pairs inside the persistent psProcess.
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

async function tripleClick() {
    return await ipcRenderer.invoke('mouse:triple-click');
}

function register(ipcMain) {
    ipcMain.handle('mouse:triple-click', async () => {
        try {
            await psProcess.run(
                `[W.U32]::mouse_event(2,0,0,0,0); [W.U32]::mouse_event(4,0,0,0,0); Start-Sleep -Milliseconds 30; [W.U32]::mouse_event(2,0,0,0,0); [W.U32]::mouse_event(4,0,0,0,0); Start-Sleep -Milliseconds 30; [W.U32]::mouse_event(2,0,0,0,0); [W.U32]::mouse_event(4,0,0,0,0)`
            );
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { tripleClick, register };
