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
const { ipcRenderer } = require('electron');
const { getProviderSettings, saveProviderSettings } = require('../../services/api');

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
    group1.appendChild(_row('User', _displayName()).row);
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

    // Section: System checks
    body.appendChild(_section('System Checks'));
    const groupChecks = _group();

    const screenCheck = _systemCheckRow('Screen Recording', 'checking…', () => ipcRenderer.invoke('permissions:open', 'screen'));
    const accessibilityCheck = _systemCheckRow('Accessibility', 'checking…', () => ipcRenderer.invoke('permissions:open', 'accessibility'));
    const daemonCheck = _systemCheckRow('Memory daemon', 'checking…');
    groupChecks.appendChild(screenCheck.row);
    groupChecks.appendChild(accessibilityCheck.row);
    groupChecks.appendChild(daemonCheck.row);

    const checkActions = _actionRow([
        { label: 'refresh', onClick: refreshSystemChecks },
        { label: 'repair daemon', onClick: repairDaemon },
    ]);
    groupChecks.appendChild(checkActions.row);
    body.appendChild(groupChecks);

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

    // Section: Model
    body.appendChild(_section('Model'));
    const group4 = _group();

    const providerRow = _row('Provider', '');
    const providerSelect = _select([]);
    providerRow.val.replaceWith(providerSelect);
    group4.appendChild(providerRow.row);

    const modelRow = _row('Model', '');
    const modelInput = _input('text', '');
    modelRow.val.replaceWith(modelInput);
    group4.appendChild(modelRow.row);

    const keyRow = _row('API Key', '');
    const keyInput = _input('password', '');
    keyRow.val.replaceWith(keyInput);
    group4.appendChild(keyRow.row);

    const saveRow = document.createElement('div');
    saveRow.className = 'settings-row settings-save-row';
    const saveBtn = document.createElement('button');
    saveBtn.className = 'settings-save-btn';
    saveBtn.textContent = 'save changes';
    const saveStatus = document.createElement('span');
    saveStatus.className = 'settings-save-status';
    saveRow.appendChild(saveStatus);
    saveRow.appendChild(saveBtn);
    group4.appendChild(saveRow);

    body.appendChild(group4);

    // Populate provider select and pre-fill current values
    let _defaultModels = {};
    getProviderSettings().then((data) => {
        _defaultModels = data.default_models || {};
        const providers = data.providers || [];
        providers.forEach((p) => {
            const opt = document.createElement('option');
            opt.value = p;
            opt.textContent = p;
            if (p === data.provider) opt.selected = true;
            providerSelect.appendChild(opt);
        });
        modelInput.value = data.model || '';
        // Don't pre-fill API key — user must re-enter to change it
        if (data.api_key_set) keyInput.placeholder = data.api_key_preview || '••••••••';
    }).catch(() => {
        const opt = document.createElement('option');
        opt.textContent = 'unavailable';
        providerSelect.appendChild(opt);
    });

    providerSelect.addEventListener('change', () => {
        const selected = providerSelect.value;
        modelInput.value = _defaultModels[selected] || '';
        keyInput.value = '';
        keyInput.placeholder = '';
        saveStatus.textContent = '';
    });

    saveBtn.addEventListener('click', async () => {
        const provider = providerSelect.value;
        const model = modelInput.value.trim();
        const apiKey = keyInput.value.trim();
        saveBtn.disabled = true;
        saveStatus.textContent = 'saving…';
        saveStatus.className = 'settings-save-status';
        try {
            await saveProviderSettings({ provider, model, apiKey });
            saveStatus.textContent = 'saved';
            saveStatus.className = 'settings-save-status ok';
            keyInput.value = '';
            if (apiKey) keyInput.placeholder = '••••••••';
        } catch (err) {
            saveStatus.textContent = err.message || 'error';
            saveStatus.className = 'settings-save-status err';
        } finally {
            saveBtn.disabled = false;
        }
    });

    async function refreshSystemChecks() {
        checkActions.setDisabled(true);
        checkActions.status.textContent = 'checking…';
        checkActions.status.className = 'settings-save-status';
        try {
            const [permissions, daemon] = await Promise.all([
                ipcRenderer.invoke('permissions:status'),
                ipcRenderer.invoke('daemon:status'),
            ]);
            screenCheck.setValue(_permissionLabel(permissions.screenRecording));
            accessibilityCheck.setValue(_permissionLabel(permissions.accessibility));
            daemonCheck.setValue(_daemonLabel(daemon));
            checkActions.status.textContent = 'updated';
            checkActions.status.className = 'settings-save-status ok';
        } catch (err) {
            checkActions.status.textContent = err.message || 'could not check';
            checkActions.status.className = 'settings-save-status err';
        } finally {
            checkActions.setDisabled(false);
        }
    }

    async function repairDaemon() {
        checkActions.setDisabled(true);
        checkActions.status.textContent = 'repairing…';
        checkActions.status.className = 'settings-save-status';
        try {
            const result = await ipcRenderer.invoke('daemon:repair');
            if (!result.ok) throw new Error(result.stderr || 'repair failed');
            checkActions.status.textContent = 'daemon repaired';
            checkActions.status.className = 'settings-save-status ok';
            await refreshSystemChecks();
        } catch (err) {
            checkActions.status.textContent = err.message || 'repair failed';
            checkActions.status.className = 'settings-save-status err';
        } finally {
            checkActions.setDisabled(false);
        }
    }

    refreshSystemChecks();

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

function _systemCheckRow(label, value, onOpen) {
    const item = _row(label, value, { action: Boolean(onOpen) });
    if (onOpen) {
        item.val.title = `Open ${label} settings`;
        item.val.addEventListener('click', onOpen);
    }
    return {
        row: item.row,
        setValue(next) { item.val.textContent = next; },
    };
}

function _actionRow(actions) {
    const row = document.createElement('div');
    row.className = 'settings-row settings-save-row';
    const status = document.createElement('span');
    status.className = 'settings-save-status';
    row.appendChild(status);

    const buttons = actions.map(({ label, onClick }) => {
        const button = document.createElement('button');
        button.className = 'settings-save-btn';
        button.textContent = label;
        button.addEventListener('click', onClick);
        row.appendChild(button);
        return button;
    });

    return {
        row,
        status,
        setDisabled(disabled) { buttons.forEach((button) => { button.disabled = disabled; }); },
    };
}

function _select(options) {
    const el = document.createElement('select');
    el.className = 'settings-row-select';
    options.forEach((o) => {
        const opt = document.createElement('option');
        opt.value = o;
        opt.textContent = o;
        el.appendChild(opt);
    });
    return el;
}

function _input(type, placeholder) {
    const el = document.createElement('input');
    el.type = type;
    el.className = 'settings-row-input';
    el.placeholder = placeholder;
    el.autocomplete = 'off';
    return el;
}

function _displayName() {
    const raw = (typeof process !== 'undefined' && process.env && process.env.USER) || '';
    if (!raw) return 'you';
    return raw.charAt(0).toUpperCase() + raw.slice(1);
}

function _permissionLabel(value) {
    if (value === true || value === 'granted') return 'granted';
    if (value === 'not-determined') return 'not granted';
    if (value === 'unsupported') return 'not needed';
    if (!value || value === 'unknown') return 'unknown';
    return String(value).replace(/-/g, ' ');
}

function _daemonLabel(status) {
    if (!status) return 'unknown';
    if (status.platform && status.platform !== 'darwin') return 'not needed';
    if (status.loaded && status.current) return 'loaded';
    if (status.loaded) return 'needs repair';
    if (status.plistPresent) return 'installed';
    return 'not installed';
}

module.exports = { Settings };
