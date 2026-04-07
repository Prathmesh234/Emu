// pages/Chat.js — Chat page component
//
// Owns the chat UI: message list, input, status bar,
// WebSocket message handling, and action execution.

const { ipcRenderer } = require('electron');
const { Message, ChatInput, StepCard, ErrorCard, PlanCard, FileCard, SkillCard, Header, EmptyState, StatusIndicator } = require('../components');
const { createEmuRunner } = require('../components/EmuRunner');
const { captureScreenshot, fullCapture } = require('../actions');
const { dispatchAction } = require('../actions/actionProxy');
const store = require('../state/store');
const api = require('../services/api');
const { initWebSocket, setMessageHandler } = require('../services/websocket');

// ── DOM refs (populated in mount) ────────────────────────────────────────

let chatContainer, chatWrapper, chatInput, header;

// ── Helpers ──────────────────────────────────────────────────────────────

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// Chain length threshold: auto-compact when the backend context chain exceeds this.
const COMPACT_THRESHOLD = 100;

// Generation counter: incremented on each new respond() call and on stop.
// Used to detect stale WS messages from a previous generation cycle so
// they don't accidentally execute actions after a stop or new task start.
let _generationId = 0;

/** Scroll chat to bottom after the browser has laid out new content. */
function scrollToBottom() {
    requestAnimationFrame(() => {
        if (chatContainer) {
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }
    });
}

function syncGeneratingUI(generating) {
    store.setGenerating(generating);
    // Border is always-on — don't toggle it based on generating state.
    // It's managed separately via set-border (typing hide/show).
    if (generating) {
        chatInput.setMode('stop');
        chatInput.setTooltip('Click to stop the agent');
    } else {
        chatInput.setMode('send');
        chatInput.setTooltip('');
    }
    // Disable the dangerous mode toggle mid-generation
    if (header) header.setToggleDisabled(generating);
}

// ── Window helpers ───────────────────────────────────────────────────────

async function toggleWindow() {
    const { state } = store;
    if (state.isSidePanel) {
        await ipcRenderer.invoke('window:centered');
        store.setSidePanel(false);
        header.setExpandVisible(false);
    } else {
        await ipcRenderer.invoke('window:side-panel');
        store.setSidePanel(true);
        header.setExpandVisible(true);
    }
}

async function moveToSidePanel() {
    if (!store.state.isSidePanel) {
        await ipcRenderer.invoke('window:side-panel');
        store.setSidePanel(true);
        header.setExpandVisible(true);
    }
}

// ── Rendering ────────────────────────────────────────────────────────────

function showEmpty() {
    const emptyState = EmptyState();
    chatWrapper.appendChild(emptyState.element);
}

function addMessage(role, content, index) {
    const empty = chatWrapper.querySelector('.empty-state');
    if (empty) empty.remove();

    const msg = Message(role, content);

    chatWrapper.appendChild(msg.element);
    scrollToBottom();
    return msg.content;
}

