// components/chrome/Composer.js — Minimal borderless input bar
//
// Part of the Emu Design System v1 refactor (see FRONTEND_REDESIGN.md).
// Design source: Emu-handoff.zip → project/frames/chrome.jsx > Composer
//
// Replaces the old ChatInput.js (rounded-border textarea + SVG icon button)
// with the new quiet composer: top-border only, serif italic placeholder,
// italic "send" / "stop" verb button, optional hint row above the input.
//
// Drop-in replacement API for Chat.js:
//   .element        — the DOM element to append
//   .textarea       — the <textarea> (same interface as ChatInput)
//   .sendBtn        — the action button (same interface as ChatInput)
//   .setMode(mode)  — 'send' | 'stop'
//   .setTooltip(t)  — repurposed as hint text in the new design
//
// No backend changes. All onSend/onStop callbacks are identical.

function Composer(onSend, onStop) {
    const container = document.createElement('div');
    container.className = 'composer';
    container.style.position = 'relative'; // for overlay

    // ── Hint row (hidden by default) ─────────────────────────────────────
    const hintRow = document.createElement('div');
    hintRow.className = 'composer-hint';
    hintRow.style.display = 'none';

    const hintDot = document.createElement('span');
    hintDot.className = 'composer-hint-dot';

    const hintText = document.createElement('span');
    hintText.textContent = '';

    hintRow.appendChild(hintDot);
    hintRow.appendChild(hintText);
    container.appendChild(hintRow);

    // ── Input row ─────────────────────────────────────────────────────────
    const row = document.createElement('div');
    row.className = 'composer-row';

    const textarea = document.createElement('textarea');
    textarea.className = 'composer-input';
    textarea.placeholder = 'Ask anything…';
    textarea.rows = 1;

    // Keep textarea height fitted to content
    textarea.addEventListener('input', () => {
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 160) + 'px';
        // Swap italic/upright styling based on content presence
        textarea.classList.toggle('has-value', !!textarea.value.trim());
        if (_mode === 'send') {
            sendBtn.disabled = !textarea.value.trim();
        }
    });

    // Enter sends; Shift+Enter inserts newline
    textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (_mode === 'stop') {
                if (onStop) onStop();
            } else if (textarea.value.trim() && !sendBtn.disabled && onSend) {
                onSend();
            }
        }
    });

    // Verb button: italic serif "send" | "stop"
    const sendBtn = document.createElement('button');
    sendBtn.className = 'composer-btn';
    sendBtn.type = 'button';
    sendBtn.textContent = 'send';
    sendBtn.disabled = true;

    sendBtn.addEventListener('click', () => {
        if (_mode === 'stop') {
            if (onStop) onStop();
        } else if (textarea.value.trim() && onSend) {
            onSend();
        }
    });

    row.appendChild(textarea);
    row.appendChild(sendBtn);
    container.appendChild(row);

    // ── State machine ─────────────────────────────────────────────────────

    let _mode = 'send'; // 'send' | 'stop'

    function setMode(mode) {
        if (_mode === mode) return;
        _mode = mode;
        if (mode === 'stop') {
            sendBtn.textContent = 'stop';
            sendBtn.className = 'composer-btn stop-mode';
            sendBtn.disabled = false;
        } else {
            sendBtn.textContent = 'send';
            sendBtn.className = 'composer-btn';
            sendBtn.disabled = !textarea.value.trim();
        }
    }

    /**
     * setTooltip — repurposed as hint text in the new design.
     * Called by Chat.js's syncGeneratingUI with status copy.
     * Empty string hides the hint row; any text shows it with a live dot.
     */
    function setTooltip(text) {
        if (!text) {
            hintRow.style.display = 'none';
            hintText.textContent = '';
            hintDot.classList.remove('live');
        } else {
            hintRow.style.display = '';
            hintText.textContent = text;
            hintDot.classList.toggle('live', _mode === 'stop');
        }
    }

    return {
        element: container,
        textarea,
        sendBtn,
        setMode,
        setTooltip,
    };
}

module.exports = { Composer };
