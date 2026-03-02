// App - Main entry point

const { ipcRenderer } = require('electron');
const { Message, ChatInput } = require('./components');
const { captureScreenshot, fullCapture, navigateMouse, leftClick, rightClick, leftClickOpen, scroll } = require('./actions');

// Config
// const API_URL = 'http://localhost:8000'; // Reserved for future direct backend calls

// State
let chats = [];
let currentChatId = null;
let isGenerating = false;
let isSidePanel = false;

// DOM refs
let app, chatWrapper, chatContainer, chatInput, expandBtn;

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

    // Move window to side panel
    await moveToSidePanel();

    // Skip default screenshot when the user wants a full capture (it takes its own)
    if (!/\bfull[-\s]?capture\b/i.test(text)) {
        showStatus('Capturing screen...');
        const result = await captureScreenshot();

        if (result.success) {
            updateStatus('Screen captured');
            await sleep(500);
        } else {
            updateStatus('Screenshot failed: ' + (result.error || 'Unknown error'));
            await sleep(1000);
        }

        removeStatus();
    }

    // Generate response
    await respond(chat);
}

async function respond(chat) {
    isGenerating = true;
    chatInput.sendBtn.disabled = true;

    const lastUserMsg = [...chat.messages].reverse().find(m => m.role === 'user')?.content || '';

    chat.messages.push({ role: 'assistant', content: '' });
    const contentEl = addMessage('assistant', '', chat.messages.length - 1);
    contentEl.innerHTML = '<span class="typing"></span>';

    let response;

    if (/\bfull[-\s]?capture\b/i.test(lastUserMsg)) {
        showStatus('Full capture (panel excluded)...');
        const result = await fullCapture();
        removeStatus();

        response = result.success
            ? `Full capture saved: ${result.filename} (${result.width}×${result.height})`
            : `Full capture failed: ${result.error}`;

    } else if (/\bscroll\b/i.test(lastUserMsg)) {
        const x = Math.floor(Math.random() * 1200) + 100;
        const y = Math.floor(Math.random() * 600) + 100;
        const direction = /\bup\b/i.test(lastUserMsg) ? 'up' : 'down';
        const amountMatch = lastUserMsg.match(/(\d+)/);
        const amount = amountMatch ? parseInt(amountMatch[1]) : 3;

        showStatus(`Scrolling ${direction} x${amount} at (${x}, ${y})...`);
        const result = await scroll(x, y, direction, amount);
        removeStatus();

        response = result.success
            ? `Scrolled ${result.direction} ${result.amount} notch${result.amount !== 1 ? 'es' : ''} at (${result.x}, ${result.y}).`
            : `Failed to scroll: ${result.error}`;

    } else if (/\bmove\b/i.test(lastUserMsg)) {
        const x = Math.floor(Math.random() * 1200) + 100;
        const y = Math.floor(Math.random() * 600) + 100;

        showStatus(`Moving mouse to (${x}, ${y})...`);
        const result = await navigateMouse(x, y);
        removeStatus();

        response = result.success
            ? `Moved mouse to coordinates (${result.x}, ${result.y}).`
            : `Failed to move mouse: ${result.error}`;

    } else if (/\bleft-click-open\b/i.test(lastUserMsg)) {
        const x = Math.floor(Math.random() * 1200) + 100;
        const y = Math.floor(Math.random() * 600) + 100;

        showStatus(`Opening at (${x}, ${y})...`);
        const result = await leftClickOpen(x, y);
        removeStatus();

        response = result.success
            ? `Double clicked (open) at coordinates (${result.x}, ${result.y}).`
            : `Failed to open: ${result.error}`;

    } else if (/\bleft-click\b/i.test(lastUserMsg)) {
        const x = Math.floor(Math.random() * 1200) + 100;
        const y = Math.floor(Math.random() * 600) + 100;

        showStatus(`Left clicking at (${x}, ${y})...`);
        const result = await leftClick(x, y);
        removeStatus();

        response = result.success
            ? `Left clicked at coordinates (${result.x}, ${result.y}).`
            : `Failed to left click: ${result.error}`;

    } else if (/\bright-click\b/i.test(lastUserMsg)) {
        const x = Math.floor(Math.random() * 1200) + 100;
        const y = Math.floor(Math.random() * 600) + 100;

        showStatus(`Right clicking at (${x}, ${y})...`);
        const result = await rightClick(x, y);
        removeStatus();

        response = result.success
            ? `Right clicked at coordinates (${result.x}, ${result.y}).`
            : `Failed to right click: ${result.error}`;

    } else {
        response = "I can see your screen. Let me analyze it and help with your task.";
    }

    let text = '';
    for (const char of response) {
        text += char;
        contentEl.textContent = text;
        chat.messages[chat.messages.length - 1].content = text;
        chatContainer.scrollTop = chatContainer.scrollHeight;
        await sleep(20);
    }

    isGenerating = false;
    chatInput.sendBtn.disabled = !chatInput.textarea.value.trim();
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
    const result = await captureScreenshot();
    updateStatus(result.success ? 'Screen captured' : 'Screenshot failed');
    await sleep(500);
    removeStatus();

    await respond(chat);
}

function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
}

init();
