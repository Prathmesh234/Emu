// Action: Navigate (mouse move)
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

async function navigateMouse(x, y) {
    return await ipcRenderer.invoke('mouse:move', { x, y });
}

function register(ipcMain, BACKEND_URL) {
    ipcMain.handle('mouse:move', async (_event, { x, y }) => {
        try {
            await psProcess.run(
                `[System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point(${x}, ${y})`
            );
            fetch(`${BACKEND_URL}/move/x=${x},y=${y}`, { method: 'POST' }).catch(() => {});
            return { success: true, x, y };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { navigateMouse, register };

