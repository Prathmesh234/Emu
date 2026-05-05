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

const store = require('../../state/store');

const AGENT_MODES = ['coworker', 'remote'];

function _modeOption(mode) {
    const btn = document.createElement('button');
    btn.className = 'window-mode-option';
    btn.type = 'button';
    btn.dataset.mode = mode;
    btn.textContent = mode;
    btn.setAttribute('role', 'radio');
    return btn;
}

function _createModeToggle() {
    const wrap = document.createElement('div');
    wrap.className = 'window-mode-toggle';
    wrap.setAttribute('role', 'radiogroup');
    wrap.setAttribute('aria-label', 'Agent mode');
    wrap.title = 'Choose agent mode';

    const thumb = document.createElement('span');
    thumb.className = 'window-mode-thumb';
    wrap.appendChild(thumb);

    const buttons = {};
    AGENT_MODES.forEach((mode) => {
        const btn = _modeOption(mode);
        buttons[mode] = btn;
        wrap.appendChild(btn);
    });

    function sync() {
        const mode = store.state.agentMode;
        wrap.classList.toggle('remote', mode === 'remote');
        AGENT_MODES.forEach((option) => {
            const active = mode === option;
            buttons[option].classList.toggle('active', active);
            buttons[option].setAttribute('aria-checked', String(active));
        });
    }

    function setDisabled(disabled) {
        wrap.classList.toggle('disabled', disabled);
        wrap.title = disabled
            ? 'Agent mode is locked while Emu is working'
            : 'Choose agent mode';
        AGENT_MODES.forEach((mode) => {
            buttons[mode].disabled = disabled;
        });
    }

    AGENT_MODES.forEach((mode) => {
        buttons[mode].addEventListener('click', () => {
            if (store.state.isGenerating) return;
            store.setAgentMode(mode);
            sync();
        });
    });

    sync();
    return { element: wrap, setDisabled };
}

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

    const title = document.createElement('div');
    title.className = 'window-header-title';
    title.textContent = 'Emu';
    left.appendChild(title);

    // Center group: agent mode toggle
    const center = document.createElement('div');
    center.className = 'window-header-center';

    const modeToggle = _createModeToggle();
    center.appendChild(modeToggle.element);

    header.appendChild(left);
    header.appendChild(center);

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

        setModeDisabled(disabled) {
            modeToggle.setDisabled(disabled);
        },
    };
}

module.exports = { WindowHeader };
