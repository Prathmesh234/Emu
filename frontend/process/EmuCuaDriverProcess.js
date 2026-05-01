// frontend/process/EmuCuaDriverProcess.js
//
// Lifecycle for the emu-cua-driver MCP stdio child process.
// (Our fork of cua-driver, customized for Emu)
// Spawned lazily on first co-worker action, killed on app quit.
// Handles JSON-RPC 2.0 request/response matching over stdio.

const path = require('path');
const fs = require('fs');
const os = require('os');
const { spawn } = require('child_process');
const pkg = require('../../package.json');

let _child = null;
let _serveChild = null;        // long-running `serve` daemon (Unix socket)
let _serveStarting = null;
let _serveLastBin = null;
let _starting = null;
let _configuredApp = null;
let _initialized = false;
let _permissionsChecked = false;
let _nextId = 1;
const _pending = new Map(); // id -> { resolve, reject, timeout }
let _stdoutBuf = '';

const REQUEST_TIMEOUT_MS = 15_000;
const INITIALIZE_TIMEOUT_MS = 20_000;
const MCP_PROTOCOL_VERSION = '2025-03-26';

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
  // dev test the live nested-driver source without `cp`-ing the binary
  // into ~/.local/bin every rebuild.
  if (!app || !app.isPackaged) {
    const repoBuild = path.join(
      __dirname, '..', 'coworker-mode', 'emu-driver',
      '.build', 'EmuCuaDriver.app', 'Contents', 'MacOS', 'emu-cua-driver'
    );
    if (fs.existsSync(repoBuild)) return repoBuild;
  }

  // Priority 3: ~/.local/bin (from curl install)
  const local = path.join(os.homedir(), '.local', 'bin', 'emu-cua-driver');
  if (fs.existsSync(local)) return local;

  // Priority 4: /Applications/EmuCuaDriver.app (unlikely, but check)
  const app_bin = '/Applications/EmuCuaDriver.app/Contents/MacOS/emu-cua-driver';
  if (fs.existsSync(app_bin)) return app_bin;

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

async function ensureStarted({ app, checkPermissions = true } = {}) {
  try {
    const state = await _ensureStartedOrThrow({ app, checkPermissions });
    return { success: true, ...state };
  } catch (err) {
    return _startupError(err);
  }
}

async function _ensureStartedOrThrow({ app, checkPermissions = true } = {}) {
  configure({ app });

  if (_child && _initialized) {
    const state = { running: true, pid: _child.pid };
    if (checkPermissions && !_permissionsChecked) {
      state.permissions = await _checkPermissions();
    }
    return state;
  }

  if (_starting) {
    return _starting;
  }

  _starting = _startOnce({ checkPermissions }).finally(() => {
    _starting = null;
  });
  return _starting;
}

async function _startOnce({ checkPermissions }) {
  const bin = _resolveBinary(_configuredApp);
  if (!bin) {
    throw new Error(
      'emu-cua-driver binary not found. Build/install it from frontend/coworker-mode/emu-driver.'
    );
  }

  console.log(`[emu-cua-driver] spawning: ${bin} mcp`);
  _child = spawn(bin, ['mcp'], { stdio: ['pipe', 'pipe', 'pipe'] });
  _initialized = false;
  _permissionsChecked = false;
  _stdoutBuf = '';

  _child.stdout.setEncoding('utf8');
  _child.stdout.on('data', (chunk) => {
    _stdoutBuf += chunk;
    _processStdout();
  });

  _child.stderr.on('data', (chunk) => {
    console.error(`[emu-cua-driver stderr] ${chunk}`);
  });

  _child.on('exit', (code, signal) => {
    console.log(`[emu-cua-driver] exited code=${code} signal=${signal}`);
    _child = null;
    _initialized = false;
    _permissionsChecked = false;
    _clearPending('emu-cua-driver exited');
  });

  try {
    await _initialize();
    // Spawn the long-running `serve` daemon as a sibling. The daemon owns
    // the persistent AppKit run loop + per-pid AX cache, so any
    // `emu-cua-driver call ...` shell-out from the Python backend
    // auto-forwards to its Unix socket. Without it, each CLI call is a
    // fresh process: the AX cache is empty (model gets "No cached AX
    // state for pid X" errors when using element_index) and the agent
    // cursor overlay flashes once per call and dies with the process.
    // Failures here are non-fatal — element_index workflows degrade to
    // "no cached AX state" messages, but pixel/coord clicks still work.
    _ensureServeStarted(bin)
      .then(() => _configureAgentCursor(bin))
      .catch((err) => {
        console.warn(`[emu-cua-driver] serve daemon start failed: ${err?.message || err}`);
      });
    const state = { running: true, pid: _child.pid, binary: bin };
    if (checkPermissions) {
      state.permissions = await _checkPermissions();
    }
    return state;
  } catch (err) {
    stop();
    throw err;
  }
}

