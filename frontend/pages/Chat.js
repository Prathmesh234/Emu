// pages/Chat.js — Chat page component
//
// Owns the chat UI: message list, input, status bar,
// WebSocket message handling, and action execution.

const { ipcRenderer } = require('electron');
const { Message, ChatInput, StepCard, DoneCard, ErrorCard } = require('../components');
const { captureScreenshot, fullCapture } = require('../actions');
const { dispatchAction } = require('../actions/actionProxy');
const store = require('../state/store');
const api = require('../services/api');
const { initWebSocket, setMessageHandler } = require('../services/websocket');

// ── DOM refs (populated in mount) ────────────────────────────────────────

let chatContainer, chatWrapper, chatInput, expandBtn;

// ── Helpers ──────────────────────────────────────────────────────────────

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function syncGeneratingUI(generating) {
    store.setGenerating(generating);
    if (generating) {
        chatInput.sendBtn.disabled = true;
        chatInput.setTooltip('Messages can only be sent once agent completes processing');
    } else {
        chatInput.sendBtn.disabled = !chatInput.textarea.value.trim();
        chatInput.setTooltip('');
    }
}

// ── Window helpers ───────────────────────────────────────────────────────

async function toggleWindow() {
    const { state } = store;
    if (state.isSidePanel) {
        await ipcRenderer.invoke('window:centered');
        store.setSidePanel(false);
        expandBtn.style.display = 'none';
    } else {
        await ipcRenderer.invoke('window:side-panel');
        store.setSidePanel(true);
        expandBtn.style.display = 'block';
    }
}

async function moveToSidePanel() {
    if (!store.state.isSidePanel) {
        await ipcRenderer.invoke('window:side-panel');
        store.setSidePanel(true);
        expandBtn.style.display = 'block';
    }
}

// ── Rendering ────────────────────────────────────────────────────────────

function showEmpty() {
    const empty = document.createElement('div');
    empty.className = 'empty-state';

    const h2 = document.createElement('h2');
    h2.textContent = 'Welcome';
    const p = document.createElement('p');
    p.textContent = 'Describe a task to automate';

    empty.appendChild(h2);
    empty.appendChild(p);
    chatWrapper.appendChild(empty);
}

function addMessage(role, content, index) {
    const empty = chatWrapper.querySelector('.empty-state');
    if (empty) empty.remove();

    const msg = Message(role, content, () => {
        if (store.state.isGenerating) return;
        if (role === 'user') editMessage(index);
        else regenerate(index);
    });

    chatWrapper.appendChild(msg.element);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    return msg.content;
}

