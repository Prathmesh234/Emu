// services/captureForStep.js — Per-step screenshot for the remote agent loop.
//
// Coworker mode gets driver screenshots directly from backend cua_* tool
// results, so this renderer helper stays scoped to desktop capture.

const { captureScreenshot } = require('../actions');

/**
 * Capture a screenshot for the next /agent/step turn.
 * Returns the same shape as remote captureScreenshot(): {success, base64, error}.
 */
async function captureForStep() {
    return captureScreenshot();
}

module.exports = { captureForStep };
