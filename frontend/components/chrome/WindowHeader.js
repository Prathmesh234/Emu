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

function WindowHeader({ onToggleSidebar } = {}) {
    const header = document.createElement('div');
    header.className = 'window-header';

    // Left group: sidebar toggle + "Emu" wordmark
    const left = document.createElement('div');
    left.className = 'window-header-left';

    if (onToggleSidebar) {
        const sidebarBtn = document.createElement('button');
        sidebarBtn.className = 'window-header-sidebar-btn';
        sidebarBtn.type = 'button';
        sidebarBtn.title = 'Toggle sessions sidebar';
        sidebarBtn.setAttribute('aria-label', 'Toggle sessions sidebar');
        sidebarBtn.innerHTML = '<svg width="14" height="11" viewBox="0 0 13 10" fill="none"><rect x="0" y="0" width="4" height="10" rx="1" fill="currentColor" opacity=".4"/><rect x="6" y="0" width="7" height="1.5" rx=".75" fill="currentColor"/><rect x="6" y="4.25" width="7" height="1.5" rx=".75" fill="currentColor"/><rect x="6" y="8.5" width="7" height="1.5" rx=".75" fill="currentColor"/></svg>';
        sidebarBtn.addEventListener('click', onToggleSidebar);
        left.appendChild(sidebarBtn);
    }

    // "Emu" wordmark (italic serif 22px)
    const title = document.createElement('div');
    title.className = 'window-header-title';
    title.textContent = 'Emu';
    left.appendChild(title);

    header.appendChild(left);

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
