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
      // TODO: Security — migrate to nodeIntegration:false + contextIsolation:true
      // Currently required because the renderer uses CommonJS require() throughout.
      // Fixing this requires adding a bundler (esbuild/webpack) to resolve modules
      // at build time, then routing all IPC through the preload.js bridge.
      nodeIntegration: true,
      contextIsolation: false,
      preload: path.join(__dirname, 'preload.js')
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
  // Border is shown only while the agent is executing.
  function ensureBorderWindow() {
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
        webPreferences: { nodeIntegration: true, contextIsolation: false, preload: path.join(__dirname, 'preload.js') }
      });
      borderWindow.setIgnoreMouseEvents(true, { forward: true });
      borderWindow.setAlwaysOnTop(true, 'screen-saver');
      borderWindow.setVisibleOnAllWorkspaces(true);
      borderWindow.loadFile(path.join(__dirname, 'frontend', 'border.html'));
    }
    return borderWindow;
  }

  ipcMain.on('set-border', (event, visible) => {
    if (visible) {
      ensureBorderWindow().show();
    } else {
      if (borderWindow) borderWindow.hide();
    }
  });

  ipcMain.on('set-generating', (event, generating) => {
    if (generating) {
      ensureBorderWindow().show();
    } else {
      if (borderWindow) borderWindow.hide();
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
  // Close WebSocket first to prevent reconnect loop, then kill the shell process
  try { require('./frontend/services/websocket').closeWebSocket(); } catch (_) {}
  psProcess.stop();
});
