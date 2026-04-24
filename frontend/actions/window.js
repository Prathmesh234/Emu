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

async function maximizeWindow() {
    return await ipcRenderer.invoke('window:maximize');
}

function register(ipcMain, getMainWindow) {
    let originalBounds = null;
    const { screen } = require('electron');
    const { getActiveDisplay } = require('../display/activeDisplay');

    ipcMain.handle('window:side-panel', async () => {
        const win = getMainWindow();
        if (!win) return { success: false };
        const wa = getActiveDisplay(screen, win).workArea;
        originalBounds = win.getBounds();
        const panelWidth = 450;
        const panelHeight = Math.round(wa.height * 0.75);
        win.setBounds({
            x: wa.x + wa.width - panelWidth - 16,
            y: wa.y + Math.round((wa.height - panelHeight) / 2),
            width: panelWidth,
            height: panelHeight,
        }, false);
        win.setAlwaysOnTop(true, 'screen-saver');
        return { success: true };
    });

    ipcMain.handle('window:centered', async () => {
        const win = getMainWindow();
        if (!win) return { success: false };
        win.setAlwaysOnTop(false);
        const wa = getActiveDisplay(screen, win).workArea;
        const newWidth  = originalBounds?.width  || 1040;
        const newHeight = originalBounds?.height || 760;
        win.setBounds({
            x: wa.x + Math.round((wa.width  - newWidth)  / 2),
            y: wa.y + Math.round((wa.height - newHeight) / 2),
            width: newWidth,
            height: newHeight,
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

    // Toggle maximize / restore (macOS-style zoom)
    ipcMain.handle('window:maximize', async () => {
        const win = getMainWindow();
        if (!win) return { success: false };
        if (win.isMaximized()) win.unmaximize();
        else win.maximize();
        return { success: true, maximized: win.isMaximized() };
    });
}

module.exports = { moveToSidePanel, moveToCentered, blurWindow, minimizeWindow, maximizeWindow, register };
