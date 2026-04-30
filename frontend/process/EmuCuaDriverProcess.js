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

  // Priority 2: ~/.local/bin (from curl install)
  const local = path.join(os.homedir(), '.local', 'bin', 'emu-cua-driver');
  if (fs.existsSync(local)) return local;

  // Priority 3: /Applications/EmuCuaDriver.app (unlikely, but check)
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

function stop() {
  if (_child) {
    console.log('[emu-cua-driver] stopping');
    _child.kill();
    _child = null;
  }
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
