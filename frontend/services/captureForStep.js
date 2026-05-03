// services/captureForStep.js — Per-step screenshot for the agent loop.
//
// Remote mode uses the desktop capture path. Coworker mode can narrow the
// capture to the active target window once the backend has surfaced a
// (pid, window_id) target for the session.

const { ipcRenderer } = require('electron');
const { captureScreenshot } = require('../actions');
const store = require('../state/store');

/**
 * Capture a screenshot for the next /agent/step turn.
 * Returns the same shape as remote captureScreenshot(): {success, base64, error}.
 */
async function captureForStep() {
    if (store.state.agentMode === 'coworker') {
        const target = store.state.coworkerTarget;
        if (target && target.pid != null && target.window_id != null) {
            try {
                const result = await invokeIpc('emu-cua:screenshot', {
                    window_id: target.window_id,
                    format: 'jpeg',
                    quality: 80,
                });
                if (result?.success && result.base64) {
                    return {
                        success: true,
                        base64: result.base64,
                        output: result.output || null,
                    };
                }
                console.warn('[captureForStep] coworker window capture failed; falling back to desktop capture:', result?.error || result?.output || 'unknown');
            } catch (err) {
                console.warn('[captureForStep] coworker window capture errored; falling back to desktop capture:', err?.message || err);
            }
        }
    }
    return captureScreenshot();
}

function invokeIpc(channel, payload) {
    if (window.electronAPI && typeof window.electronAPI.invoke === 'function') {
        return window.electronAPI.invoke(channel, payload);
    }
    return ipcRenderer.invoke(channel, payload);
}

module.exports = { captureForStep };
