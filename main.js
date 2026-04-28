const { app, BrowserWindow, ipcMain, screen } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const psProcess = require('./frontend/process/psProcess');
const { initEmu } = require('./frontend/emu');
const pkg = require('./package.json');

const BACKEND_URL = 'http://127.0.0.1:8000';

let mainWindow;
let borderWindow;

// ── SkyLight Daemon Management ─────────────────────────────────────────────
const DAEMON_SOCKET_PATH = '/tmp/skylight-daemon.sock';
const DAEMON_BINARY_PATH = path.join(__dirname, 'daemon', 'skylight-daemon', 'build', 'skylight-daemon');

let daemonProcess = null;

function isSkylightDaemonRunning() {
  return fs.existsSync(DAEMON_SOCKET_PATH);
}

async function startSkylightDaemon() {
  if (isSkylightDaemonRunning()) {
    console.log('[main] SkyLight daemon is already running');
    return true;
  }

  if (!fs.existsSync(DAEMON_BINARY_PATH)) {
    console.warn('[main] SkyLight daemon binary not found, skipping daemon startup');
    return false;
  }

  try {
    console.log('[main] Starting SkyLight daemon...');
    daemonProcess = spawn(DAEMON_BINARY_PATH, [], {
      detached: false,
      stdio: ['ignore', 'pipe', 'pipe']
    });

    daemonProcess.stdout.on('data', (data) => {
      console.log(`[daemon] ${data.toString().trim()}`);
    });

    daemonProcess.stderr.on('data', (data) => {
      console.error(`[daemon] ${data.toString().trim()}`);
    });

    daemonProcess.on('error', (err) => {
      console.error('[main] Failed to start daemon:', err.message);
    });

    // Wait for socket to appear (up to 2 seconds)
    for (let i = 0; i < 20; i++) {
      if (isSkylightDaemonRunning()) {
        console.log('[main] ✓ SkyLight daemon is running');
        return true;
      }
      await new Promise(resolve => setTimeout(resolve, 100));
    }

    console.warn('[main] SkyLight daemon socket did not appear');
    return false;
  } catch (err) {
    console.error('[main] Error starting SkyLight daemon:', err.message);
    return false;
  }
}

async function stopSkylightDaemon() {
  if (daemonProcess && !daemonProcess.killed) {
    console.log('[main] Stopping SkyLight daemon...');
    daemonProcess.kill('SIGTERM');

    // Wait for process to exit (up to 2 seconds)
    for (let i = 0; i < 20; i++) {
      if (daemonProcess.killed || daemonProcess.exitCode !== null) {
        console.log('[main] ✓ SkyLight daemon stopped');
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 100));
    }

    console.warn('[main] Forcing daemon termination');
    daemonProcess.kill('SIGKILL');
  }
}

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
      contextIsolation: false
    }
  });

  mainWindow.loadFile(path.join(__dirname, 'frontend', 'index.html'));

  if (process.env.NODE_ENV === 'development') {
    mainWindow.webContents.openDevTools();
  }
}

app.whenReady().then(async () => {
  // Bootstrap .emu/ folder (idempotent — safe on every launch)
  initEmu(pkg.version);

  // Start SkyLight daemon for coworker mode
  await startSkylightDaemon();

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
        webPreferences: { nodeIntegration: true, contextIsolation: false }
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

app.on('will-quit', async () => {
  // Close WebSocket first to prevent reconnect loop, then kill PowerShell
  try { require('./frontend/services/websocket').closeWebSocket(); } catch (_) {}
  psProcess.stop();
  
  // Stop SkyLight daemon gracefully
  await stopSkylightDaemon();
});
