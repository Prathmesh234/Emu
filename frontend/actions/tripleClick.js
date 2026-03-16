// Action: Triple Click (select entire line/paragraph)
// Three rapid mouse clicks inside the persistent shell process.
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

async function tripleClick() {
    return await ipcRenderer.invoke('mouse:triple-click');
}

function register(ipcMain) {
    ipcMain.handle('mouse:triple-click', async () => {
        try {
            await psProcess.run(
                `xdotool click --repeat 3 --delay 30 1`
            );
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { tripleClick, register };
