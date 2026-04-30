const { app, BrowserWindow, ipcMain, screen, shell, systemPreferences } = require('electron');
const path = require('path');
const psProcess = require('./frontend/process/psProcess');
const backendProcess = require('./frontend/process/backendProcess');
const emuCuaDriverProcess = require('./frontend/process/EmuCuaDriverProcess');
const daemonInstaller = require('./frontend/process/daemonInstaller');
const { resolveEmuRoot } = require('./frontend/emu/root');
const { initEmu } = require('./frontend/emu');
const pkg = require('./package.json');
const { lockSessionDisplay, clearSessionLock } = require('./frontend/display/activeDisplay');

const BACKEND_URL = 'http://127.0.0.1:8000';

// Resolve .emu/ location BEFORE anything else runs. Publishing it via
// process.env means every child process (backend, daemon installer) and
// every renderer module inherits the same resolved path without having
// to re-derive it from __dirname (which is wrong inside app.asar).
const EMU_ROOT = resolveEmuRoot(app);
process.env.EMU_ROOT = EMU_ROOT;
console.log(`[emu] EMU_ROOT = ${EMU_ROOT}`);

let mainWindow;
let borderWindow;

// ── App lifecycle ──────────────────────────────────────────────────────────
function createWindow() {
  const primaryDisplay = screen.getPrimaryDisplay();
  const wa = primaryDisplay.workArea;

  // Larger default for the Design System v1 layout (chrome + body + composer
   // needs room; sidebar is 240px when open).
  const DEFAULT_W = 1040;
  const DEFAULT_H = 760;
  mainWindow = new BrowserWindow({
    width:  DEFAULT_W,
    height: DEFAULT_H,
    x: wa.x + Math.round((wa.width  - DEFAULT_W) / 2),
    y: wa.y + Math.round((wa.height - DEFAULT_H) / 2),
    minWidth: 420,
    minHeight: 440,
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
      // Created with placeholder bounds; repositioned to active display before each show.
      borderWindow = new BrowserWindow({
        x: 0, y: 0, width: 100, height: 100,
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

  function showBorderOnActiveDisplay() {
    const display = lockSessionDisplay(screen, mainWindow);
    const bw = ensureBorderWindow();
    bw.setBounds(display.bounds);
    bw.show();
  }

  ipcMain.on('set-border', (event, visible) => {
    if (visible) {
      showBorderOnActiveDisplay();
    } else {
      clearSessionLock();
      if (borderWindow) borderWindow.hide();
    }
  });

  ipcMain.on('set-generating', (event, generating) => {
    // set-generating mirrors set-border; delegate to the same handler
    // so both signals manage the session lock consistently.
    if (generating) {
      showBorderOnActiveDisplay();
    } else {
      if (borderWindow) borderWindow.hide();
      // Do NOT clear the session lock here — set-border:false will do it.
      // Clearing independently could race with an in-flight set-border:true.
    }
  });

  // Register IPC handlers AFTER app is ready (desktopCapturer + screen need this)
  const { registerAll } = require('./frontend/actions');
  registerAll(ipcMain, {
      BACKEND_URL,
      screen,
      getMainWindow: () => mainWindow
  });

  emuCuaDriverProcess.configure({ app });
  ipcMain.handle('emu-cua:ensure-started', async () => (
    emuCuaDriverProcess.ensureStarted({ app })
  ));

  // Eagerly spawn the emu-cua-driver MCP child as soon as Electron is
  // ready, regardless of the persisted agent mode. This pays the
  // ~spawn + initialize + check_permissions cost once at app start so
  // the first coworker action never blocks on it. Fire-and-forget:
  // failures (missing binary, denied AX) are logged here and surface
  // naturally on the first coworker action via the normal error path.
  emuCuaDriverProcess.ensureStarted({ app })
    .then((result) => {
      if (result?.success) {
        const missing = result?.permissions?.missing || [];
        if (missing.length) {
          console.warn(`[emu-cua-driver] startup ok, missing permissions: ${missing.join(', ')}`);
        } else {
          console.log(`[emu-cua-driver] startup ok (pid=${result.pid})`);
        }
      } else {
        console.warn(`[emu-cua-driver] startup deferred: ${result?.error || 'unknown'}`);
      }
    })
    .catch((err) => {
      console.warn(`[emu-cua-driver] startup error: ${err?.message || err}`);
    });

  // Register emu-cua-driver IPC handlers (co-worker mode commands)
  require('./frontend/cua-driver-commands').registerAll(ipcMain, {
      callTool: (toolName, args) => emuCuaDriverProcess.callTool(toolName, args, { app }),
      getMainWindow: () => mainWindow,
  });

  ipcMain.handle('permissions:status', async () => {
    if (process.platform !== 'darwin') {
      return {
        platform: process.platform,
        screenRecording: 'unsupported',
        accessibility: 'unsupported',
      };
    }

    let screenRecording = 'unknown';
    try {
      screenRecording = systemPreferences.getMediaAccessStatus('screen');
    } catch (_) {}

    let accessibility = 'unknown';
    try {
      accessibility = systemPreferences.isTrustedAccessibilityClient(false) ? 'granted' : 'denied';
    } catch (_) {}

    return { platform: process.platform, screenRecording, accessibility };
  });

  ipcMain.handle('permissions:open', async (_event, pane) => {
    if (process.platform !== 'darwin') return { success: false, error: 'not macOS' };
    const urls = {
      screen: 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture',
      accessibility: 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility',
    };
    const url = urls[pane] || urls.screen;
    try {
      await shell.openExternal(url);
      return { success: true };
    } catch (err) {
      return { success: false, error: err.message };
    }
  });

  ipcMain.handle('daemon:status', async () => daemonInstaller.getStatus({ app, emuRoot: EMU_ROOT }));
  ipcMain.handle('daemon:repair', async () => daemonInstaller.repair({ app, emuRoot: EMU_ROOT }));

  psProcess.start();
  // Spawn the backend (dev: backend.sh; packaged: frozen binary).
  // The backend writes .emu/.auth_token on startup; the renderer reads
  // it for every HTTP/WS call. See frontend/services/api.js.
  backendProcess.start({ app, emuRoot: EMU_ROOT });
  daemonInstaller.maybeInstall({ app, emuRoot: EMU_ROOT });
  // emu-cua-driver is lazy-started on first co-worker action (not here)
  // but IPC handlers are registered up front for immediate availability.
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
  backendProcess.stop();
  emuCuaDriverProcess.stop();
});
