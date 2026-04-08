// Action: Navigate (mouse move)
const { ipcRenderer } = require('electron');

async function navigateMouse(x, y) {
    return await ipcRenderer.invoke('mouse:move', { x, y });
}

function register(ipcMain, BACKEND_URL) {
    const psProcess = require('../process/psProcess');
    ipcMain.handle('mouse:move', async (_event, { x, y }) => {
        console.log(`[navigate] mouse:move invoked x=${x} y=${y}`);
        try {
            const cmd = `[System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point(${x}, ${y})`;
            const result = await psProcess.run(cmd);
            console.log(`[navigate] mouse:move OK x=${x} y=${y} result=${JSON.stringify(result)}`);
            return { success: true, x, y };
        } catch (err) {
            console.error(`[navigate] mouse:move FAILED x=${x} y=${y}:`, err.message);
            return { success: false, error: err.message };
        }
    });
}

module.exports = { navigateMouse, register };

