// components/conversation/TurnYou.js — User turn block
//
// Part of the Emu Design System v1 refactor (see FRONTEND_REDESIGN.md).
// Design source: Emu-handoff.zip → project/frames/chrome.jsx > You
//
// Replaces the old Message('user', content) bubble.
// Layout: italic serif "You" label → 19px body text.

function TurnYou(content) {
    const wrap = document.createElement('div');
    wrap.className = 'turn-you';

    const label = document.createElement('div');
    label.className = 'turn-label';
    label.textContent = 'You';
    wrap.appendChild(label);

    const text = document.createElement('p');
    text.className = 'turn-you-text';
    text.textContent = content || '';
    wrap.appendChild(text);

    return {
        element: wrap,
        // setText is available if callers need to update content later
        setText(t) { text.textContent = t; },
    };
}

module.exports = { TurnYou };
