// services/websocket.js — WebSocket connection management
//
// Messages are queued and processed one-at-a-time so that the async
// handler (executeAction → continueLoop) finishes before the next
// WS message is handled.  This prevents race conditions where two
// handlers manipulate the DOM and psProcess concurrently.

const store = require('../state/store');

const WS_URL = 'ws://172.23.104.4:8000';

let onMessageHandler = null;
let _closing = false;

// ── Serial message queue ──────────────────────────────────────────────
const _queue = [];
let _processing = false;

async function _processQueue() {
    if (_processing) return;        // another call is already draining
    _processing = true;

    while (_queue.length > 0) {
        const data = _queue.shift();
        try {
            if (onMessageHandler) await onMessageHandler(data);
        } catch (err) {
            console.error('[ws] handler error:', err);
        }
    }

    _processing = false;
}

// ── Public API ────────────────────────────────────────────────────────
function initWebSocket(sessionId) {
    const ws = new WebSocket(`${WS_URL}/ws/${sessionId}`);

    ws.onopen = () => console.log('[ws] connected');

    ws.onclose = () => {
        if (_closing) return;
        console.log('[ws] closed — reconnecting in 2s');
        setTimeout(() => initWebSocket(sessionId), 2000);
    };

    ws.onerror = (e) => console.warn('[ws] error', e);

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            _queue.push(data);
            _processQueue();          // fire-and-forget; queue serialises
        } catch (e) {
            console.warn('[ws] bad JSON:', event.data);
        }
    };

    store.setWebSocket(ws);
}

function setMessageHandler(handler) {
    onMessageHandler = handler;
}

function closeWebSocket() {
    _closing = true;
    const ws = store.state.ws;
    if (ws) {
        try { ws.close(); } catch (_) {}
    }
}

module.exports = { initWebSocket, setMessageHandler, closeWebSocket };
