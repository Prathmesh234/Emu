// components/chrome/WindowHeader.js — "Emu" mark + live status pill
//
// Part of the Emu Design System v1 refactor (see FRONTEND_REDESIGN.md).
// Design source: Emu-handoff.zip → project/frames/chrome.jsx > Header
//
// Sits below the mac-chrome bar, above the chat body. Shows the "Emu"
// wordmark (italic serif) on the left and a live-status pill on the right.
//
// Status strings map to visual state:
//   'ready'    → dot dim, text "ready"
//   'working'  → dot pulses (emuPulse), text "working"
//   'waiting'  → dot dim, text "waiting for you"
//   'finished' → dot dim, text "finished"
//   'stopped'  → dot dim, text "stopped"

function WindowHeader() {
    const header = document.createElement('div');
    header.className = 'window-header';

    // "Emu" wordmark (italic serif 22px)
    const title = document.createElement('div');
    title.className = 'window-header-title';
    title.textContent = 'Emu';
    header.appendChild(title);

    // Status pill: pulsing dot + italic status text
    const status = document.createElement('div');
    status.className = 'window-header-status';

    const dot = document.createElement('span');
    dot.className = 'window-status-dot';

    const text = document.createElement('span');
    text.textContent = 'ready';

    status.appendChild(dot);
    status.appendChild(text);
    header.appendChild(status);

    return {
        element: header,

        /**
         * Update the status pill.
         * @param {string} label  — text shown next to the dot
         * @param {boolean} live  — true = dot pulses (agent is active)
         */
        setStatus(label, live) {
            text.textContent = label || 'ready';
            dot.classList.toggle('live', !!live);
        },
    };
}

module.exports = { WindowHeader };
