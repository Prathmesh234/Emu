// frontend/process/cuaDriverProcess.js
//
// Lifecycle for the emu-cua-driver MCP stdio child process.
// (Our fork of cua-driver, customized for Emu)
// Spawned lazily on first co-worker action, killed on app quit.
// Handles JSON-RPC 2.0 request/response matching over stdio.

const path = require('path');
const fs = require('fs');
const os = require('os');
const { spawn } = require('child_process');

let _child = null;
let _nextId = 1;
const _pending = new Map(); // id -> { resolve, reject, timeout }
let _stdoutBuf = '';

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

function start({ app }) {
  if (_child) return true;

  const bin = _resolveBinary(app);
  if (!bin) {
    console.warn('[emu-cua-driver] binary not found');
    return false;
  }

  console.log(`[emu-cua-driver] spawning: ${bin} mcp`);
  _child = spawn(bin, ['mcp'], { stdio: ['pipe', 'pipe', 'pipe'] });

  _child.stdout.setEncoding('utf8');
  _child.stdout.on('data', (chunk) => {
    _stdoutBuf += chunk;
    _processStdout();
  });

  _child.stderr.on('data', (chunk) => {
    console.error(`[emu-cua-driver stderr] ${chunk}`);
  });

  _child.on('exit', (code) => {
    console.log(`[emu-cua-driver] exited with code ${code}`);
    _child = null;
    _clearPending('emu-cua-driver exited');
  });

  return true;
}

function stop() {
  if (_child) {
    console.log('[emu-cua-driver] stopping');
    _child.kill();
    _child = null;
  }
  _clearPending('emu-cua-driver stopped');
}

// ============================================================================
// JSON-RPC Communication
// ============================================================================

function callTool(toolName, args = {}) {
  return new Promise((resolve, reject) => {
    if (!_child) {
      return reject(new Error('emu-cua-driver not running'));
    }

    const id = _nextId++;
    const request = {
      jsonrpc: '2.0',
      id,
      method: 'tools/call',
      params: {
        name: toolName,
        arguments: args,
      },
    };

    const timeout = setTimeout(() => {
      _pending.delete(id);
      reject(new Error(`emu-cua-driver timeout (15s): ${toolName}`));
    }, 15000);

    _pending.set(id, { resolve, reject, timeout });

    const jsonLine = JSON.stringify(request) + '\n';
    _child.stdin.write(jsonLine, (err) => {
      if (err) {
        _pending.delete(id);
        clearTimeout(timeout);
        reject(err);
      }
    });
  });
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
  for (const { resolve, reject, timeout } of _pending.values()) {
    clearTimeout(timeout);
    reject(new Error(reason));
  }
  _pending.clear();
}

// ============================================================================
// Exports
// ============================================================================

module.exports = {
  start,
  stop,
  callTool,
};
