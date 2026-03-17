const { app, BrowserWindow, ipcMain, screen } = require('electron');
const path = require('path');
const psProcess = require('./frontend/process/psProcess');
const { initEmu } = require('./frontend/emu');
const pkg = require('./package.json');

const BACKEND_URL = 'http://172.23.104.4:8000';

let mainWindow;

// ── IPC handlers (co-located with their action files) ─────────────────────
const { registerAll } = require('./frontend/actions');
registerAll(ipcMain, {
    BACKEND_URL,
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
    frame: false,
    transparent: true,
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
  // Bootstrap .emu/ folder (idempotent — safe on every launch)
  initEmu(pkg.version);

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
  // Close WebSocket first to prevent reconnect loop, then kill shell process
  try { require('./frontend/services/websocket').closeWebSocket(); } catch (_) {}
  psProcess.stop();
});
