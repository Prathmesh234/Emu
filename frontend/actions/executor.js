// actions/executor.js — Execute a single agent action and notify backend.
//
// Extracted from pages/Chat.js. Behavior is identical:
//   1. Dispatch remote-mode actions via the IPC proxy.
//   2. Update the step card's badge (resolved / failed).
//   3. POST /action/complete to the backend (best-effort).

const { dispatchAction: dispatchRemote } = require('./actionProxy');
const store = require('../state/store');
const api = require('../services/api');

async function executeAction(action, stepEl) {
    console.log(`[executeAction] mode=${store.state.agentMode} dispatching ${action.type}`);
    const result = store.state.agentMode === 'coworker' && action.type !== 'done'
        ? {
            success: false,
            error: 'Coworker mode actions must use backend cua_* tools; only done is dispatched by the renderer.',
        }
        : await dispatchRemote(action);
    console.log(`[executeAction] result:`, result);

    // Mark trace as resolved (hides the blinking caret).
    // Success case: remove the badge entirely for a clean prose-style trace.
    // Failure case: show a quiet "failed" note so the user can see what broke.
    stepEl.classList.add('resolved');
    const badge = stepEl.querySelector('.step-action-status');
    if (badge) {
        if (result.success) {
            badge.remove();
        } else {
            badge.className = 'step-action-status failed trace-status';
            badge.textContent = 'failed';
        }
    }

    try {
        await api.notifyActionComplete({
            sessionId: store.state.sessionId,
            ipcChannel: result.ipc || action.type,
            success: result.success,
            error: result.error,
            output: result.output || null,
        });
    } catch (_) { /* non-critical */ }
}

module.exports = { executeAction };
