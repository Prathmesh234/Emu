// services/api.js — HTTP API calls to backend

const BACKEND_URL = 'http://127.0.0.1:8000';

async function createSession() {
    const res = await fetch(`${BACKEND_URL}/agent/session`, { method: 'POST' });
    if (!res.ok) {
        throw new Error(`Session creation failed: ${res.status} ${res.statusText}`);
    }
    const data = await res.json();
    if (!data.session_id) {
        throw new Error('Session response missing session_id');
    }
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

async function notifyActionComplete({ sessionId, ipcChannel, success, error, output }) {
    return fetch(`${BACKEND_URL}/action/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: sessionId,
            ipc_channel: ipcChannel,
            success,
            error: error || null,
            output: output || null,
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

async function compactContext(sessionId) {
    const res = await fetch(`${BACKEND_URL}/agent/compact`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId }),
    });
    return res.json();
}

module.exports = { BACKEND_URL, createSession, postStep, notifyActionComplete, stopAgent, compactContext };
