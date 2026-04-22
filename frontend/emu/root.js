/**
 * frontend/emu/root.js — Single source of truth for the .emu directory.
 *
 * Resolution order (highest priority first):
 *   1. process.env.EMU_ROOT if set — honors a developer / CI override.
 *   2. Packaged app → <userData>/.emu (writable, per-user, survives updates).
 *   3. Source checkout → <repo>/.emu (preserves dev ergonomics; lives next to
 *      the code so `ls`, git status, etc. still show it).
 *
 * Called once from main.js on startup, which then sets process.env.EMU_ROOT
 * so every child process (backend, daemon installer) inherits the same
 * value without re-running this logic.
 */

const path = require('path');
const fs = require('fs');

let _cached = null;

/**
 * Resolve the absolute .emu directory path.
 * Pass the Electron `app` module so we can detect packaged vs. source.
 * Safe to call without `app` from the renderer — it'll fall back to env.
 */
function resolveEmuRoot(app) {
    if (_cached) return _cached;

    const fromEnv = (process.env.EMU_ROOT || '').trim();
    if (fromEnv) {
        _cached = path.resolve(fromEnv);
    } else if (app && typeof app.isPackaged === 'boolean' && app.isPackaged) {
        _cached = path.join(app.getPath('userData'), '.emu');
    } else {
        // Source-checkout default: <repo>/.emu (this file is at
        // <repo>/frontend/emu/root.js, so go up two levels).
        _cached = path.resolve(__dirname, '..', '..', '.emu');
    }

    try {
        fs.mkdirSync(_cached, { recursive: true });
    } catch (_) { /* best effort — init.js will retry */ }

    return _cached;
}

/**
 * Get the cached .emu path. Must be called after resolveEmuRoot() from main.
 * In the renderer, this returns whatever the main process published via
 * process.env.EMU_ROOT.
 */
function getEmuRoot() {
    if (_cached) return _cached;
    const fromEnv = (process.env.EMU_ROOT || '').trim();
    if (fromEnv) {
        _cached = path.resolve(fromEnv);
        return _cached;
    }
    // Fallback to source-layout default so we never return null.
    _cached = path.resolve(__dirname, '..', '..', '.emu');
    return _cached;
}

// ── Path helpers ─────────────────────────────────────────────────────────
// Convenience wrappers so callers don't have to remember subpaths. Every
// path is anchored at getEmuRoot(), so they all honor EMU_ROOT / packaged
// userData / source-checkout resolution automatically.

function emuPath(...segments) {
    return path.join(getEmuRoot(), ...segments);
}

function authTokenPath() {
    return emuPath('.auth_token');
}

function memoryDir() {
    return emuPath('workspace', 'memory');
}

function readAuthToken() {
    try {
        return fs.readFileSync(authTokenPath(), 'utf8').trim();
    } catch {
        return '';
    }
}

module.exports = {
    resolveEmuRoot,
    getEmuRoot,
    emuPath,
    authTokenPath,
    memoryDir,
    readAuthToken,
};
