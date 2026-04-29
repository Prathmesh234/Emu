// actions/executor.js — Execute a single agent action and notify backend.
//
// Extracted from pages/Chat.js. Behavior is identical:
//   1. Dispatch action via the IPC proxy (branched by agent mode).
//   2. Update the step card's badge (resolved / failed).
//   3. POST /action/complete to the backend (best-effort).

const { dispatchAction: dispatchRemote } = require('./actionProxy');
const { dispatchAction: dispatchCoworker } = require('../cua-driver-commands/actionProxy');
const store = require('../state/store');
const api = require('../services/api');

async function executeAction(action, stepEl) {
    // Branch on agent mode: coworker uses emu-cua-driver MCP, remote uses cliclick/CGEvent
    const dispatch = store.state.agentMode === 'coworker'
        ? dispatchCoworker
        : dispatchRemote;

    console.log(`[executeAction] mode=${store.state.agentMode} dispatching ${action.type}`);
    const result = await dispatch(action);
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
