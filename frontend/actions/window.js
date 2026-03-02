// Action: Window management
const { ipcRenderer } = require('electron');

async function moveToSidePanel() {
    return await ipcRenderer.invoke('window:side-panel');
}

async function moveToCentered() {
    return await ipcRenderer.invoke('window:centered');
}

async function blurWindow() {
    return await ipcRenderer.invoke('window:blur');
}

function register(ipcMain, getMainWindow) {
    let originalBounds = null;
    const { screen } = require('electron');

    ipcMain.handle('window:side-panel', async () => {
        const win = getMainWindow();
        if (!win) return { success: false };
        const { width, height } = screen.getPrimaryDisplay().workAreaSize;
        originalBounds = win.getBounds();
        win.setBounds({ x: width - 400, y: 0, width: 400, height }, false);
        win.setAlwaysOnTop(true, 'screen-saver');
        return { success: true };
    });

    ipcMain.handle('window:centered', async () => {
        const win = getMainWindow();
        if (!win) return { success: false };
        win.setAlwaysOnTop(false);
        const { width, height } = screen.getPrimaryDisplay().workAreaSize;
        const newWidth = originalBounds?.width || 800;
        const newHeight = originalBounds?.height || 600;
        win.setBounds({
            x: Math.round((width - newWidth) / 2),
            y: Math.round((height - newHeight) / 2),
            width: newWidth,
            height: newHeight
        }, false);
        return { success: true };
    });

    ipcMain.handle('window:blur', async () => {
        const win = getMainWindow();
        if (win) win.blur();
        return { success: true };
    });
}

module.exports = { moveToSidePanel, moveToCentered, blurWindow, register };