// ============================================================================
// Daemon (`serve`) lifecycle — sibling of the stdio MCP child
// ============================================================================

function _ensureServeStarted(bin) {
  if (_serveChild && !_serveChild.killed) return Promise.resolve();
  if (_serveStarting) return _serveStarting;
  _serveStarting = _startServeOnce(bin).finally(() => {
    _serveStarting = null;
  });
  return _serveStarting;
}

function _startServeOnce(bin) {
  return new Promise((resolve, reject) => {
    _serveLastBin = bin;
    // `--no-relaunch` keeps the daemon attached to this process so we can
    // manage its lifetime; we trust Electron's TCC grants (AX + screen
    // recording) to cover the daemon since it inherits our identity.
    console.log(`[emu-cua-driver] spawning daemon: ${bin} serve --no-relaunch`);
    const child = spawn(bin, ['serve', '--no-relaunch'], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let settled = false;
    const settle = (err) => {
      if (settled) return;
      settled = true;
      err ? reject(err) : resolve();
    };

    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (chunk) => {
      // Daemon prints "emu-cua-driver daemon started on <socket>" on bind.
      if (!settled && /daemon started on/i.test(chunk)) settle();
      // Surface daemon stdout under a clear prefix for diagnostics.
      process.stdout.write(`[emu-cua-driver:serve] ${chunk}`);
    });
    child.stderr.on('data', (chunk) => {
      const text = chunk.toString();
      // Idempotent re-start case: another daemon is already listening on
      // the default socket. Treat as success — CLI calls auto-forward to
      // whoever owns the socket.
      if (!settled && /daemon is already running/i.test(text)) {
        console.warn(`[emu-cua-driver:serve] ${text.trim()}`);
        settle();
        return;
      }
      console.error(`[emu-cua-driver:serve stderr] ${text}`);
    });
    child.on('exit', (code, signal) => {
      console.log(`[emu-cua-driver:serve] exited code=${code} signal=${signal}`);
      if (_serveChild === child) _serveChild = null;
      if (!settled) settle(new Error(`serve exited before bind (code=${code} signal=${signal})`));
    });
    child.on('error', (err) => {
      if (!settled) settle(err);
    });

    _serveChild = child;
    // Safety timeout — bind should complete in well under a second.
    setTimeout(() => settle(), 5000);
  });
}

function _stopServe() {
  if (_serveChild && !_serveChild.killed) {
    console.log('[emu-cua-driver] stopping daemon');
    try { _serveChild.kill('SIGTERM'); } catch (_) {}
  }
  _serveChild = null;
  _serveStarting = null;
}

// Configure the agent-cursor overlay so it stays pinned for the whole
// app session — including after the agent stops. `idle_hide_ms: 0`
// disables the daemon's idle-hide timer, so the overlay remains visible
// until the driver/app shuts down.
// Fire-and-forget — the daemon already defaults to enabled, so a
// failure here just means slightly less-sticky cursor, not a broken
// session.
function _configureAgentCursor(bin) {
  try {
    const { execFile } = require('child_process');
    const calls = [
      ['set_agent_cursor_motion', { idle_hide_ms: 0 }],
      ['set_agent_cursor_style', {
        gradient_colors: ['#FFFFFF', '#F7FBFF'],
        bloom_color: '#2F80FF',
        shape_size: 18,
      }],
    ];

    for (const [tool, args] of calls) {
      execFile(
        bin,
        ['call', tool, JSON.stringify(args)],
        { timeout: 5000 },
        (err) => {
          if (err) {
            console.warn(`[emu-cua-driver] ${tool} failed: ${err.message}`);
          } else {
            console.log(`[emu-cua-driver] agent cursor configured (${tool})`);
          }
        }
      );
    }
  } catch (err) {
    console.warn(`[emu-cua-driver] _configureAgentCursor error: ${err?.message || err}`);
  }
}