function showStatus(text) {
    removeStatus();
    const indicator = document.createElement('div');
    indicator.className = 'status-indicator';
    indicator.id = 'status-indicator';

    const dot = document.createElement('span');
    dot.className = 'dot';
    indicator.appendChild(dot);

    const span = document.createElement('span');
    span.textContent = text;
    indicator.appendChild(span);

    chatWrapper.appendChild(indicator);
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function updateStatus(text) {
    const indicator = document.getElementById('status-indicator');
    if (indicator) {
        const span = indicator.querySelector('span:last-child');
        if (span) span.textContent = text;
    }
}

function removeStatus() {
    const indicator = document.getElementById('status-indicator');
    if (indicator) indicator.remove();
}

// ── Chat selection ───────────────────────────────────────────────────────

function selectChat(id) {
    store.setCurrentChat(id);
    const chat = store.getChat(id);

    chatWrapper.innerHTML = '';

    if (chat && chat.messages.length > 0) {
        chat.messages.forEach((msg, i) => addMessage(msg.role, msg.content, i));
    } else {
        showEmpty();
    }

    chatInput.textarea.focus();
}

function newChat() {
    const id = store.createChat();
    selectChat(id);
}

// ── Message actions ──────────────────────────────────────────────────────

function editMessage(index) {
    const chat = store.getCurrentChat();
    if (!chat) return;

    const content = chat.messages[index].content;
    store.truncateMessages(chat.id, index);

    const msgs = chatWrapper.querySelectorAll('.message');
    for (let i = index; i < msgs.length; i++) msgs[i].remove();

    if (chat.messages.length === 0) showEmpty();

    chatInput.textarea.value = content;
    chatInput.textarea.style.height = 'auto';
    chatInput.textarea.style.height = Math.min(chatInput.textarea.scrollHeight, 150) + 'px';
    chatInput.sendBtn.disabled = false;
    chatInput.textarea.focus();
}

async function regenerate(index) {
    const chat = store.getCurrentChat();
    if (!chat) return;

    store.truncateMessages(chat.id, index);
    const msgs = chatWrapper.querySelectorAll('.message');
    for (let i = index; i < msgs.length; i++) msgs[i].remove();

    showStatus('Capturing screen...');
    const screenshot = await captureScreenshot();
    updateStatus(screenshot.success ? 'Screen captured' : 'Screenshot failed');
    await sleep(500);
    removeStatus();

    await respond(chat, screenshot.success ? screenshot.base64 : null);
}

// ── Send / respond ───────────────────────────────────────────────────────

async function sendMessage() {
    const text = chatInput.textarea.value.trim();
    if (!text || store.state.isGenerating) return;

    const chat = store.getCurrentChat();
    if (!chat) return;

    // Add user message
    store.pushMessage(chat.id, { role: 'user', content: text });
    addMessage('user', text, chat.messages.length - 1);
    store.updateChatPreview(chat.id, text);

    // Clear input
    chatInput.textarea.value = '';
    chatInput.textarea.style.height = 'auto';
    chatInput.sendBtn.disabled = true;

    // Wait for session
    if (!store.state.sessionId) {
        showStatus('Connecting to backend...');
        await new Promise(resolve => {
            const check = setInterval(() => {
                if (store.state.sessionId) { clearInterval(check); resolve(); }
            }, 100);
        });
        removeStatus();
    }

    await moveToSidePanel();

    // Debug: full-capture
    if (/\bfull[-\s]?capture\b/i.test(text)) {
        showStatus('Full capture (panel excluded)...');
        const result = await fullCapture();
        removeStatus();
        const msg = result.success
            ? `Full capture saved: ${result.filename} (${result.width}\u00d7${result.height})`
            : `Full capture failed: ${result.error}`;
        store.pushMessage(chat.id, { role: 'assistant', content: msg });
        addMessage('assistant', msg, chat.messages.length - 1);
        return;
    }

    // Send text only — model will request a screenshot if it needs one
    await respond(chat);
}

async function respond(chat, base64Screenshot = null) {
    syncGeneratingUI(true);

    const lastUserMsg = store.getLastUserMessage(chat);

    store.pushMessage(chat.id, { role: 'assistant', content: '', stepCount: 0 });
    const contentEl = addMessage('assistant', '', chat.messages.length - 1);
    contentEl.innerHTML = '<span class="typing"></span>';

    // Create a step container for sequential step cards
    const stepContainer = document.createElement('div');
    stepContainer.className = 'step-container';
    store.setAssistantEl(contentEl);
    store.state.stepContainer = stepContainer;
    store.state.stepCount = 0;

    try {
        await api.postStep({
            sessionId:        store.state.sessionId,
            userMessage:      base64Screenshot ? '' : lastUserMsg,
            base64Screenshot: base64Screenshot || '',
        });
    } catch (err) {
        contentEl.textContent = `Backend unreachable: ${err.message}`;
        syncGeneratingUI(false);
    }
}

/**
 * Continue the agent loop: capture screenshot and send to backend.
 * Called after the model requests a screenshot or after executing an action.
 */
async function continueLoop() {
    const chat = store.getCurrentChat();
    if (!chat) { console.warn('[continueLoop] no current chat'); return; }

    console.log('[continueLoop] capturing screenshot...');
    showStatus('Capturing screen...');
    const screenshot = await captureScreenshot();
    removeStatus();

    if (!screenshot.success) {
        console.error('[continueLoop] screenshot failed:', screenshot.error);
        showStatus('Screenshot failed: ' + (screenshot.error || 'unknown'));
        await sleep(1500);
        removeStatus();
        syncGeneratingUI(false);
        return;
    }

    console.log(`[continueLoop] screenshot OK (${Math.round(screenshot.base64.length / 1024)} KB) — posting to backend`);

    // Send screenshot to backend (no new assistant message bubble — reuse current)
    try {
        await api.postStep({
            sessionId:        store.state.sessionId,
            userMessage:      '',
            base64Screenshot: screenshot.base64,
        });
        console.log('[continueLoop] POST completed');
    } catch (err) {
        console.error('[continueLoop] POST failed:', err);
        showStatus(`Backend error: ${err.message}`);
        await sleep(1500);
        removeStatus();
        syncGeneratingUI(false);
    }
}

// ── WebSocket handler ────────────────────────────────────────────────────

async function handleWsMessage(data) {
    const { state } = store;

    switch (data.type) {
        case 'status':
            showStatus(data.message);
            break;

        case 'step': {
            removeStatus();

            // Increment step counter
            store.state.stepCount = (store.state.stepCount || 0) + 1;
            const stepNum = store.state.stepCount;

            const stepCard = StepCard(data, stepNum);

            if (state.currentAssistantEl) {
                // Remove typing indicator on first step
                const typing = state.currentAssistantEl.querySelector('.typing');
                if (typing) typing.remove();

                // Ensure step container exists
                let container = state.stepContainer;
                if (container && !container.parentNode) {
                    state.currentAssistantEl.appendChild(container);
                }
                if (container) {
                    container.appendChild(stepCard.element);
                } else {
                    state.currentAssistantEl.appendChild(stepCard.element);
                }
            }

            if (state.currentChat) {
                const last = state.currentChat.messages[state.currentChat.messages.length - 1];
                last.content = data.reasoning || data.final_message || '';
                last.stepData = data;
                last.stepCount = stepNum;
            }

            chatContainer.scrollTop = chatContainer.scrollHeight;

            if (data.done) {
                syncGeneratingUI(false);
                break;
            }

            if (data.action) {
                try {
                    if (data.action.type === 'screenshot') {
                        console.log('[step] model requested screenshot — calling continueLoop');
                        await continueLoop();
                    } else {
                        console.log(`[step] executing action: ${data.action.type}`);
                        await executeAction(data.action, stepCard.element);
                        console.log('[step] action executed — sleeping 500ms');
                        await sleep(500);
                        console.log('[step] calling continueLoop');
                        await continueLoop();
                        console.log('[step] continueLoop done');
                    }
                } catch (err) {
                    console.error('[step] loop error:', err);
                    showStatus(`Agent error: ${err.message}`);
                    await sleep(2000);
                    removeStatus();
                    syncGeneratingUI(false);
                }
            } else {
                syncGeneratingUI(false);
            }
            break;
        }

        case 'done': {
            removeStatus();
            const msg = data.message || 'Task complete.';
            if (state.currentAssistantEl) {
                const typing = state.currentAssistantEl.querySelector('.typing');
                if (typing) typing.remove();

                const doneCard = DoneCard(msg);
                let container = state.stepContainer;
                if (container && container.parentNode) {
                    container.appendChild(doneCard.element);
                } else {
                    state.currentAssistantEl.appendChild(doneCard.element);
                }
            }
            if (state.currentChat) {
                state.currentChat.messages[state.currentChat.messages.length - 1].content = msg;
            }
            syncGeneratingUI(false);
            chatContainer.scrollTop = chatContainer.scrollHeight;
            break;
        }

        case 'error':
            removeStatus();
            if (state.currentAssistantEl) {
                const typing = state.currentAssistantEl.querySelector('.typing');
                if (typing) typing.remove();

                const errCard = ErrorCard(data.message);
                let container = state.stepContainer;
                if (container && container.parentNode) {
                    container.appendChild(errCard.element);
                } else {
                    state.currentAssistantEl.appendChild(errCard.element);
                }
            }
            syncGeneratingUI(false);
            break;
    }
}

// ── Action execution ─────────────────────────────────────────────────────

async function executeAction(action, stepEl) {
    console.log(`[executeAction] dispatching ${action.type}`);
    const result = await dispatchAction(action);
    console.log(`[executeAction] result:`, result);

    const badge = stepEl.querySelector('.step-action-status');
    if (badge) {
        if (result.success) {
            badge.className = 'step-action-status success';
            badge.textContent = '✓ Done';
        } else {
            badge.className = 'step-action-status failed';
            badge.textContent = `✗ Failed: ${result.error || 'unknown'}`;
        }
    }

    try {
        await api.notifyActionComplete({
            sessionId: store.state.sessionId,
            ipcChannel: result.ipc || action.type,
            success: result.success,
            error: result.error,
        });
    } catch (_) { /* non-critical */ }
}

// ── Session bootstrap ────────────────────────────────────────────────────

async function initSession() {
    try {
        const id = await api.createSession();
        store.setSession(id);
        initWebSocket(id);
        console.log('[session] created', id);
    } catch (err) {
        console.warn('[session] backend unreachable:', err.message);
        console.log('[session] retrying in 2s...');
        setTimeout(initSession, 2000);
    }
}

// ── Mount ────────────────────────────────────────────────────────────────

function mount(appEl) {
    // Wire up WS handler
    setMessageHandler(handleWsMessage);

    // Main wrapper
    const main = document.createElement('div');
    main.className = 'main';

    // Header
    const header = document.createElement('div');
    header.className = 'header';

    const h1 = document.createElement('h1');
    h1.textContent = 'Emulation Agent';

    const headerActions = document.createElement('div');
    headerActions.className = 'header-actions';

    expandBtn = document.createElement('button');
    expandBtn.className = 'expand-btn';
    expandBtn.textContent = 'Expand';
    expandBtn.style.display = 'none';
    expandBtn.onclick = toggleWindow;
    headerActions.appendChild(expandBtn);

    const closeBtn = document.createElement('button');
    closeBtn.className = 'close-btn';
    closeBtn.textContent = '✕';
    closeBtn.onclick = () => window.close();
    headerActions.appendChild(closeBtn);

    header.appendChild(h1);
    header.appendChild(headerActions);
    main.appendChild(header);

    // Chat area
    chatContainer = document.createElement('div');
    chatContainer.className = 'chat-container';
    chatWrapper = document.createElement('div');
    chatWrapper.className = 'chat-wrapper';
    chatContainer.appendChild(chatWrapper);
    main.appendChild(chatContainer);

    // Input
    chatInput = ChatInput(sendMessage);
    main.appendChild(chatInput.element);

    appEl.appendChild(main);

    // Keyboard shortcuts
    document.onkeydown = (e) => {
        if (e.ctrlKey && e.shiftKey && e.key === 'N') {
            e.preventDefault();
            newChat();
        }
        if (e.key === 'Escape' && store.state.isSidePanel) {
            toggleWindow();
        }
    };

    // Boot
    newChat();
    chatInput.textarea.focus();
    initSession();
}

module.exports = { mount, newChat, selectChat };
