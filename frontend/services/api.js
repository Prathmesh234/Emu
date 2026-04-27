// services/api.js — HTTP API calls to backend

const fs = require('fs');
const { authTokenPath } = require('../emu/root');

const BACKEND_URL = 'http://127.0.0.1:8000';

// Auth token path resolves via EMU_ROOT so it works in both source-checkout
// and packaged-DMG layouts.
const TOKEN_PATH = authTokenPath();

function getToken() {
    try {
        return fs.readFileSync(TOKEN_PATH, 'utf8').trim();
    } catch {
        return '';
    }
}

function authHeaders(extra = {}) {
    return { 'Content-Type': 'application/json', 'X-Emu-Token': getToken(), ...extra };
}

async function createSession() {
    const res = await fetch(`${BACKEND_URL}/agent/session`, {
        method: 'POST',
        headers: authHeaders(),
    });
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
        headers: authHeaders(),
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
        headers: authHeaders(),
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
        headers: authHeaders(),
        body: JSON.stringify({ session_id: sessionId }),
    });
}

async function compactContext(sessionId) {
    const res = await fetch(`${BACKEND_URL}/agent/compact`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ session_id: sessionId }),
    });
    return res.json();
}

async function fetchSessionHistory() {
    const res = await fetch(`${BACKEND_URL}/sessions/history`, {
        headers: authHeaders(),
    });
    if (!res.ok) return [];
    const data = await res.json();
    return data.sessions || [];
}

async function fetchSessionMessages(sessionId) {
    const res = await fetch(`${BACKEND_URL}/sessions/${encodeURIComponent(sessionId)}/messages`, {
        headers: authHeaders(),
    });
    if (!res.ok) return [];
    const data = await res.json();
    return data.messages || [];
}

async function continueSession(previousSessionId) {
    const res = await fetch(`${BACKEND_URL}/agent/session/continue`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ previous_session_id: previousSessionId }),
    });
    if (!res.ok) throw new Error(`Continue session failed: ${res.status} ${res.statusText}`);
    const data = await res.json();
    if (!data.session_id) throw new Error('Continue session response missing session_id');
    return data.session_id;
}

async function getProviderSettings() {
    const res = await fetch(`${BACKEND_URL}/settings/provider`, {
        headers: authHeaders(),
    });
    if (!res.ok) throw new Error(`Failed to get provider settings: ${res.status}`);
    return res.json();
}

async function saveProviderSettings({ provider, model, apiKey }) {
    const res = await fetch(`${BACKEND_URL}/settings/provider`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ provider, model, api_key: apiKey }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Failed to save provider settings: ${res.status}`);
    return data;
}

module.exports = { BACKEND_URL, createSession, continueSession, postStep, notifyActionComplete, stopAgent, compactContext, fetchSessionHistory, fetchSessionMessages, getProviderSettings, saveProviderSettings };
