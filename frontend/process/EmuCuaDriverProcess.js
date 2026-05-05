// frontend/process/EmuCuaDriverProcess.js
//
// Lifecycle owner for the emu-cua-driver `serve` daemon.
// The Python coworker harness talks to this daemon socket directly; Electron
// makes sure it is reachable, configures the cursor overlay, checks
// permissions, and shuts down the child daemon it owns.

const path = require('path');
const fs = require('fs');
const os = require('os');
const { spawn, spawnSync, execFile, execFileSync } = require('child_process');

let _serveChild = null;
let _serveStarting = null;
let _serveLastBin = null;
let _starting = null;
let _configuredApp = null;
let _permissionsChecked = false;
let _cursorConfiguredFor = null;
let _ownsServeDaemon = false;

// ============================================================================
// Binary Resolution
// ============================================================================

function _resolveBinary(app) {
  // Priority 1: Bundled inside app (emu-cua-driver fork)
  if (app && app.isPackaged) {
    const bundled = path.join(process.resourcesPath, 'emu-cua-driver', 'emu-cua-driver');
    if (fs.existsSync(bundled)) return bundled;
  }

  // Priority 2 (dev only): freshly-built fork inside the repo. Lets local
  // dev test the live nested-driver source without copying the binary into
  // ~/.local/bin every rebuild.
  if (!app || !app.isPackaged) {
    const repoBuild = path.join(
      __dirname, '..', 'coworker-mode', 'emu-driver',
      '.build', 'EmuCuaDriver.app', 'Contents', 'MacOS', 'emu-cua-driver'
    );
    if (fs.existsSync(repoBuild)) return repoBuild;
  }

  // Priority 3: ~/.local/bin (from local install)
  const local = path.join(os.homedir(), '.local', 'bin', 'emu-cua-driver');
  if (fs.existsSync(local)) return local;

  // Priority 4: /Applications/EmuCuaDriver.app (unlikely, but check)
  const appBin = '/Applications/EmuCuaDriver.app/Contents/MacOS/emu-cua-driver';
  if (fs.existsSync(appBin)) return appBin;

  return null;
}

// ============================================================================
// Lifecycle
// ============================================================================

function configure({ app } = {}) {
  if (app) _configuredApp = app;
}

async function start({ app } = {}) {
  return ensureStarted({ app });
}

async function ensureStarted({ app, checkPermissions = true, forcePermissionCheck = false } = {}) {
  try {
    const state = await _ensureStartedOrThrow({ app, checkPermissions, forcePermissionCheck });
    return { success: true, ...state };
  } catch (err) {
    return _startupError(err);
  }
}

async function _ensureStartedOrThrow({ app, checkPermissions = true, forcePermissionCheck = false } = {}) {
  configure({ app });

  if (_starting) {
    return _starting;
  }

  _starting = _startOnce({ checkPermissions, forcePermissionCheck }).finally(() => {
    _starting = null;
  });
  return _starting;
}

async function _startOnce({ checkPermissions, forcePermissionCheck }) {
  const bin = _resolveBinary(_configuredApp);
  if (!bin) {
    throw new Error(
      'emu-cua-driver binary not found. Build/install it from frontend/coworker-mode/emu-driver.'
    );
  }

  await _ensureServeStarted(bin);
  if (_cursorConfiguredFor !== bin) {
    await _configureAgentCursor(bin);
    _cursorConfiguredFor = bin;
  }

  const state = { running: true, pid: _serveChild?.pid || null, binary: bin };
  if (checkPermissions && (forcePermissionCheck || !_permissionsChecked)) {
    state.permissions = await _checkPermissions(bin);
  }
  return state;
}

// ============================================================================
// Daemon (`serve`) lifecycle
// ============================================================================

function _ensureServeStarted(bin) {
  if (_serveChild && _serveChild.exitCode === null && _serveChild.signalCode === null) {
    return Promise.resolve();
  }
  if (_serveStarting) return _serveStarting;
  _serveStarting = _startServeOnce(bin).finally(() => {
    _serveStarting = null;
  });
  return _serveStarting;
}

