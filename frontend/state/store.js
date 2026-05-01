// state/store.js — Centralized state management
//
// Single source of truth for app state.
// Components read from store and call mutations to update.

let _savedDarkMode = false;
try { _savedDarkMode = localStorage.getItem('emu-dark-mode') === '1'; } catch(e) {}

const AGENT_MODES = new Set(['coworker', 'remote']);
let _savedAgentMode = 'coworker';
try {
    const saved = localStorage.getItem('emu-agent-mode');
    if (AGENT_MODES.has(saved)) _savedAgentMode = saved;
} catch(e) {}

const state = {
    chats: [],
    currentChatId: null,
    isGenerating: false,
    isStopped: false,
    isSidePanel: false,
    sessionId: null,
    ws: null,
    dangerousMode: true,
    darkMode: _savedDarkMode,
    agentMode: _savedAgentMode,
    // Active coworker target (PLAN §6.5). Populated from each /agent/step
    // reply when agent_mode==='coworker'; consumed by captureForStep to
    // pull a target-window screenshot via emu-cua-driver instead of the
    // full desktop. null when unknown (no raise_app/launch_app yet).
    coworkerTarget: null,

    // Transient references (current render cycle)
    currentAssistantEl: null,
    currentChat: null,
};

// ── Getters ──────────────────────────────────────────────────────────────

function getChat(id) {
    return state.chats.find(c => c.id === (id || state.currentChatId));
}

function getCurrentChat() {
    return getChat(state.currentChatId);
}

function getLastUserMessage(chat) {
    const c = chat || getCurrentChat();
    if (!c) return '';
    return [...c.messages].reverse().find(m => m.role === 'user')?.content || '';
}

// ── Mutations ────────────────────────────────────────────────────────────

function createChat() {
    const id = 'chat-' + Date.now();
    state.chats.unshift({ id, preview: 'New conversation', messages: [] });
    state.currentChatId = id;
    return id;
}

function setCurrentChat(id) {
    state.currentChatId = id;
    state.currentChat = getChat(id);
}

function setGenerating(value) {
    state.isGenerating = value;
}

function setStopped(value) {
    state.isStopped = value;
}

function setSidePanel(value) {
    state.isSidePanel = value;
}

function setSession(id) {
    state.sessionId = id;
}

function setDangerousMode(value) {
    state.dangerousMode = value;
}

function setDarkMode(value) {
    state.darkMode = value;
    try { localStorage.setItem('emu-dark-mode', value ? '1' : '0'); } catch(e) {}
}

function setAgentMode(value) {
    if (!AGENT_MODES.has(value)) {
        throw new Error(`Invalid agent mode: ${value}`);
    }
    state.agentMode = value;
    try { localStorage.setItem('emu-agent-mode', value); } catch(e) {}
}

function setCoworkerTarget(target) {
    if (!target || target.pid == null || target.window_id == null) {
        state.coworkerTarget = null;
        return;
    }
    state.coworkerTarget = { pid: target.pid, window_id: target.window_id };
}

function setWebSocket(socket) {
    state.ws = socket;
}

function setAssistantEl(el) {
    state.currentAssistantEl = el;
    state.currentChat = getCurrentChat();
}

function pushMessage(chatId, message) {
    const chat = getChat(chatId);
    if (chat) chat.messages.push(message);
}

function updateChatPreview(chatId, text) {
    const chat = getChat(chatId);
    if (!chat || chat.preview !== 'New conversation') return;
    chat.preview = text.slice(0, 30) + (text.length > 30 ? '...' : '');
}

function truncateMessages(chatId, fromIndex) {
    const chat = getChat(chatId);
    if (chat) chat.messages = chat.messages.slice(0, fromIndex);
}

module.exports = {
    state,
    getChat,
    getCurrentChat,
    getLastUserMessage,
    createChat,
    setCurrentChat,
    setGenerating,
    setStopped,
    setSidePanel,
    setSession,
    setDangerousMode,
    setDarkMode,
    setAgentMode,
    setCoworkerTarget,
    setWebSocket,
    setAssistantEl,
    pushMessage,
    updateChatPreview,
    truncateMessages,
};
