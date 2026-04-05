const { app, BrowserWindow, ipcMain, screen } = require('electron');
const path = require('path');
const psProcess = require('./frontend/process/psProcess');
const { initEmu } = require('./frontend/emu');
const pkg = require('./package.json');

const BACKEND_URL = 'http://127.0.0.1:8000';

let mainWindow;
let borderWindow;

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

  // Set up IPC for the desktop border
  ipcMain.on('set-generating', (event, generating) => {
    if (generating) {
      if (!borderWindow) {
        const primaryDisplay = screen.getPrimaryDisplay();
        borderWindow = new BrowserWindow({
          x: primaryDisplay.bounds.x,
          y: primaryDisplay.bounds.y,
          width: primaryDisplay.bounds.width,
          height: primaryDisplay.bounds.height,
          transparent: true,
          frame: false,
          alwaysOnTop: true,
          skipTaskbar: true,
          hasShadow: false,
          focusable: false,
          webPreferences: { nodeIntegration: true, contextIsolation: false }
        });
        borderWindow.setIgnoreMouseEvents(true, { forward: true });
        // Set window level to float above everything (screen saver level)
        borderWindow.setAlwaysOnTop(true, 'screen-saver');
        borderWindow.setVisibleOnAllWorkspaces(true);
        borderWindow.loadFile(path.join(__dirname, 'frontend', 'border.html'));
      } else {
        borderWindow.show();
      }
    } else {
      if (borderWindow) {
        borderWindow.hide();
      }
    }
  });

  // Register IPC handlers AFTER app is ready (desktopCapturer + screen need this)
  const { registerAll } = require('./frontend/actions');
  registerAll(ipcMain, {
      BACKEND_URL,
      screen,
      getMainWindow: () => mainWindow
  });

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
  // Close WebSocket first to prevent reconnect loop, then kill PowerShell
  try { require('./frontend/services/websocket').closeWebSocket(); } catch (_) {}
  psProcess.stop();
});
