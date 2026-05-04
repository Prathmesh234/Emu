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
const { getProviderSettings, getProviderModelOptions, saveProviderSettings } = require('../../services/api');

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

function _createModelPicker() {
    const wrap = document.createElement('div');
    wrap.className = 'window-model-picker loading';
    wrap.title = 'Loading model catalog';

    const label = document.createElement('span');
    label.className = 'window-model-label';
    label.textContent = 'model';
    wrap.appendChild(label);

    const button = document.createElement('button');
    button.className = 'window-model-button';
    button.type = 'button';
    button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-label', 'Model');

    const selectedText = document.createElement('span');
    selectedText.className = 'window-model-selected';
    selectedText.textContent = 'loading';

    const selectedMeta = document.createElement('span');
    selectedMeta.className = 'window-model-selected-meta';

    button.appendChild(selectedText);
    button.appendChild(selectedMeta);
    wrap.appendChild(button);

    const state = document.createElement('span');
    state.className = 'window-model-state';
    wrap.appendChild(state);

    const menu = document.createElement('div');
    menu.className = 'window-model-menu';
    menu.setAttribute('role', 'listbox');
    menu.hidden = true;
    wrap.appendChild(menu);

    let currentProvider = '';
    let currentModel = '';
    let currentOptions = [];
    let busy = false;
    let locked = false;
    let open = false;
    let refreshToken = 0;

    function setBusy(nextBusy, className = '') {
        busy = nextBusy;
        wrap.classList.toggle('loading', className === 'loading');
        wrap.classList.toggle('saving', className === 'saving');
        wrap.classList.toggle('error', className === 'error');
        syncDisabled();
    }

    function syncDisabled() {
        button.disabled = locked || busy || currentOptions.length === 0;
        wrap.classList.toggle('disabled', button.disabled);
        if (button.disabled) closeMenu();
    }

    function optionLabel(option) {
        return option.label || option.id;
    }

    function optionMeta(option) {
        if (option.parameters && option.parameters !== 'undisclosed') {
            return option.parameters;
        }
        if (option.context) return option.context;
        if (option.parameters) return option.parameters;
        return '';
    }

    function displayOption(option) {
        if (!option) {
            return { label: currentModel || 'no curated model', meta: '' };
        }
        return { label: optionLabel(option), meta: optionMeta(option) };
    }

    function setOpen(nextOpen) {
        open = nextOpen && !button.disabled && currentOptions.length > 0;
        menu.hidden = !open;
        wrap.classList.toggle('open', open);
        button.setAttribute('aria-expanded', String(open));
    }

    function closeMenu() {
        setOpen(false);
    }

    function updateTitle() {
        const active = currentOptions.find((option) => option.id === currentModel);
        if (active) {
            wrap.title = active.description || `${currentProvider}: ${currentModel}`;
        } else if (currentOptions.length) {
            wrap.title = `${currentProvider}: ${currentModel}`;
        } else {
            wrap.title = currentProvider
                ? `${currentProvider}: no curated vision model in the catalog`
                : 'No curated vision model in the catalog';
        }
    }

    function renderButton(active) {
        const display = displayOption(active);
        selectedText.textContent = display.label;
        selectedMeta.textContent = display.meta;
        selectedMeta.hidden = !display.meta;
    }

    function menuMeta(option) {
        const parts = [];
        const meta = optionMeta(option);
        if (meta) parts.push(meta);
        if (option.pricing?.input_per_m != null && option.pricing?.output_per_m != null) {
            parts.push(`$${option.pricing.input_per_m}/$${option.pricing.output_per_m}`);
        }
        return parts.join(' - ');
    }

    function renderMenu(options) {
        menu.replaceChildren();
        options.forEach((option) => {
            const item = document.createElement('button');
            item.className = 'window-model-menu-option';
            item.type = 'button';
            item.dataset.model = option.id;
            item.setAttribute('role', 'option');
            item.setAttribute('aria-selected', String(option.id === currentModel));

            const itemLabel = document.createElement('span');
            itemLabel.className = 'window-model-menu-label';
            itemLabel.textContent = optionLabel(option);

            const itemMeta = document.createElement('span');
            itemMeta.className = 'window-model-menu-meta';
            itemMeta.textContent = menuMeta(option);

            item.appendChild(itemLabel);
            if (itemMeta.textContent) item.appendChild(itemMeta);
            item.addEventListener('click', () => {
                closeMenu();
                selectModel(option.id);
            });
            menu.appendChild(item);
        });
    }

    function renderOptions(options, selectedModel) {
        currentOptions = Array.isArray(options) ? options : [];
        currentModel = selectedModel || currentModel || '';
        menu.replaceChildren();

        if (!currentOptions.length) {
            wrap.classList.add('empty');
            renderButton(null);
            updateTitle();
            syncDisabled();
            return;
        }

        wrap.classList.remove('empty');
        let menuOptions = currentOptions;
        const hasCurrent = currentOptions.some((option) => option.id === currentModel);
        if (currentModel && !hasCurrent) {
            menuOptions = [
                {
                    id: currentModel,
                    label: `Current - ${currentModel}`,
                    description: currentModel,
                    vision: true,
                },
                ...currentOptions,
            ];
        }

        currentModel = currentModel || currentOptions[0].id;
        const active = menuOptions.find((option) => option.id === currentModel) || currentOptions[0];
        renderButton(active);
        renderMenu(menuOptions);
        updateTitle();
        syncDisabled();
    }

    async function refresh() {
        const token = ++refreshToken;
        setBusy(true, 'loading');
        try {
            const settings = await getProviderSettings();
            if (token !== refreshToken) return;
            currentProvider = settings.provider || '';
            currentModel = settings.model || '';
            const catalog = await getProviderModelOptions(currentProvider);
            if (token !== refreshToken) return;
            renderOptions(catalog.models || settings.model_options || [], catalog.model || currentModel);
            setBusy(false);
        } catch (err) {
            if (token !== refreshToken) return;
            menu.replaceChildren();
            selectedText.textContent = 'models unavailable';
            selectedMeta.textContent = '';
            selectedMeta.hidden = true;
            wrap.title = err.message || 'Could not load model catalog';
            currentOptions = [];
            setBusy(false, 'error');
        }
    }

    async function selectModel(nextModel) {
        if (!nextModel || !currentProvider || nextModel === currentModel) return;
        refreshToken++;
        const previousModel = currentModel;
        currentModel = nextModel;
        renderOptions(currentOptions, currentModel);
        setBusy(true, 'saving');
        try {
            const result = await saveProviderSettings({
                provider: currentProvider,
                model: nextModel,
                apiKey: '',
            });
            currentModel = result.model || nextModel;
            renderOptions(currentOptions, currentModel);
            window.dispatchEvent(new CustomEvent('emu-provider-settings-changed', {
                detail: { provider: currentProvider, model: currentModel, source: 'header' },
            }));
            setBusy(false);
        } catch (err) {
            currentModel = previousModel;
            renderOptions(currentOptions, currentModel);
            wrap.title = err.message || 'Could not save model';
            setBusy(false, 'error');
        }
    }

    button.addEventListener('click', () => setOpen(!open));
    window.addEventListener('click', (event) => {
        if (!wrap.contains(event.target)) closeMenu();
    });
    window.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') closeMenu();
    });
    window.addEventListener('emu-provider-settings-changed', (event) => {
        if (event.detail?.source === 'header') return;
        refresh();
    });

    refresh();

    return {
        element: wrap,
        setDisabled(disabled) {
            locked = disabled;
            if (disabled) {
                wrap.title = 'Model is locked while Emu is working';
            } else {
                updateTitle();
            }
            syncDisabled();
        },
        refresh,
    };
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

    // Center group: model picker + agent mode toggle
    const center = document.createElement('div');
    center.className = 'window-header-center';

    const modelPicker = _createModelPicker();
    const modeToggle = _createModeToggle();
    center.appendChild(modelPicker.element);
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

        setModelDisabled(disabled) {
            modelPicker.setDisabled(disabled);
        },
    };
}

module.exports = { WindowHeader };
