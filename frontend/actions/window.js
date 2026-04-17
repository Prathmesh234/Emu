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

async function minimizeWindow() {
    return await ipcRenderer.invoke('window:minimize');
}

function register(ipcMain, getMainWindow) {
    let originalBounds = null;
    const { screen } = require('electron');

    ipcMain.handle('window:side-panel', async () => {
        const win = getMainWindow();
        if (!win) return { success: false };
        const { width, height } = screen.getPrimaryDisplay().workAreaSize;
        originalBounds = win.getBounds();
        const panelWidth = 450;
        const panelHeight = Math.round(height * 0.75);
        const panelY = Math.round((height - panelHeight) / 2);
        win.setBounds({ x: width - panelWidth - 16, y: panelY, width: panelWidth, height: panelHeight }, false);
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

    ipcMain.handle('window:minimize', async () => {
        const win = getMainWindow();
        if (win) win.minimize();
        return { success: true };
    });
}

module.exports = { moveToSidePanel, moveToCentered, blurWindow, minimizeWindow, register };
