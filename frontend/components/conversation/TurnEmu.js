// components/conversation/TurnEmu.js — Agent turn block
//
// Part of the Emu Design System v1 refactor (see FRONTEND_REDESIGN.md).
// Design source: Emu-handoff.zip → project/frames/chrome.jsx > Emu
//
// Replaces the old Message('assistant', content) bubble.
// Layout: italic serif "Emu" label → flex-column body area.
//
// The returned `.body` element is the mount point for:
//   - EmuRunner typing indicator (removed on first step)
//   - Trace lines (one per StepCard)
//   - Done text / final_message
//   - PlanCard, FileCard, SkillCard inline blocks

const { renderMarkdown } = require('../markdown');

function TurnEmu(initialText) {
    const wrap = document.createElement('div');
    wrap.className = 'turn-emu';

    const label = document.createElement('div');
    label.className = 'turn-label';
    label.textContent = 'Emu';
    wrap.appendChild(label);

    const body = document.createElement('div');
    body.className = 'turn-emu-body';

    // If initialText is provided (replaying past sessions), render as body text
    if (initialText && initialText.trim()) {
        const textEl = document.createElement('div');
        textEl.className = 'turn-text';
        renderMarkdown(textEl, initialText);
        body.appendChild(textEl);
    }

    wrap.appendChild(body);

    return {
        element: wrap,
        body,           // Chat.js appends trace lines + EmuRunner here
    };
}

module.exports = { TurnEmu };
