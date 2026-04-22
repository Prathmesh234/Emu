// StepCard — agent action step, rendered as a Trace block
//
// Part of the Emu Design System v1 refactor (see FRONTEND_REDESIGN.md).
// Design source: Emu-handoff.zip → project/frames/chrome.jsx > Trace
//
// Design change: replaces the old boxy card (screenshot thumbnail, reasoning
// block, action badge) with a minimal left-bordered italic trace line that
// shows what the agent is doing. Keeps identical function signatures and all
// class names (.step-action-status, .step-confirm-btn.allow/deny) so Chat.js
// querySelector logic needs no changes.
//
// Backend and action dispatch logic: untouched.

const { describeAction, actionIcon } = require('../actions/actionProxy');
const { renderMarkdown } = require('./markdown');
const { ConfirmCard } = require('./conversation/ConfirmCard');

function StepCard(data, stepNum) {
    const wrap = document.createElement('div');
    wrap.className = 'trace';

    // ── Reasoning (dim sub-line above the action text) ──────────────────
    const reasoning = data.reasoning_content || '';
    if (reasoning) {
        const reasonEl = document.createElement('div');
        reasonEl.className = 'trace-reasoning';

        // Truncate to 2 lines by default; click to expand
        const MAX = 240;
        let expanded = false;
        reasonEl.textContent = reasoning.length > MAX ? reasoning.slice(0, MAX) + '…' : reasoning;
        if (reasoning.length > MAX) {
            reasonEl.style.cursor = 'pointer';
            reasonEl.addEventListener('click', () => {
                expanded = !expanded;
                reasonEl.classList.toggle('expanded', expanded);
                reasonEl.textContent = expanded ? reasoning : reasoning.slice(0, MAX) + '…';
            });
        }
        wrap.appendChild(reasonEl);
    }

    // ── Action text (main trace line) ────────────────────────────────────
    if (data.action && !data.done) {
        const actionEl = document.createElement('span');
        actionEl.className = 'trace-action';
        actionEl.textContent = describeAction(data.action);
        wrap.appendChild(actionEl);

        // Shell exec: structured details card + Allow / Deny buttons
        // Design: matches F_Confirm frame — details in a bordered card,
        // primary filled "Allow" + outlined "Deny".
        if (data.requires_confirmation && data.action.type === 'shell_exec') {
            const card = ConfirmCard([
                ['Action',  'Shell command'],
                ['Command', data.action.command || ''],
            ]);
            // Apply monospace styling to the command row's value
            const rows = card.element.querySelectorAll('.confirm-card-val');
            if (rows.length >= 2) rows[1].classList.add('monospace');
            wrap.appendChild(card.element);

            const row = document.createElement('div');
            row.className = 'action-row';

            const allowBtn = document.createElement('button');
            allowBtn.className = 'step-confirm-btn allow';
            allowBtn.textContent = 'Allow';

            const denyBtn = document.createElement('button');
            denyBtn.className = 'step-confirm-btn deny';
            denyBtn.textContent = 'Deny';

            row.appendChild(allowBtn);
            row.appendChild(denyBtn);
            wrap.appendChild(row);

            // Hidden status span (shown after user decision)
            const badge = document.createElement('span');
            badge.className = 'step-action-status pending trace-status';
            badge.style.display = 'none';
            wrap.appendChild(badge);
        } else {
            // Status span (updated by executeAction in Chat.js)
            const badge = document.createElement('span');
            badge.className = 'step-action-status pending trace-status';
            badge.textContent = '…';
            wrap.appendChild(badge);
        }
    }

    // ── Done / final message ─────────────────────────────────────────────
    if (data.done && data.final_message) {
        // Render done text as non-italic body text (not inside a trace block)
        wrap.classList.remove('trace');
        wrap.classList.add('trace-done-text');
        renderMarkdown(wrap, data.final_message);
    }

    // Screenshots are intentionally not displayed inline in the new design.
    // The agent's actions are narrated via trace text instead.

    return { element: wrap };
}

// DoneCard — standalone final-message block (no prior steps)
function DoneCard(message) {
    const el = document.createElement('div');
    el.className = 'trace-done-text';
    renderMarkdown(el, message);
    return { element: el };
}

// ErrorCard — error message in trace styling, matches F_Error frame
// Renders a dim trace block with a quiet "paused" hint, so the user can
// simply reply in the composer to continue or redirect the agent.
function ErrorCard(message) {
    const wrap = document.createElement('div');
    wrap.className = 'trace trace-error';

    const text = document.createElement('span');
    text.textContent = message;
    wrap.appendChild(text);

    return { element: wrap };
}

module.exports = { StepCard, DoneCard, ErrorCard };
