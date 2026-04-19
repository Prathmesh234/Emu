// pages/Chat.js — Chat page component
//
// Owns the chat UI: message list, input, status bar,
// WebSocket message handling, and action execution.
//
// Design change (Emu Design System v1 refactor — phases 1-3):
//   - Header      → MacWindow (chrome bar) + WindowHeader (Emu + status pill)
//   - ChatInput   → Composer (borderless, serif, hint row)
//   - Layout      → mac-chrome / mac-content / mac-main structure
//   All WebSocket, IPC, action dispatch, and API logic is unchanged.

const { ipcRenderer } = require('electron');
const { StepCard, DoneCard, ErrorCard, PlanCard, FileCard, SkillCard, HistoryPanel } = require('../components');
const { Greeting } = require('../components/conversation/Greeting');
const { TurnYou }      = require('../components/conversation/TurnYou');
const { TurnEmu }      = require('../components/conversation/TurnEmu');
const { MacWindow }    = require('../components/chrome/MacWindow');
const { WindowHeader } = require('../components/chrome/WindowHeader');
const { Composer }     = require('../components/chrome/Composer');
const { renderMarkdown } = require('../components/markdown');
const { createEmuRunner } = require('../components/EmuRunner');
const { captureScreenshot, fullCapture } = require('../actions');
const { dispatchAction } = require('../actions/actionProxy');
const store = require('../state/store');
const api = require('../services/api');
const { initWebSocket, setMessageHandler } = require('../services/websocket');

// ── DOM refs (populated in mount) ────────────────────────────────────────

let chatContainer, chatWrapper, chatInput, header, historyPanel, winHeader;
let _historyPanelOpen = false;
let _viewingPastSession = false;

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
    // Border glow only while agent is executing
    ipcRenderer.send('set-border', generating);
    if (generating) {
        chatInput.setMode('stop');
        chatInput.setTooltip('Emu is working…');   // shown as hint row in Composer
    } else {
        chatInput.setMode('send');
        chatInput.setTooltip('');
    }
    // Update the window header status pill
    if (winHeader) winHeader.setStatus(generating ? 'working' : 'ready', generating);
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
        header.setCompact(false);
    } else {
        await ipcRenderer.invoke('window:side-panel');
        store.setSidePanel(true);
        header.setExpandVisible(true);
        header.setCompact(true);
    }
}

async function moveToSidePanel() {
    if (!store.state.isSidePanel) {
        await ipcRenderer.invoke('window:side-panel');
        store.setSidePanel(true);
        header.setExpandVisible(true);
        header.setCompact(true);
    }
}

async function minimizeWindow() {
    try {
        await ipcRenderer.invoke('window:minimize');
    } catch (err) {
        console.warn('[window] minimize failed:', err.message);
    }
}

// ── Rendering ────────────────────────────────────────────────────────────

// Design change (Phase 5): replaced old EmptyState (emu SVG + "Hey I'm Emu")
// with the Idle greeting from the handoff design.
function showEmpty() {
    const greeting = Greeting();
    chatWrapper.appendChild(greeting.element);
}

// Design change (Phase 4): replaced Message('user'/'assistant') bubbles
// with TurnYou / TurnEmu blocks matching the handoff design.
// Returns: user → turn element; assistant → turn.body (mount point for trace lines).
function addMessage(role, content, index) {
    const empty = chatWrapper.querySelector('.empty-state, .idle-greeting');
    if (empty) empty.remove();

    if (role === 'user') {
        const turn = TurnYou(content);
        chatWrapper.appendChild(turn.element);
        scrollToBottom();
        return turn.element;
    } else {
        const turn = TurnEmu(content);
        chatWrapper.appendChild(turn.element);
        scrollToBottom();
        return turn.body;
    }
}

// Design change (Phase 4): status messages now drive the WindowHeader pill
// instead of appending a visible bubble to the chat area. This matches the
// design's quiet aesthetic — status lives in the chrome, not the conversation.
function showStatus(text) {
    if (winHeader) winHeader.setStatus(text, true);
}

function updateStatus(text) {
    if (winHeader) winHeader.setStatus(text, true);
}

function removeStatus() {
    // Revert to the live/idle state that syncGeneratingUI will correct on next call
    if (winHeader) winHeader.setStatus(store.state.isGenerating ? 'working' : 'ready', store.state.isGenerating);
}

// ── Chat selection ───────────────────────────────────────────────────────

function selectChat(id) {
    store.setCurrentChat(id);
    const chat = store.getChat(id);

    chatWrapper.innerHTML = '';

    if (chat && chat.messages.length > 0) {
        chat.messages.forEach((msg, i) => addMessage(msg.role, msg.content, i));
    } else {
        showEmpty(); // shows Idle greeting
    }

    chatInput.textarea.focus();
}

function newChat() {
    const id = store.createChat();
    _viewingPastSession = false;
    enableInput();
    selectChat(id);
    if (historyPanel) historyPanel.setActive(null);
}

// ── History panel ────────────────────────────────────────────────────────

