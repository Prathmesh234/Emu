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

function MacWindow({ onMaximize, onMinimize, onClose, onNewTask, onToggleSidebar, onOpenSettings }) {
    // ── Chrome bar (32px drag region) ────────────────────────────────────
    const chrome = document.createElement('div');
    chrome.className = 'mac-chrome';

    // Three monochrome traffic-light buttons: close / minimize / maximize.
    // macOS pattern: each dot reveals its glyph (× / − / +) on group hover.
    const dots = document.createElement('div');
    dots.className = 'mac-dots';

    const dotClose    = _dot('Close window',      onClose || (() => window.close()), '×');
    const dotMinimize = _dot('Minimize window',   onMinimize,                         '−');
    const dotMaximize = _dot('Maximize / restore', onMaximize,                        '+');

    dots.appendChild(dotClose);
    dots.appendChild(dotMinimize);
    dots.appendChild(dotMaximize);
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

    // Theme toggle — moved into Settings, but keep in chrome too for one-click access
    const themeBtn = document.createElement('button');
    themeBtn.className = 'mac-action-btn theme-toggle';
    themeBtn.type = 'button';
    themeBtn.title = store.state.darkMode ? 'Switch to light mode' : 'Switch to dark mode';
    themeBtn.textContent = store.state.darkMode ? '☀' : '☽';
    themeBtn.onclick = () => {
        const newDark = !store.state.darkMode;
        store.setDarkMode(newDark);
        document.body.classList.toggle('ink', newDark);
        themeBtn.textContent = newDark ? '☀' : '☽';
        themeBtn.title = newDark ? 'Switch to light mode' : 'Switch to dark mode';
    };
    actions.appendChild(themeBtn);

    // Settings (gear) — opens the Settings modal
    if (onOpenSettings) {
        const settingsBtn = document.createElement('button');
        settingsBtn.className = 'mac-action-btn settings-btn';
        settingsBtn.type = 'button';
        settingsBtn.title = 'Settings';
        settingsBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="7" cy="7" r="2"/><path d="M11.5 8.3a.95.95 0 0 0 .19 1.05l.04.04a1.15 1.15 0 1 1-1.63 1.63l-.04-.04a.95.95 0 0 0-1.05-.19.95.95 0 0 0-.58.87v.12a1.15 1.15 0 1 1-2.3 0v-.06a.95.95 0 0 0-.62-.87.95.95 0 0 0-1.05.19l-.04.04a1.15 1.15 0 1 1-1.63-1.63l.04-.04a.95.95 0 0 0 .19-1.05.95.95 0 0 0-.87-.58h-.12a1.15 1.15 0 1 1 0-2.3h.06a.95.95 0 0 0 .87-.62.95.95 0 0 0-.19-1.05l-.04-.04a1.15 1.15 0 1 1 1.63-1.63l.04.04a.95.95 0 0 0 1.05.19h.01a.95.95 0 0 0 .58-.87v-.12a1.15 1.15 0 1 1 2.3 0v.06a.95.95 0 0 0 .58.87.95.95 0 0 0 1.05-.19l.04-.04a1.15 1.15 0 1 1 1.63 1.63l-.04.04a.95.95 0 0 0-.19 1.05v.01a.95.95 0 0 0 .87.58h.12a1.15 1.15 0 1 1 0 2.3h-.06a.95.95 0 0 0-.87.58z"/></svg>';
        settingsBtn.addEventListener('click', onOpenSettings);
        actions.appendChild(settingsBtn);
    }

    chrome.appendChild(actions);

    // ── Content shell below chrome ────────────────────────────────────────
    // Chat.js appends sidebar + main into this element.
    const content = document.createElement('div');
    content.className = 'mac-content';

    return {
        chromeEl:  chrome,
        contentEl: content,

        // ── Public API ────────────────────────────────────────────────────

        // setExpandVisible kept as no-op so legacy callers don't crash
        setExpandVisible() { /* no-op since side-panel toggle left the chrome */ },

        setToggleDisabled(disabled) {
            dangerInput.disabled = disabled;
            dangerWrap.classList.toggle('disabled', disabled);
        },

        setCompact(compact) {
            title.style.opacity = compact ? '0' : '';
        },
    };
}

// ── Private helpers ───────────────────────────────────────────────────────

function _dot(label, onClick, glyph) {
    const d = document.createElement('button');
    d.className = 'mac-dot';
    d.type = 'button';
    d.title = label;
    d.setAttribute('aria-label', label);
    if (glyph) {
        const g = document.createElement('span');
        g.className = 'mac-dot-glyph';
        g.textContent = glyph;
        d.appendChild(g);
    }
    if (onClick) d.onclick = onClick;
    return d;
}

module.exports = { MacWindow };