function stop() {
  if (_child) {
    console.log('[emu-cua-driver] stopping');
    _child.kill();
    _child = null;
  }
  _stopServe();
  _initialized = false;
  _permissionsChecked = false;
  _starting = null;
  _clearPending('emu-cua-driver stopped');
}

// ============================================================================
// JSON-RPC Communication
// ============================================================================

async function callTool(toolName, args = {}, opts = {}) {
  await _ensureStartedOrThrow({ app: opts.app, checkPermissions: true });
  return _sendRequest(
    'tools/call',
    { name: toolName, arguments: args || {} },
    REQUEST_TIMEOUT_MS,
    toolName
  );
}

async function _initialize() {
  await _sendRequest(
    'initialize',
    {
      protocolVersion: MCP_PROTOCOL_VERSION,
      capabilities: {},
      clientInfo: {
        name: 'emu',
        version: pkg.version || '0.0.0',
      },
    },
    INITIALIZE_TIMEOUT_MS,
    'initialize'
  );
  _sendNotification('notifications/initialized');
  _initialized = true;
}

async function _checkPermissions() {
  const result = await _sendRequest(
    'tools/call',
    { name: 'check_permissions', arguments: { prompt: false } },
    REQUEST_TIMEOUT_MS,
    'check_permissions'
  );
  const output = _summarizeText(result);
  const missing = _missingPermissions(output);
  _permissionsChecked = missing.length === 0;
  return {
    granted: missing.length === 0,
    missing,
    output,
  };
}

function _sendRequest(method, params, timeoutMs, label) {
  return new Promise((resolve, reject) => {
    if (!_child) {
      return reject(new Error('emu-cua-driver not running'));
    }

    const id = _nextId++;
    const request = { jsonrpc: '2.0', id, method };
    if (params !== undefined) request.params = params;

    const timeout = setTimeout(() => {
      _pending.delete(id);
      reject(new Error(`emu-cua-driver timeout (${timeoutMs}ms): ${label || method}`));
    }, timeoutMs);

    _pending.set(id, { resolve, reject, timeout });

    _child.stdin.write(JSON.stringify(request) + '\n', (err) => {
      if (err) {
        _pending.delete(id);
        clearTimeout(timeout);
        reject(err);
      }
    });
  });
}

function _sendNotification(method, params) {
  if (!_child) return;
  const request = { jsonrpc: '2.0', method };
  if (params !== undefined) request.params = params;
  _child.stdin.write(JSON.stringify(request) + '\n');
}

// ============================================================================
// Stdout Processing (JSON-RPC Response Parsing)
// ============================================================================

function _processStdout() {
  const lines = _stdoutBuf.split('\n');

  // Keep the last (possibly incomplete) line in the buffer
  _stdoutBuf = lines[lines.length - 1];

  // Process all complete lines
  for (let i = 0; i < lines.length - 1; i++) {
    const line = lines[i].trim();
    if (!line) continue;

    try {
      const msg = JSON.parse(line);

      // Handle result
      if (msg.id !== undefined && _pending.has(msg.id)) {
        const { resolve, reject, timeout } = _pending.get(msg.id);
        _pending.delete(msg.id);
        clearTimeout(timeout);

        if (msg.error) {
          reject(new Error(msg.error.message || JSON.stringify(msg.error)));
        } else {
          resolve(msg.result);
        }
      }
    } catch (err) {
      console.error(`[emu-cua-driver] parse error: ${err.message}`);
    }
  }
}

function _clearPending(reason) {
  for (const { reject, timeout } of _pending.values()) {
    clearTimeout(timeout);
    reject(new Error(reason));
  }
  _pending.clear();
}

function _summarizeText(result) {
  if (!result?.content) return '';
  return result.content
    .filter((item) => item.type === 'text')
    .map((item) => item.text || '')
    .join('\n');
}

function _missingPermissions(output) {
  const missing = [];
  if (/Accessibility:\s*NOT granted/i.test(output)) missing.push('accessibility');
  if (/Screen Recording:\s*NOT granted/i.test(output)) missing.push('screen');
  return missing;
}

function _startupError(err) {
  const message = err?.message || String(err);
  return {
    success: false,
    running: false,
    error: message,
    permissionsRequired: /permission|Accessibility|Screen Recording/i.test(message),
  };
}

// ============================================================================
// Exports
// ============================================================================

module.exports = {
  configure,
  start,
  ensureStarted,
  stop,
  callTool,
};