function _startServeOnce(bin) {
  return new Promise((resolve, reject) => {
    _serveLastBin = bin;
    if (_isDaemonRunning(bin)) {
      if (_isDaemonCompatible(bin)) {
        console.log('[emu-cua-driver] using existing daemon');
        _ownsServeDaemon = false;
        resolve();
        return;
      }
      console.warn('[emu-cua-driver] existing daemon is incompatible; restarting it');
      _stopExistingDaemon(bin);
    }

    // `--no-relaunch` keeps the daemon as our child so quitting Emu shuts down
    // the AX cache and agent cursor instead of leaving a stale socket process.
    console.log(`[emu-cua-driver] spawning daemon: ${bin} serve --no-relaunch`);
    const child = spawn(bin, ['serve', '--no-relaunch'], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    _ownsServeDaemon = true;
    let settled = false;
    let readyTimer = null;
    const settle = (err) => {
      if (settled) return;
      settled = true;
      if (readyTimer) {
        clearTimeout(readyTimer);
        readyTimer = null;
      }
      err ? reject(err) : resolve();
    };

    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (chunk) => {
      if (!settled && /daemon started on/i.test(chunk)) {
        _ownsServeDaemon = true;
        settle();
      }
      process.stdout.write(`[emu-cua-driver:serve] ${chunk}`);
    });
    child.stderr.on('data', (chunk) => {
      const text = chunk.toString();
      if (!settled && /daemon is already running/i.test(text)) {
        console.warn(`[emu-cua-driver:serve] ${text.trim()}`);
        _ownsServeDaemon = false;
        settle();
        return;
      }
      console.error(`[emu-cua-driver:serve stderr] ${text}`);
    });
    child.on('exit', (code, signal) => {
      console.log(`[emu-cua-driver:serve] exited code=${code} signal=${signal}`);
      if (_serveChild === child) {
        _serveChild = null;
        _ownsServeDaemon = false;
      }
      _permissionsChecked = false;
      _cursorConfiguredFor = null;
      if (!settled) settle(new Error(`serve exited before bind (code=${code} signal=${signal})`));
    });
    child.on('error', (err) => {
      if (!settled) settle(err);
    });

    _serveChild = child;
    readyTimer = setTimeout(() => {
      if (_isDaemonRunning(bin)) {
        settle();
        return;
      }
      try { child.kill('SIGTERM'); } catch (_) {}
      settle(new Error('serve did not become ready within 5000ms'));
    }, 5000);
    if (readyTimer.unref) readyTimer.unref();
  });
}

function _isDaemonRunning(bin) {
  try {
    const result = spawnSync(bin, ['status'], { timeout: 2000, stdio: 'ignore' });
    return result.status === 0;
  } catch (_) {
    return false;
  }
}

function _isDaemonCompatible(bin) {
  try {
    const result = spawnSync(
      bin,
      ['describe', 'set_agent_cursor_style'],
      { timeout: 2000, stdio: 'ignore' }
    );
    return result.status === 0;
  } catch (_) {
    return false;
  }
}

function _stopExistingDaemon(bin) {
  try {
    spawnSync(bin, ['stop'], { timeout: 2000, stdio: 'ignore' });
  } catch (_) {
    // Best effort: a missing/stopped daemon should not block startup.
  }
}

function _stopServe() {
  const child = _serveChild;
  if (child && child.exitCode === null && child.signalCode === null) {
    console.log('[emu-cua-driver] stopping daemon');
    try { child.kill('SIGTERM'); } catch (_) {}
    setTimeout(() => {
      if (child.exitCode === null && child.signalCode === null) {
        console.warn('[emu-cua-driver] daemon did not exit after SIGTERM; forcing stop');
        try { child.kill('SIGKILL'); } catch (_) {}
      }
    }, 1500).unref();
  }
  _serveChild = null;
  _serveStarting = null;
  _ownsServeDaemon = false;
}

// ============================================================================
// Driver setup helpers
// ============================================================================

function _callDriver(bin, args, timeout = 5000) {
  return new Promise((resolve, reject) => {
    execFile(bin, args, { timeout }, (err, stdout, stderr) => {
      if (err) {
        err.stderr = stderr;
        err.stdout = stdout;
        reject(err);
        return;
      }
      resolve((stdout || '').trim());
    });
  });
}

async function _configureAgentCursor(bin) {
  const calls = [
    ['set_agent_cursor_enabled', {
      enabled: true,
    }],
    ['set_agent_cursor_motion', {
      start_handle: 0.36,
      end_handle: 0.36,
      arc_size: 0.28,
      spring: 0.82,
      glide_duration_ms: 1150,
      dwell_after_click_ms: 300,
      idle_hide_ms: 20000,
    }],
    ['set_agent_cursor_style', {
      gradient_colors: ['#FFFFFF', '#FFFFFF'],
      bloom_color: '#EDE7D8',
      shape_size: 8,
    }],
  ];

  await Promise.all(calls.map(async ([tool, args]) => {
    try {
      await _callDriver(bin, ['call', tool, JSON.stringify(args)], 5000);
      console.log(`[emu-cua-driver] agent cursor configured (${tool})`);
    } catch (err) {
      console.warn(`[emu-cua-driver] ${tool} failed: ${err?.message || err}`);
    }
  }));
}

