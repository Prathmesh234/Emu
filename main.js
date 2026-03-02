const { app, BrowserWindow, ipcMain, screen, desktopCapturer } = require('electron');
const path = require('path');
const psProcess = require('./frontend/process/psProcess');

const BACKEND_URL = 'http://localhost:8000';

let mainWindow;

// ── IPC handlers (co-located with their action files) ─────────────────────
const { registerAll } = require('./frontend/actions');
registerAll(ipcMain, {
    BACKEND_URL,
    desktopCapturer,
    screen,
    getMainWindow: () => mainWindow
});

// ── App lifecycle ──────────────────────────────────────────────────────────
function createWindow() {
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.workAreaSize;

  mainWindow = new BrowserWindow({
    width: 800,
    height: 600,
    x: Math.round((width - 800) / 2),
    y: Math.round((height - 600) / 2),
    minWidth: 380,
    minHeight: 400,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  });

  mainWindow.loadFile(path.join(__dirname, 'frontend', 'index.html'));

  if (process.env.NODE_ENV === 'development') {
    mainWindow.webContents.openDevTools();
  }
}

app.whenReady().then(() => {
  psProcess.start();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('will-quit', () => {
  psProcess.stop();
});
