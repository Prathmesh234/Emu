// App - Main entry point

const { ipcRenderer } = require('electron');
const { Message, ChatInput, StepCard, DoneCard, ErrorCard } = require('./components');
const { captureScreenshot, fullCapture, navigateMouse, leftClick, rightClick, leftClickOpen, scroll } = require('./actions');
const { dispatchAction } = require('./actions/actionProxy');

// Config
const BACKEND_URL = 'http://localhost:8000';
const WS_URL      = 'ws://localhost:8000';

// State
let chats = [];
let currentChatId = null;
let isGenerating = false;
let isSidePanel = false;
let sessionId = null;
let ws = null;
let currentAssistantEl = null;
let currentChat = null;

// DOM refs
let app, chatWrapper, chatContainer, chatInput, expandBtn;

// Helper to manage generating state and button tooltip
function setGenerating(generating) {
    isGenerating = generating;
    if (generating) {
        chatInput.sendBtn.disabled = true;
        chatInput.setTooltip('Messages can only be sent once agent completes processing');
    } else {
        chatInput.sendBtn.disabled = !chatInput.textarea.value.trim();
        chatInput.setTooltip('');
    }
}

function init() {
    app = document.getElementById('app');

    // Main content
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

    header.appendChild(h1);
    header.appendChild(headerActions);
    main.appendChild(header);

    chatContainer = document.createElement('div');
    chatContainer.className = 'chat-container';
    chatWrapper = document.createElement('div');
    chatWrapper.className = 'chat-wrapper';
    chatContainer.appendChild(chatWrapper);
    main.appendChild(chatContainer);

    // Input
    chatInput = ChatInput(sendMessage);
    main.appendChild(chatInput.element);

    app.appendChild(main);

    // Keyboard shortcuts
    document.onkeydown = (e) => {
        if (e.ctrlKey && e.shiftKey && e.key === 'N') {
            e.preventDefault();
            newChat();
        }
        if (e.key === 'Escape' && isSidePanel) {
            toggleWindow();
        }
    };

    newChat();
    chatInput.textarea.focus();
    initSession();
}

async function toggleWindow() {
    if (isSidePanel) {
        await ipcRenderer.invoke('window:centered');
        isSidePanel = false;
        expandBtn.style.display = 'none';
    } else {
        await ipcRenderer.invoke('window:side-panel');
        isSidePanel = true;
        expandBtn.style.display = 'block';
    }
}

async function moveToSidePanel() {
    if (!isSidePanel) {
        await ipcRenderer.invoke('window:side-panel');
        isSidePanel = true;
        expandBtn.style.display = 'block';
    }
}

function newChat() {
    const id = 'chat-' + Date.now();
    chats.unshift({ id, preview: 'New conversation', messages: [] });
    selectChat(id);
}

function selectChat(id) {
    currentChatId = id;
    const chat = chats.find(c => c.id === id);

    chatWrapper.innerHTML = '';

    if (chat && chat.messages.length > 0) {
        chat.messages.forEach((msg, i) => addMessage(msg.role, msg.content, i));
    } else {
        showEmpty();
    }

    chatInput.textarea.focus();
}

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
        if (isGenerating) return;
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

async function sendMessage() {
    const text = chatInput.textarea.value.trim();
    if (!text || isGenerating) return;

    const chat = chats.find(c => c.id === currentChatId);
    if (!chat) return;

    // Add user message
    chat.messages.push({ role: 'user', content: text });
    addMessage('user', text, chat.messages.length - 1);

    // Update preview
    if (chat.preview === 'New conversation') {
        chat.preview = text.slice(0, 30) + (text.length > 30 ? '...' : '');
    }

    // Clear input
    chatInput.textarea.value = '';
    chatInput.textarea.style.height = 'auto';
    chatInput.sendBtn.disabled = true;

    // Wait for the session to be initialised before hitting the backend
    if (!sessionId) {
        showStatus('Connecting to backend...');
        await new Promise(resolve => {
            const check = setInterval(() => {
                if (sessionId) { clearInterval(check); resolve(); }
            }, 100);
        });
        removeStatus();
    }

    // Move window to side panel
    await moveToSidePanel();

    // Full capture is a debug command — handled inline, not sent to agent
    if (/\bfull[-\s]?capture\b/i.test(text)) {
        showStatus('Full capture (panel excluded)...');
        const result = await fullCapture();
        removeStatus();
        const msg = result.success
            ? `Full capture saved: ${result.filename} (${result.width}\u00d7${result.height})`
            : `Full capture failed: ${result.error}`;
        chat.messages.push({ role: 'assistant', content: msg });
        addMessage('assistant', msg, chat.messages.length - 1);
        return;
    }

    // Capture screenshot and forward to agent
    showStatus('Capturing screen...');
    const screenshot = await captureScreenshot();
    if (!screenshot.success) {
        updateStatus('Screenshot failed: ' + (screenshot.error || 'unknown error'));
        await sleep(1000);
    }
    removeStatus();

    await respond(chat, screenshot.success ? screenshot.base64 : null);
}