async function _checkPermissions(bin) {
  const output = await _callDriver(
    bin,
    ['call', 'check_permissions', JSON.stringify({ prompt: false })],
    15_000
  );
  const missing = _missingPermissions(output);
  _permissionsChecked = missing.length === 0;
  return {
    granted: missing.length === 0,
    missing,
    output,
  };
}

function _hideAgentCursor(bin) {
  if (!bin) return;
  try {
    execFileSync(
      bin,
      ['call', 'set_agent_cursor_enabled', JSON.stringify({ enabled: false })],
      { timeout: 2000, stdio: 'ignore' }
    );
    console.log('[emu-cua-driver] agent cursor hidden');
  } catch (err) {
    console.warn(`[emu-cua-driver] hide cursor failed: ${err?.message || err}`);
  }
}

function _requestDaemonStop(bin) {
  if (!bin) return;
  try {
    execFileSync(bin, ['stop'], { timeout: 2000, stdio: 'ignore' });
    console.log('[emu-cua-driver] daemon stop requested');
  } catch (err) {
    console.warn(`[emu-cua-driver] daemon stop request failed: ${err?.message || err}`);
  }
}

function stop() {
  const bin = _serveLastBin || _resolveBinary(_configuredApp);
  if (_ownsServeDaemon) {
    _hideAgentCursor(bin);
    _requestDaemonStop(bin);
  }
  _stopServe();
  _permissionsChecked = false;
  _cursorConfiguredFor = null;
  _starting = null;
}

async function recheckPermissions({ app } = {}) {
  configure({ app });
  const bin = _serveLastBin || _resolveBinary(_configuredApp);
  if (!bin) {
    throw new Error(
      'emu-cua-driver binary not found. Build/install it from frontend/coworker-mode/emu-driver.'
    );
  }

  const childAlive = _serveChild && _serveChild.exitCode === null && _serveChild.signalCode === null;
  if (childAlive || _isDaemonRunning(bin)) {
    return _checkPermissions(bin);
  }

  const state = await _ensureStartedOrThrow({ checkPermissions: true });
  return state.permissions || { granted: true, missing: [], output: '' };
}

async function callTool(toolName, args = {}, { app } = {}) {
  configure({ app });
  const state = await _ensureStartedOrThrow({ checkPermissions: true });
  const bin = state.binary || _serveLastBin || _resolveBinary(_configuredApp);
  if (!bin) {
    throw new Error(
      'emu-cua-driver binary not found. Build/install it from frontend/coworker-mode/emu-driver.'
    );
  }

  const output = await _callDriverRawResult(
    bin,
    ['call', toolName, JSON.stringify(args || {}), '--raw', '--compact'],
    30_000
  );
  return _parseToolResult(output, toolName);
}

function _missingPermissions(output) {
  const missing = [];
  if (_permissionLineIsMissing(output, 'Accessibility')) missing.push('accessibility');
  if (_permissionLineIsMissing(output, 'Screen Recording')) missing.push('screen');
  return missing;
}

function _permissionLineIsMissing(output, label) {
  const text = String(output || '');
  const line = text
    .split(/\r?\n/)
    .find((item) => new RegExp(label, 'i').test(item));
  if (!line) return false;
  return /not\s*granted|denied|not.?determined|restricted|missing|unauthori[sz]ed|requires|disabled|false/i.test(line);
}

function _isDriverBinaryMissing(message) {
  return /binary not found|build\/install|install it from/i.test(String(message || ''));
}

function _looksLikePermissionFailure(message) {
  const text = String(message || '');
  if (_isDriverBinaryMissing(text)) return false;
  return /permission|accessibility|screen recording|screen capture|not authorized|not authorised|unauthori[sz]ed|requires/i.test(text);
}

function _startupError(err) {
  const message = err?.message || String(err);
  return {
    success: false,
    running: false,
    error: message,
    permissionsRequired: _looksLikePermissionFailure(message),
  };
}

function _callDriverRawResult(bin, args, timeout = 5000) {
  return new Promise((resolve, reject) => {
    execFile(bin, args, { timeout }, (err, stdout, stderr) => {
      if (stdout && stdout.trim()) {
        resolve(stdout.trim());
        return;
      }
      if (err) {
        err.stderr = stderr;
        err.stdout = stdout;
        reject(err);
        return;
      }
      resolve('');
    });
  });
}

function _parseToolResult(output, toolName) {
  if (!output) {
    throw new Error(`emu-cua-driver ${toolName} returned no output`);
  }
  try {
    return JSON.parse(output);
  } catch (err) {
    throw new Error(
      `emu-cua-driver ${toolName} returned invalid JSON: ${err?.message || err}`
    );
  }
}

// ============================================================================
// Exports
// ============================================================================

module.exports = {
  configure,
  start,
  ensureStarted,
  recheckPermissions,
  callTool,
  stop,
};
