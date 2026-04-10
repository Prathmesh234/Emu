// state/store.js — Centralized state management
//
// Single source of truth for app state.
// Components read from store and call mutations to update.

let _savedDarkMode = false;
try { _savedDarkMode = localStorage.getItem('emu-dark-mode') === '1'; } catch(e) {}

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
    setWebSocket,
    setAssistantEl,
    pushMessage,
    updateChatPreview,
    truncateMessages,
};