function showStatus(text) {
    removeStatus();
    const indicator = StatusIndicator(text);
    chatWrapper.appendChild(indicator.element);
    scrollToBottom();
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

// ── Send / respond / stop ────────────────────────────────────────────────

async function stopAgent() {
    if (!store.state.isGenerating) return;

    console.log('[stopAgent] user requested stop');
    store.setStopped(true);
    // Bump generation ID so any in-flight WS messages from the old
    // generation are ignored — prevents stale actions from executing
    _generationId++;

    // Notify backend — adds STOP to the context chain
    // The session itself is NOT destroyed — user can continue chatting
    try {
        await api.stopAgent(store.state.sessionId);
    } catch (err) {
        console.warn('[stopAgent] backend call failed:', err.message);
    }

    // Show a stopped step card in the UI
    const { state } = store;
    store.state.stepCount = (store.state.stepCount || 0) + 1;
    const stepNum = store.state.stepCount;

    const stoppedCard = StepCard({
        action: { type: 'done' },
        done: true,
        final_message: 'Stopped by user',
        confidence: 1.0,
    }, stepNum);

    if (state.currentAssistantEl) {
        let container = state.stepContainer;
        if (container && !container.parentNode) {
            state.currentAssistantEl.appendChild(container);
        }
        if (container) {
            container.appendChild(stoppedCard.element);
        } else {
            state.currentAssistantEl.appendChild(stoppedCard.element);
        }
    }
    scrollToBottom();

    syncGeneratingUI(false);

    // Add visible STOP message in chat
    const chat = store.getCurrentChat();
    if (chat) {
        store.pushMessage(chat.id, { role: 'user', content: 'STOP' });
        addMessage('user', 'STOP', chat.messages.length - 1);
    }
}

async function sendMessage() {
    const text = chatInput.textarea.value.trim();
    if (!text) return;

    // If currently generating, stop the current task first, then send the new message
    if (store.state.isGenerating) {
        // Grab the text before stopping (stop clears state)
        const pendingText = text;
        await stopAgent();
        // Wait for stop to settle
        await sleep(300);
        // Now send the new message by putting it back and recursing
        chatInput.textarea.value = pendingText;
        chatInput.sendBtn.disabled = false;
        // Fall through to send logic below (isGenerating is now false)
    }

    let finalText = chatInput.textarea.value.trim();
    if (!finalText) return;

    // If user is refining a plan, prefix the message
    if (store.state.pendingPlanRefine) {
        finalText = `User wants to refine the plan: ${finalText}`;
        store.state.pendingPlanRefine = false;
        chatInput.textarea.placeholder = 'Ask anything...';
    }

    const chat = store.getCurrentChat();
    if (!chat) return;

    // Add user message
    store.pushMessage(chat.id, { role: 'user', content: finalText });
    addMessage('user', finalText, chat.messages.length - 1);
    store.updateChatPreview(chat.id, finalText);

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

    // Don't move to side panel here — only move when a vision/action step arrives
    // (see handleWsMessage 'step' case)

    // Debug: full-capture
    if (/\bfull[-\s]?capture\b/i.test(finalText)) {
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
    store.setStopped(false);
    _generationId++;
    const thisGenId = _generationId;
    store.state._generationId = thisGenId;
    syncGeneratingUI(true);

    const lastUserMsg = store.getLastUserMessage(chat);

    store.pushMessage(chat.id, { role: 'assistant', content: '', stepCount: 0 });
    const contentEl = addMessage('assistant', '', chat.messages.length - 1);
    contentEl.appendChild(createEmuRunner());

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
    const loopGenId = _generationId;
    if (store.state.isStopped) {
        console.log('[continueLoop] stopped by user — bailing out');
        return;
    }
    // If generation changed since this continueLoop was called, bail
    if (loopGenId !== _generationId) {
        console.log('[continueLoop] generation changed — bailing out');
        return;
    }
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

    const sizeKB = Math.round(screenshot.base64.length / 1024);
    console.log(`[continueLoop] screenshot OK (${sizeKB} KB) — posting to backend`);

    // Show screenshot as a visible step card in the UI
    store.state.stepCount = (store.state.stepCount || 0) + 1;
    const stepNum = store.state.stepCount;

    const screenshotStepData = {
        action: null,
        screenshot: screenshot.base64,
        confidence: 1.0,
        done: false,
    };
    const screenshotCard = StepCard(screenshotStepData, stepNum);

    const { state } = store;
    if (state.currentAssistantEl) {
        let container = state.stepContainer;
        if (container && !container.parentNode) {
            state.currentAssistantEl.appendChild(container);
        }
        if (container) {
            container.appendChild(screenshotCard.element);
        } else {
            state.currentAssistantEl.appendChild(screenshotCard.element);
        }
    }
    scrollToBottom();

    // Send screenshot to backend (no new assistant message bubble — reuse current)
    try {
        // Auto-compact if context chain is bloating
        const chainLen = store.state.lastChainLength || 0;
        if (chainLen >= COMPACT_THRESHOLD) {
            console.log(`[continueLoop] chain_length=${chainLen} >= ${COMPACT_THRESHOLD} — auto-compacting`);
            showStatus('Compacting context (summarising history)...');
            try {
                const result = await api.compactContext(store.state.sessionId);
                console.log(`[continueLoop] compact result:`, result);
                if (result.status === 'compacted') {
                    updateStatus(`Compacted: ${result.previous_length} → ${result.new_length} messages`);
                    store.state.lastChainLength = result.new_length;
                    await sleep(1000);
                }
            } catch (compactErr) {
                console.warn('[continueLoop] compact failed:', compactErr.message);
            }
            removeStatus();
        }

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
    // Capture the generation ID at the time this message was received
    const msgGenId = _generationId;

    switch (data.type) {
        case 'status':
            // Status messages are always safe to show
            if (msgGenId === _generationId) showStatus(data.message);
            break;

        case 'step': {
            // If the generation has changed since this message was queued,
            // this is a stale response from a previous generation — ignore it
            if (msgGenId !== _generationId) {
                console.log(`[step] stale message (gen ${msgGenId} vs current ${_generationId}) — ignoring`);
                break;
            }
            removeStatus();

            // Track chain length for auto-compact
            if (data.chain_length != null) {
                store.state.lastChainLength = data.chain_length;
            }

            // Move to side panel only for vision/action steps (not pure chat/done)
            if (!data.done && data.action) {
                await moveToSidePanel();
            }

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

            scrollToBottom();

            if (data.done) {
                syncGeneratingUI(false);
                break;
            }

            // Bail out if user stopped
            if (store.state.isStopped) {
                console.log('[step] user stopped — not executing action');
                syncGeneratingUI(false);
                break;
            }

            if (data.action) {
                try {
                    if (data.action.type === 'screenshot') {
                        console.log('[step] model requested screenshot — calling continueLoop');
                        await continueLoop();
                    } else if (data.requires_confirmation && !store.state.dangerousMode) {
                        // Shell exec confirmation — wait for user Allow/Deny
                        console.log('[step] awaiting user confirmation for shell_exec');
                        const decision = await waitForConfirmation(stepCard.element);
                        if (decision === 'allow') {
                            console.log('[step] user allowed shell_exec — executing');
                            const badge = stepCard.element.querySelector('.step-action-status');
                            if (badge) { badge.style.display = ''; badge.textContent = 'Executing…'; }
                            await executeAction(data.action, stepCard.element);
                            await sleep(500);
                            await continueLoop();
                        } else {
                            console.log('[step] user denied shell_exec — notifying backend');
                            const badge = stepCard.element.querySelector('.step-action-status');
                            if (badge) {
                                badge.style.display = '';
                                badge.className = 'step-action-status failed';
                                badge.textContent = 'Denied by user';
                            }
                            // Inject denial into context so the model can adapt
                            try {
                                await api.notifyActionComplete({
                                    sessionId: store.state.sessionId,
                                    ipcChannel: 'shell:exec',
                                    success: false,
                                    error: 'DENIED — user has denied this command. Try a different approach.',
                                    output: null,
                                });
                            } catch (_) {}
                            await sleep(300);
                            await continueLoop();
                        }
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

            // If steps already rendered (stepCount > 0), the last StepCard
            // with done:true already shows the final_message — skip duplicate.
            const alreadyHandledByStep = (store.state.stepCount || 0) > 0;

            if (state.currentAssistantEl) {
                const typing = state.currentAssistantEl.querySelector('.typing');
                if (typing) typing.remove();

                if (!alreadyHandledByStep) {
                    // No steps ran — this is a conversational reply (bootstrap, chat).
                    // Render as plain text in the assistant bubble instead of a card.
                    state.currentAssistantEl.textContent = msg;
                }
            }
            if (state.currentChat) {
                state.currentChat.messages[state.currentChat.messages.length - 1].content = msg;
            }
            syncGeneratingUI(false);
            scrollToBottom();
            break;
        }

        case 'stopped':
            removeStatus();
            console.log('[ws] received stopped from backend');
            syncGeneratingUI(false);
            break;

        case 'plan_review': {
            if (msgGenId !== _generationId) break;
            removeStatus();

            if (state.currentAssistantEl) {
                const typing = state.currentAssistantEl.querySelector('.typing');
                if (typing) typing.remove();

                let container = state.stepContainer;
                if (container && !container.parentNode) {
                    state.currentAssistantEl.appendChild(container);
                }

                const planCard = PlanCard(data.content);

                // In dangerous mode, auto-accept the plan without user confirmation
                if (store.state.dangerousMode) {
                    planCard.acceptBtn.disabled = true;
                    planCard.refineBtn.disabled = true;
                    planCard.acceptBtn.classList.add('chosen');

                    if (container) {
                        container.appendChild(planCard.element);
                    } else {
                        state.currentAssistantEl.appendChild(planCard.element);
                    }
                    scrollToBottom();

                    showStatus('Plan auto-accepted — starting execution...');
                    try {
                        await api.postStep({
                            sessionId: store.state.sessionId,
                            userMessage: '[PLAN APPROVED] The user has accepted the plan. Proceed with execution — take a screenshot to orient yourself and begin from step 1.',
                            base64Screenshot: '',
                        });
                    } catch (err) {
                        console.error('[plan_review] auto-accept failed:', err);
                        removeStatus();
                        syncGeneratingUI(false);
                    }
                    break;
                }

                planCard.acceptBtn.addEventListener('click', async () => {
                    planCard.acceptBtn.disabled = true;
                    planCard.refineBtn.disabled = true;
                    planCard.acceptBtn.classList.add('chosen');

                    // User accepted — inject approval into context and resume
                    showStatus('Plan accepted — starting execution...');
                    try {
                        await api.postStep({
                            sessionId: store.state.sessionId,
                            userMessage: '[PLAN APPROVED] The user has accepted the plan. Proceed with execution — take a screenshot to orient yourself and begin from step 1.',
                            base64Screenshot: '',
                        });
                    } catch (err) {
                        console.error('[plan_review] accept failed:', err);
                        removeStatus();
                        syncGeneratingUI(false);
                    }
                }, { once: true });

                planCard.refineBtn.addEventListener('click', async () => {
                    planCard.acceptBtn.disabled = true;
                    planCard.refineBtn.disabled = true;
                    planCard.refineBtn.classList.add('chosen');

                    // Pause — let user type refinement
                    syncGeneratingUI(false);
                    store.state.pendingPlanRefine = true;
                    chatInput.textarea.placeholder = 'Describe how to refine the plan...';
                    chatInput.textarea.focus();
                }, { once: true });

                if (container) {
                    container.appendChild(planCard.element);
                } else {
                    state.currentAssistantEl.appendChild(planCard.element);
                }
            }
            scrollToBottom();
            break;
        }

        case 'tool_event': {
            if (msgGenId !== _generationId) break;
            removeStatus();

            if (state.currentAssistantEl) {
                const typing = state.currentAssistantEl.querySelector('.typing');
                if (typing) typing.remove();

                let container = state.stepContainer;
                if (container && !container.parentNode) {
                    state.currentAssistantEl.appendChild(container);
                }

                if (data.event === 'file_written') {
                    const fileCard = FileCard(data.filename, data.action, data.filepath);
                    if (container) {
                        container.appendChild(fileCard.element);
                    } else {
                        state.currentAssistantEl.appendChild(fileCard.element);
                    }
                } else if (data.event === 'skill_used') {
                    const skillCard = SkillCard(data.skill_name);
                    if (container) {
                        container.appendChild(skillCard.element);
                    } else {
                        state.currentAssistantEl.appendChild(skillCard.element);
                    }
                }
            }
            scrollToBottom();
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

// ── Shell exec confirmation ──────────────────────────────────────────────

/**
 * Wait for the user to click Allow or Deny on a step card.
 * Returns 'allow' or 'deny'.
 */
function waitForConfirmation(stepEl) {
    return new Promise(resolve => {
        const allowBtn = stepEl.querySelector('.step-confirm-btn.allow');
        const denyBtn = stepEl.querySelector('.step-confirm-btn.deny');
        if (!allowBtn || !denyBtn) {
            // No buttons found — auto-allow (shouldn't happen)
            resolve('allow');
            return;
        }
        allowBtn.addEventListener('click', () => {
            allowBtn.disabled = true;
            denyBtn.disabled = true;
            allowBtn.classList.add('chosen');
            resolve('allow');
        }, { once: true });
        denyBtn.addEventListener('click', () => {
            allowBtn.disabled = true;
            denyBtn.disabled = true;
            denyBtn.classList.add('chosen');
            resolve('deny');
        }, { once: true });
    });
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
            output: result.output || null,
        });
    } catch (_) { /* non-critical */ }
}

// ── Session bootstrap ────────────────────────────────────────────────────

async function initSession() {
    console.log('[session] attempting to create session...');
    try {
        const id = await api.createSession();
        if (!id) {
            throw new Error('createSession returned empty id');
        }
        store.setSession(id);
        initWebSocket(id);
        console.log('[session] created successfully:', id);
    } catch (err) {
        console.warn('[session] failed:', err.message);
        console.log('[session] retrying in 2s... (is backend running on localhost:8000?)');
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

    // Header (component)
    header = Header({
        onExpand: toggleWindow,
        onClose: () => window.close(),
        onNewTask: newChat,
    });
    main.appendChild(header.element);

    // Chat area
    chatContainer = document.createElement('div');
    chatContainer.className = 'chat-container';
    chatWrapper = document.createElement('div');
    chatWrapper.className = 'chat-wrapper';
    chatContainer.appendChild(chatWrapper);
    main.appendChild(chatContainer);

    // Auto-scroll whenever new content is added or elements resize
    const observer = new MutationObserver(() => scrollToBottom());
    observer.observe(chatWrapper, { childList: true, subtree: true, attributes: true });

    // Input
    chatInput = ChatInput(sendMessage, stopAgent);
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

    // Boot — show border glow immediately (always-on)
    ipcRenderer.send('set-border', true);

    // Hide border while user is typing, re-show after they stop
    let _borderTypingTimer = null;
    chatInput.textarea.addEventListener('input', () => {
        ipcRenderer.send('set-border', false);
        clearTimeout(_borderTypingTimer);
        _borderTypingTimer = setTimeout(() => {
            ipcRenderer.send('set-border', true);
        }, 800);
    });

    newChat();
    chatInput.textarea.focus();
    initSession();
}

module.exports = { mount, newChat, selectChat };
