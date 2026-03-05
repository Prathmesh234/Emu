// services/api.js — HTTP API calls to backend

const BACKEND_URL = 'http://localhost:8000';

async function createSession() {
    const res = await fetch(`${BACKEND_URL}/agent/session`, { method: 'POST' });
    const data = await res.json();
    return data.session_id;
}

async function postStep({ sessionId, userMessage, base64Screenshot }) {
    return fetch(`${BACKEND_URL}/agent/step`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id:        sessionId,
            user_message:      userMessage || '',
            base64_screenshot: base64Screenshot || '',
        }),
    });
}

async function notifyActionComplete({ sessionId, ipcChannel, success, error }) {
    return fetch(`${BACKEND_URL}/action/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: sessionId,
            ipc_channel: ipcChannel,
            success,
            error: error || null,
        }),
    });
}

async function stopAgent(sessionId) {
    return fetch(`${BACKEND_URL}/agent/stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId }),
    });
}

module.exports = { BACKEND_URL, createSession, postStep, notifyActionComplete, stopAgent };
