// components/chrome/MacWindow.js — 32px chrome bar (traffic lights + title + actions)
//
// Part of the Emu Design System v1 refactor (see FRONTEND_REDESIGN.md).
// Design source: Emu-handoff.zip → project/frames/chrome.jsx > MacWindow
//
// This component owns the top chrome bar only (traffic light dots, window
// title, danger toggle, theme toggle, window controls). It does NOT own the
// inner "Emu" header — that's WindowHeader.js.
//
// Drop-in replacement for the old Header.js from Chat.js's perspective:
// exposes setExpandVisible(), setToggleDisabled(), setCompact() so Chat.js
// mount() and syncGeneratingUI() require minimal changes.
//
// Backend and IPC calls are identical to the old Header.js.

const store = require('../../state/store');

function MacWindow({ onExpand, onMinimize, onClose, onNewTask, onToggleSidebar }) {
    // ── Chrome bar (32px drag region) ────────────────────────────────────
    const chrome = document.createElement('div');
    chrome.className = 'mac-chrome';

    // Three monochrome dot buttons: close / minimize / expand
    const dots = document.createElement('div');
    dots.className = 'mac-dots';

    const dotClose    = _dot('Close window',    onClose || (() => window.close()));
    const dotMinimize = _dot('Minimize window', onMinimize);
    const dotExpand   = _dot('Expand / side panel', onExpand);
    dotExpand.style.display = 'none'; // hidden until in side-panel mode

    dots.appendChild(dotClose);
    dots.appendChild(dotMinimize);
    dots.appendChild(dotExpand);
    chrome.appendChild(dots);

    // Window title ("Emu" in italic serif, centered)
    const title = document.createElement('div');
    title.className = 'mac-chrome-title';
    title.textContent = 'Emu';
    chrome.appendChild(title);

    // Actions: new-task, danger toggle, theme toggle
    const actions = document.createElement('div');
    actions.className = 'mac-actions';

    // Sessions sidebar toggle
    if (onToggleSidebar) {
        const sidebarBtn = document.createElement('button');
        sidebarBtn.className = 'mac-action-btn';
        sidebarBtn.type = 'button';
        sidebarBtn.title = 'Toggle sessions sidebar';
        sidebarBtn.innerHTML = '<svg width="13" height="10" viewBox="0 0 13 10" fill="none"><rect x="0" y="0" width="4" height="10" rx="1" fill="currentColor" opacity=".4"/><rect x="6" y="0" width="7" height="1.5" rx=".75" fill="currentColor"/><rect x="6" y="4.25" width="7" height="1.5" rx=".75" fill="currentColor"/><rect x="6" y="8.5" width="7" height="1.5" rx=".75" fill="currentColor"/></svg>';
        sidebarBtn.addEventListener('click', onToggleSidebar);
        actions.appendChild(sidebarBtn);
    }

    // Danger mode toggle (compact slider)
    const dangerWrap = document.createElement('label');
    dangerWrap.className = 'mac-danger-wrap' + (store.state.dangerousMode ? ' active' : '');
    dangerWrap.title = 'Auto-approve shell commands (dangerous mode)';

    const dangerInput = document.createElement('input');
    dangerInput.type = 'checkbox';
    dangerInput.checked = store.state.dangerousMode;
    dangerInput.addEventListener('change', () => {
        store.setDangerousMode(dangerInput.checked);
        dangerWrap.classList.toggle('active', dangerInput.checked);
    });

    const dangerSlider = document.createElement('span');
    dangerSlider.className = 'mac-danger-slider';

    dangerWrap.appendChild(dangerInput);
    dangerWrap.appendChild(dangerSlider);
    actions.appendChild(dangerWrap);

    // Theme toggle (moon / sun glyph)
    const themeBtn = document.createElement('button');
    themeBtn.className = 'mac-action-btn';
    themeBtn.type = 'button';
    themeBtn.title = store.state.darkMode ? 'Switch to light mode' : 'Switch to dark mode';
    themeBtn.textContent = store.state.darkMode ? '☀' : '☽';
    themeBtn.onclick = () => {
        const newDark = !store.state.darkMode;
        store.setDarkMode(newDark);
        // New: toggle .ink on <body> (Emu Design System v1)
        document.body.classList.toggle('ink', newDark);
        themeBtn.textContent = newDark ? '☀' : '☽';
        themeBtn.title = newDark ? 'Switch to light mode' : 'Switch to dark mode';
    };
    actions.appendChild(themeBtn);

    chrome.appendChild(actions);

    // ── Content shell below chrome ────────────────────────────────────────
    // Chat.js appends sidebar + main into this element.
    const content = document.createElement('div');
    content.className = 'mac-content';

    return {
        chromeEl:  chrome,
        contentEl: content,

        // ── API (matches old Header.js so Chat.js needs no logic changes) ──

        setExpandVisible(visible) {
            dotExpand.style.display = visible ? '' : 'none';
        },

        setToggleDisabled(disabled) {
            dangerInput.disabled = disabled;
            dangerWrap.classList.toggle('disabled', disabled);
        },

        // In side-panel (compact) mode the window is narrow; hide chrome title.
        setCompact(compact) {
            title.style.opacity = compact ? '0' : '';
        },
    };
}

// ── Private helpers ───────────────────────────────────────────────────────

function _dot(label, onClick) {
    const d = document.createElement('button');
    d.className = 'mac-dot';
    d.type = 'button';
    d.title = label;
    d.setAttribute('aria-label', label);
    if (onClick) d.onclick = onClick;
    return d;
}

module.exports = { MacWindow };