async function respond(chat, base64Screenshot = null) {
    setGenerating(true);

    const lastUserMsg = [...chat.messages].reverse().find(m => m.role === 'user')?.content || '';

    chat.messages.push({ role: 'assistant', content: '' });
    const contentEl = addMessage('assistant', '', chat.messages.length - 1);
    contentEl.innerHTML = '<span class="typing"></span>';

    // Track which element and chat the WS messages should update
    currentAssistantEl = contentEl;
    currentChat = chat;

    try {
        await fetch(`${BACKEND_URL}/agent/step`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id:        sessionId,
                user_message:      lastUserMsg,
                base64_screenshot: base64Screenshot || '',
                previous_messages: chat.messages
                    .slice(0, -1)   // exclude the empty assistant placeholder
                    .map(m => ({ role: m.role, content: m.content }))
            })
        });
    } catch (err) {
        contentEl.textContent = `Backend unreachable: ${err.message}`;
        setGenerating(false);
    }
}

function editMessage(index) {
    const chat = chats.find(c => c.id === currentChatId);
    if (!chat) return;

    const content = chat.messages[index].content;
    chat.messages = chat.messages.slice(0, index);

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
    const chat = chats.find(c => c.id === currentChatId);
    if (!chat) return;

    chat.messages = chat.messages.slice(0, index);
    const msgs = chatWrapper.querySelectorAll('.message');
    for (let i = index; i < msgs.length; i++) msgs[i].remove();

    showStatus('Capturing screen...');
    const screenshot = await captureScreenshot();
    updateStatus(screenshot.success ? 'Screen captured' : 'Screenshot failed');
    await sleep(500);
    removeStatus();

    await respond(chat, screenshot.success ? screenshot.base64 : null);
}

function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
}

// ── Backend + WebSocket ──────────────────────────────────────────────────────────────

async function initSession() {
    try {
        const res = await fetch(`${BACKEND_URL}/agent/session`, { method: 'POST' });
        const data = await res.json();
        sessionId = data.session_id;
        initWebSocket(sessionId);
        console.log('[session] created', sessionId);
    } catch (err) {
        console.warn('[session] backend unreachable:', err.message);
        console.log('[session] retrying in 2s...');
        setTimeout(initSession, 2000);
    }
}

function initWebSocket(sid) {
    ws = new WebSocket(`${WS_URL}/ws/${sid}`);
    ws.onopen  = () => console.log('[ws] connected');
    ws.onclose = () => {
        console.log('[ws] closed — reconnecting in 2s');
        setTimeout(() => initWebSocket(sid), 2000);
    };
    ws.onerror = (e) => console.warn('[ws] error', e);
    ws.onmessage = (event) => {
        try { handleWsMessage(JSON.parse(event.data)); }
        catch (e) { console.warn('[ws] bad message:', event.data); }
    };
}

async function handleWsMessage(data) {
    switch (data.type) {
        case 'status':
            showStatus(data.message);
            break;

        case 'step': {
            // Full step payload: { screenshot, reasoning, action, done, confidence, final_message }
            removeStatus();

            const stepCard = StepCard(data);
            if (currentAssistantEl) {
                currentAssistantEl.innerHTML = '';
                currentAssistantEl.appendChild(stepCard.element);
            }

            // Store in chat history
            if (currentChat) {
                currentChat.messages[currentChat.messages.length - 1].content = data.reasoning || data.final_message || '';
                currentChat.messages[currentChat.messages.length - 1].stepData = data;
            }

            chatContainer.scrollTop = chatContainer.scrollHeight;

            // If not done, execute the action
            if (!data.done && data.action) {
                await executeAction(data.action, stepCard.element);
            }

            // Allow follow-up messages after step is received
            setGenerating(false);
            break;
        }

        case 'done': {
            removeStatus();
            const msg = data.message || 'Task complete.';
            if (currentAssistantEl) {
                const doneCard = DoneCard(msg);
                currentAssistantEl.innerHTML = '';
                currentAssistantEl.appendChild(doneCard.element);
            }
            if (currentChat) {
                currentChat.messages[currentChat.messages.length - 1].content = msg;
            }
            setGenerating(false);
            chatContainer.scrollTop = chatContainer.scrollHeight;
            break;
        }

        case 'error':
            removeStatus();
            if (currentAssistantEl) {
                const errCard = ErrorCard(data.message);
                currentAssistantEl.innerHTML = '';
                currentAssistantEl.appendChild(errCard.element);
            }
            setGenerating(false);
            break;
    }
}

// ── Action execution ────────────────────────────────────────────────────────────────

async function executeAction(action, stepEl) {
    const result = await dispatchAction(action);

    // Update the status badge inside the step card
    const badge = stepEl.querySelector('#step-action-status');
    if (badge) {
        if (result.success) {
            badge.className = 'step-action-status success';
            badge.textContent = '✓ Done';
        } else {
            badge.className = 'step-action-status failed';
            badge.textContent = `✗ Failed: ${result.error || 'unknown'}`;
        }
    }

    // Notify backend
    try {
        await fetch(`${BACKEND_URL}/action/complete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: sessionId,
                ipc_channel: result.ipc || action.type,
                success: result.success,
                error: result.error || null
            })
        });
    } catch (e) { /* non-critical */ }
}

async function typeText(el, text) {
    let out = '';
    for (const ch of text) {
        out += ch;
        el.textContent = out;
        chatContainer.scrollTop = chatContainer.scrollHeight;
        await sleep(15);
    }
}

init();