function toggleHistoryPanel() {
    _historyPanelOpen = !_historyPanelOpen;
    const panel = historyPanel ? historyPanel.element : null;
    if (panel) {
        panel.classList.toggle('open', _historyPanelOpen);
    }
    if (_historyPanelOpen) {
        refreshHistory();
    }
}

async function refreshHistory() {
    try {
        const sessions = await api.fetchSessionHistory();
        if (historyPanel) historyPanel.populate(sessions);
    } catch (err) {
        console.warn('[history] failed to load:', err.message);
    }
}

async function loadPastSession(sessionId) {
    try {
        const messages = await api.fetchSessionMessages(sessionId);
        if (!messages || messages.length === 0) return;

        _viewingPastSession = true;
        disableInput();

        chatWrapper.innerHTML = '';

        // Group consecutive non-user messages into assistant "turns"
        // so tool/action/done cards appear inside step containers just like live sessions
        let stepNum = 0;
        let currentAssistantBubble = null;
        let currentStepContainer = null;

        // Design change (Phase 4): uses TurnEmu instead of raw .message.assistant divs
        function ensureAssistantBubble() {
            if (!currentAssistantBubble) {
                const turn = TurnEmu('');
                currentAssistantBubble = turn.element;
                currentStepContainer  = turn.body;
                chatWrapper.appendChild(currentAssistantBubble);
            }
            return currentStepContainer;
        }

        function flushAssistantBubble() {
            currentAssistantBubble = null;
            currentStepContainer = null;
        }

        messages.forEach(msg => {
            const role = msg.role;
            const content = msg.content || '';
            const meta = msg.metadata || {};

            // Skip screenshot entries
            if (content === '<screenshot>') return;

            if (role === 'user') {
                flushAssistantBubble();
                addMessage('user', content);
                return;
            }


            if (role === 'assistant') {
                // Done message — render as DoneCard or plain text
                const finalMsg = meta.final_message || content.replace(/^DONE\s*—?\s*/, '');
                if (finalMsg) {
                    const container = ensureAssistantBubble();
                    stepNum++;
                    const doneCard = StepCard({
                        action: { type: 'done' },
                        done: true,
                        final_message: finalMsg,
                        confidence: 1.0,
                    }, stepNum);
                    container.appendChild(doneCard.element);
                }
                flushAssistantBubble();
                return;
            }

            if (role === 'tool') {
                const container = ensureAssistantBubble();
                stepNum++;

                const toolName = meta.tool_name || '';
                const toolResult = meta.result || content;

                // Render skill cards for use_skill
                if (toolName === 'use_skill') {
                    let skillName = 'Unknown';
                    try {
                        const parsed = JSON.parse(meta.args || '{}');
                        skillName = parsed.skill_name || 'Unknown';
                    } catch (_) {}
                    const skillCard = SkillCard(skillName);
                    container.appendChild(skillCard.element);
                    return;
                }

                // Render file cards for write_session_file
                if (toolName === 'write_session_file') {
                    let filename = 'file';
                    try {
                        const parsed = JSON.parse(meta.args || '{}');
                        filename = parsed.filename || 'file';
                    } catch (_) {}
                    const fileCard = FileCard(filename, 'created', null);
                    container.appendChild(fileCard.element);
                    return;
                }

                // Generic tool card
                const toolCard = document.createElement('div');
                toolCard.className = 'step-card';

                const toolBlock = document.createElement('div');
                toolBlock.className = 'step-action';

                const toolLabel = document.createElement('div');
                toolLabel.className = 'step-label';
                toolLabel.textContent = `🔧 Tool: ${toolName || 'unknown'}`;
                toolBlock.appendChild(toolLabel);

                const toolDesc = document.createElement('div');
                toolDesc.className = 'step-action-desc';
                toolDesc.textContent = toolResult.length > 200 ? toolResult.slice(0, 200) + '…' : toolResult;
                toolBlock.appendChild(toolDesc);

                const badge = document.createElement('div');
                badge.className = 'step-action-status success';
                badge.textContent = '✓ Done';
                toolBlock.appendChild(badge);

                toolCard.appendChild(toolBlock);
                container.appendChild(toolCard);
                return;
            }

            if (role === 'action') {
                const container = ensureAssistantBubble();
                stepNum++;

                const actionType = meta.action_type || content.split(/\s+/)[0] || 'unknown';
                const confidence = meta.confidence != null ? meta.confidence : null;
                const reasoning = meta.reasoning || '';
                const actionPayload = meta.action || { type: actionType };

                const stepCard = StepCard({
                    action: actionPayload,
                    done: false,
                    confidence: confidence,
                    reasoning_content: reasoning,
                }, stepNum);

                // Mark as completed (not executing)
                const badge = stepCard.element.querySelector('.step-action-status');
                if (badge) {
                    badge.className = 'step-action-status success';
                    badge.textContent = '✓ Done';
                }

                container.appendChild(stepCard.element);
                return;
            }
        });

        scrollToBottom();
    } catch (err) {
        console.warn('[history] failed to load session:', err.message);
    }
}

