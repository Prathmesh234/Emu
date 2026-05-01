// services/captureForStep.js — Per-step screenshot for the agent loop.
//
// PLAN §6.2/§6.3 (coworker mode): when agent_mode === 'coworker' AND we
// know the active (pid, window_id), pull a target-window screenshot via
// emu-cua-driver (`emu-cua:screenshot`). Otherwise fall through to the
// regular desktop screenshot path used in remote mode.
//
// Robustness: if the coworker capture fails for any reason (driver down,
// stale window, permission denied), log it and fall back to the remote
// path once so a transient driver issue never wedges the loop.

const { ipcRenderer } = require('electron');
const store = require('../state/store');
const { captureScreenshot } = require('../actions');

async function _coworkerCapture(target) {
    // ScreenshotTool.swift inputSchema: {format?, quality?, window_id?} with
    // additionalProperties:false. Pass only window_id; pid is not used by
    // the screenshot tool (it captures by CGWindowID).
    const result = await ipcRenderer.invoke('emu-cua:screenshot', {
        window_id: target.window_id,
    });
    if (!result?.success || !result.base64) {
        return {
            success: false,
            error: result?.error || 'emu-cua-driver returned no image',
        };
    }
    return { success: true, base64: result.base64, source: 'coworker' };
}

/**
 * Capture a screenshot for the next /agent/step turn.
 * Returns the same shape as remote captureScreenshot(): {success, base64, error}.
 */
async function captureForStep() {
    const target = store.state.coworkerTarget;
    const isCoworker = store.state.agentMode === 'coworker';

    if (isCoworker && target && target.pid && target.window_id) {
        try {
            const result = await _coworkerCapture(target);
            if (result.success) return result;
            console.warn(
                `[captureForStep] coworker capture failed (${result.error}); ` +
                `falling back to remote desktopCapturer`,
            );
        } catch (err) {
            console.warn(
                `[captureForStep] coworker capture threw (${err.message}); ` +
                `falling back to remote desktopCapturer`,
            );
        }
    }

    return captureScreenshot();
}

module.exports = { captureForStep };
