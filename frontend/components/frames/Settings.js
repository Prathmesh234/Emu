// components/frames/Settings.js — Settings modal
//
// Part of the Emu Design System v1 refactor (see FRONTEND_REDESIGN.md).
// Design source: Emu-handoff.zip → project/frames/frames-b.jsx > F_Settings
//
// Grouped rows (Account / Behavior / Appearance) in a centered modal.
// Each row is a label + italic-serif interactive value. Modal dismisses
// on outside click, ×, or Esc.
//
// Hooks into the same store mutations the chrome bar used to call,
// so we can move the controls here and out of the chrome bar later.

const store = require('../../state/store');

function Settings({ onClose }) {
    const overlay = document.createElement('div');
    overlay.className = 'settings-overlay';

    const dialog = document.createElement('div');
    dialog.className = 'settings-dialog';
    overlay.appendChild(dialog);

    // ── Header ─────────────────────────────────────────────────────────────
    const header = document.createElement('div');
    header.className = 'settings-header';

    const h = document.createElement('h2');
    h.className = 'settings-title';
    h.textContent = 'Settings';
    header.appendChild(h);

    const closeBtn = document.createElement('button');
    closeBtn.className = 'settings-close';
    closeBtn.textContent = '×';
    closeBtn.title = 'Close';
    header.appendChild(closeBtn);

    dialog.appendChild(header);

    // ── Body ───────────────────────────────────────────────────────────────
    const body = document.createElement('div');
    body.className = 'settings-body';
    dialog.appendChild(body);

    // Section: Account
    body.appendChild(_section('Account'));
    const group1 = _group();
    group1.appendChild(_row('User', _displayName()));
    body.appendChild(group1);

    // Section: Behavior
    body.appendChild(_section('Behavior'));
    const group2 = _group();

    const dangerRow = _row(
        'Dangerous mode',
        store.state.dangerousMode ? 'on' : 'off',
        { action: true },
    );
    dangerRow.val.addEventListener('click', () => {
        const next = !store.state.dangerousMode;
        store.setDangerousMode(next);
        dangerRow.val.textContent = next ? 'on' : 'off';
        // Keep the chrome-bar danger slider visually in sync (mirrors the
        // theme-toggle pattern below: settings is the single source of truth,
        // but the chrome bar shows the live value too).
        const dangerWrap = document.querySelector('.mac-danger-wrap');
        if (dangerWrap) {
            dangerWrap.classList.toggle('active', next);
            const input = dangerWrap.querySelector('input[type="checkbox"]');
            if (input) input.checked = next;
        }
    });
    group2.appendChild(dangerRow.row);
    body.appendChild(group2);

    // Section: Appearance
    body.appendChild(_section('Appearance'));
    const group3 = _group();

    const themeRow = _row(
        'Theme',
        store.state.darkMode ? 'ink' : 'linen',
        { action: true },
    );
    themeRow.val.addEventListener('click', () => {
        const next = !store.state.darkMode;
        store.setDarkMode(next);
        document.body.classList.toggle('ink', next);
        themeRow.val.textContent = next ? 'ink' : 'linen';
        // Also update the chrome theme button glyph if present
        const themeBtn = document.querySelector('.mac-action-btn.theme-toggle');
        if (themeBtn) themeBtn.textContent = next ? '☀' : '☽';
    });
    group3.appendChild(themeRow.row);
    body.appendChild(group3);

    // ── Dismiss handlers ──────────────────────────────────────────────────
    function close() {
        overlay.remove();
        document.removeEventListener('keydown', onKey);
        if (onClose) onClose();
    }

    function onKey(e) { if (e.key === 'Escape') close(); }

    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    closeBtn.addEventListener('click', close);
    document.addEventListener('keydown', onKey);

    return { element: overlay, close };
}

// ── Private builders ─────────────────────────────────────────────────────

function _section(label) {
    const el = document.createElement('div');
    el.className = 'settings-section-label';
    el.textContent = label;
    return el;
}

function _group() {
    const el = document.createElement('div');
    el.className = 'settings-group';
    return el;
}

function _row(label, value, opts = {}) {
    const row = document.createElement('div');
    row.className = 'settings-row';

    const k = document.createElement('span');
    k.className = 'settings-row-label';
    k.textContent = label;

    const v = document.createElement('span');
    v.className = 'settings-row-value' + (opts.action ? ' action' : '');
    v.textContent = value;

    row.appendChild(k);
    row.appendChild(v);

    return { row, val: v };
}

function _displayName() {
    const raw = (typeof process !== 'undefined' && process.env && process.env.USER) || '';
    if (!raw) return 'you';
    return raw.charAt(0).toUpperCase() + raw.slice(1);
}

module.exports = { Settings };