function disableInput() {
    const container = chatInput.element;
    container.classList.add('composer-disabled');
    chatInput.textarea.disabled = true;
    chatInput.textarea.placeholder = '';
    chatInput.sendBtn.disabled = true;

    // Add overlay if not present
    if (!container.querySelector('.composer-overlay')) {
        const overlay = document.createElement('div');
        overlay.className = 'composer-overlay';
        overlay.textContent = 'Past sessions cannot be continued';
        container.appendChild(overlay);
    }
}

function enableInput() {
    const container = chatInput.element;
    container.classList.remove('composer-disabled');
    chatInput.textarea.disabled = false;
    chatInput.textarea.placeholder = 'Ask anything…';
    chatInput.sendBtn.disabled = !chatInput.textarea.value.trim();

    const overlay = container.querySelector('.composer-overlay');
    if (overlay) overlay.remove();
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
    chatInput.textarea.style.height = Math.min(chatInput.textarea.scrollHeight, 160) + 'px';
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
    if (_viewingPastSession) return;
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
    // Design change (Phase 4): contentEl is now TurnEmu.body — the direct
    // mount point for trace lines. No separate step-container div needed.
    const contentEl = addMessage('assistant', '', chat.messages.length - 1);
    contentEl.appendChild(createEmuRunner());

    store.setAssistantEl(contentEl);
    store.state.stepContainer = contentEl; // body IS the container
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
            // Status updates logged to console only — no visible card
            console.log(`[status] ${data.message}`);
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
                    // No steps ran — conversational reply (bootstrap, chat).
                    // Render as body text inside the TurnEmu block.
                    state.currentAssistantEl.innerHTML = '';
                    const textEl = document.createElement('div');
                    textEl.className = 'turn-text';
                    renderMarkdown(textEl, msg);
                    state.currentAssistantEl.appendChild(textEl);
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
                    chatInput.textarea.placeholder = 'Describe how to refine the plan…';
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

    // Mark trace as resolved (hides the blinking caret)
    stepEl.classList.add('resolved');
    const badge = stepEl.querySelector('.step-action-status');
    if (badge) {
        if (result.success) {
            badge.className = 'step-action-status success trace-status';
            badge.textContent = '✓';
        } else {
            badge.className = 'step-action-status failed trace-status';
            badge.textContent = '✗';
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
        // Backend is up — load session history for the sidebar
        refreshHistory();
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

    // ── MacWindow chrome bar (traffic lights + title + actions) ──────────
    // `header` keeps the same variable name so all existing callers
    // (setExpandVisible, setToggleDisabled, setCompact) work unchanged.
    header = MacWindow({
        onExpand:          toggleWindow,
        onMinimize:        minimizeWindow,
        onClose:           () => window.close(),
        onNewTask:         newChat,
        onToggleSidebar:   toggleHistoryPanel,
    });

    appEl.appendChild(header.chromeEl);

    // ── mac-content (sidebar + main, flex row) ────────────────────────────
    appEl.appendChild(header.contentEl);

    // ── History sidebar ───────────────────────────────────────────────────
    historyPanel = HistoryPanel({
        onNewChat:       () => newChat(),
        onSelectSession: (sid) => loadPastSession(sid),
        onToggle:        () => toggleHistoryPanel(),
    });
    header.contentEl.appendChild(historyPanel.element);

    // ── Main column (window-header + chat body + composer) ───────────────
    const macMain = document.createElement('div');
    macMain.className = 'mac-main';
    header.contentEl.appendChild(macMain);

    // Window header: "Emu" mark + status pill
    winHeader = WindowHeader();
    macMain.appendChild(winHeader.element);

    // Chat body (scrollable)
    chatContainer = document.createElement('div');
    chatContainer.className = 'chat-container';
    chatWrapper = document.createElement('div');
    chatWrapper.className = 'chat-wrapper';
    chatContainer.appendChild(chatWrapper);
    macMain.appendChild(chatContainer);

    // Auto-scroll whenever new content is added or elements resize
    const observer = new MutationObserver(() => scrollToBottom());
    observer.observe(chatWrapper, { childList: true, subtree: true, attributes: true });

    // Composer (drop-in replacement for ChatInput — same .textarea / .sendBtn / .setMode / .setTooltip API)
    chatInput = Composer(sendMessage, stopAgent);
    macMain.appendChild(chatInput.element);

    // Keyboard shortcuts (unchanged)
    document.onkeydown = (e) => {
        if (e.ctrlKey && e.shiftKey && e.key === 'N') {
            e.preventDefault();
            newChat();
        }
        if (e.key === 'Escape' && store.state.isSidePanel) {
            toggleWindow();
        }
    };

    // Border glow is driven by syncGeneratingUI — starts hidden
    ipcRenderer.send('set-border', false);

    newChat();
    chatInput.textarea.focus();
    initSession();
}

module.exports = { mount, newChat, selectChat };
