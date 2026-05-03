/**
 * preload.js — Secure bridge between main and renderer processes.
 *
 * With contextIsolation: true and nodeIntegration: false, the renderer
 * cannot access Node.js APIs directly.  This preload script exposes only
 * the specific IPC channels the renderer needs via contextBridge.
 */

const { contextBridge, ipcRenderer } = require('electron');
const fs = require('fs');
const { authTokenPath } = require('./frontend/emu/root');

// ── Allowed IPC channels ───────────────────────────────────────────────────
// Only these channels can be invoked / sent from the renderer.

const ALLOWED_INVOKE_CHANNELS = new Set([
    'screenshot:capture',
    'screenshot:fullCapture',
    'mouse:move',
    'mouse:left-click',
    'mouse:right-click',
    'mouse:double-click',
    'mouse:triple-click',
    'mouse:drag',
    'mouse:scroll',
    'keyboard:key-press',
    'keyboard:type',
    'shell:exec',
    'memory:read',
    'window:side-panel',
    'window:centered',
    'window:blur',
    'window:minimize',
    'window:maximize',
    'permissions:status',
    'permissions:open',
    'emu-cua:screenshot',
    'emu-cua:recheck-permissions',
    'daemon:status',
    'daemon:repair',
]);

const ALLOWED_RECEIVE_CHANNELS = new Set([
    'emu-cua:permissions-required',
]);

const ALLOWED_SEND_CHANNELS = new Set([
    'set-border',
    'set-generating',
]);

// ── Read auth token for API calls ──────────────────────────────────────────
// Token path is derived from EMU_ROOT (set by main.js before preload loads),
// NOT from __dirname — inside a packaged app.asar, __dirname points into the
// read-only bundle and the token file lives elsewhere (<userData>/.emu).
const TOKEN_PATH = authTokenPath();

function readAuthToken() {
    try {
        return fs.readFileSync(TOKEN_PATH, 'utf8').trim();
    } catch {
        console.warn('[preload] Could not read auth token from', TOKEN_PATH);
        return '';
    }
}

// ── Expose safe API to renderer ────────────────────────────────────────────
const electronAPI = {
    /**
     * Invoke an IPC handler in the main process and await the result.
     * Only allowed channels are permitted.
     */
    invoke(channel, data) {
        if (!ALLOWED_INVOKE_CHANNELS.has(channel)) {
            return Promise.reject(new Error(`IPC channel not allowed: ${channel}`));
        }
        return ipcRenderer.invoke(channel, data);
    },

    /**
     * Send a one-way message to the main process.
     * Only allowed channels are permitted.
     */
    send(channel, data) {
        if (!ALLOWED_SEND_CHANNELS.has(channel)) {
            console.warn(`[preload] Blocked send to disallowed channel: ${channel}`);
            return;
        }
        ipcRenderer.send(channel, data);
    },

    /**
     * Subscribe to a one-way IPC event from the main process.
     * Returns an unsubscribe function.
     */
    on(channel, callback) {
        if (!ALLOWED_RECEIVE_CHANNELS.has(channel)) {
            throw new Error(`IPC channel not allowed: ${channel}`);
        }
        const listener = (_event, payload) => callback(payload);
        ipcRenderer.on(channel, listener);
        return () => ipcRenderer.removeListener(channel, listener);
    },

    /**
     * Get the per-launch auth token for backend API calls.
     */
    getAuthToken() {
        return readAuthToken();
    },
};

// contextBridge requires contextIsolation:true. Until the renderer is migrated
// away from CommonJS require() (needs a bundler), we fall back to a direct
// window assignment so the preload's IPC allowlist is at least live code.
if (process.contextIsolated) {
    contextBridge.exposeInMainWorld('electronAPI', electronAPI);
} else {
    window.electronAPI = electronAPI;
}
