const { getProviderSettings, getProviderModelOptions, saveProviderSettings } = require('../../services/api');

const RETRY_DELAYS_MS = [1200, 2500, 5000, 10000];

function createModelPicker() {
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
    let retryTimer = null;
    let retryAttempt = 0;

    function clearRetry() {
        if (retryTimer) {
            clearTimeout(retryTimer);
            retryTimer = null;
        }
    }

    function scheduleRetry() {
        clearRetry();
        const delay = RETRY_DELAYS_MS[Math.min(retryAttempt, RETRY_DELAYS_MS.length - 1)];
        retryAttempt += 1;
        retryTimer = setTimeout(() => {
            retryTimer = null;
            refresh();
        }, delay);
    }

    function resetRetry() {
        retryAttempt = 0;
        clearRetry();
    }

    function setBusy(nextBusy, className = '') {
        busy = nextBusy;
        wrap.classList.toggle('loading', className === 'loading');
        wrap.classList.toggle('saving', className === 'saving');
        wrap.classList.toggle('error', className === 'error');
        syncDisabled();
    }

    function syncDisabled() {
        button.disabled = locked || busy;
        wrap.classList.toggle('disabled', button.disabled);
        if (button.disabled) closeMenu();
    }

    function optionLabel(option) {
        return option.label || option.id;
    }

    function displayOption(option) {
        if (!option) {
            return { label: currentModel || 'no curated model', meta: '' };
        }
        return { label: optionLabel(option), meta: '' };
    }

    function setOpen(nextOpen) {
        open = nextOpen && !button.disabled;
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

            item.appendChild(itemLabel);
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
        clearRetry();
        setBusy(true, 'loading');
        try {
            const settings = await getProviderSettings();
            if (token !== refreshToken) return;

            currentProvider = settings.provider || '';
            currentModel = settings.model || '';

            let modelOptions = Array.isArray(settings.model_options) ? settings.model_options : [];
            let selectedModel = currentModel;
            try {
                const catalog = await getProviderModelOptions(currentProvider);
                if (token !== refreshToken) return;
                modelOptions = Array.isArray(catalog.models) ? catalog.models : modelOptions;
                selectedModel = catalog.model || selectedModel;
            } catch (catalogErr) {
                console.warn('[model-picker] model catalog endpoint failed; using provider settings:', catalogErr.message);
            }

            // If the catalog is empty but a model is selected, synthesize an option so
            // the picker is always interactive (e.g. Claude provider omits the catalog).
            if (!modelOptions.length && selectedModel) {
                modelOptions = [{ id: selectedModel, label: selectedModel, vision: true }];
            }

            renderOptions(modelOptions, selectedModel);
            resetRetry();
            setBusy(false);
        } catch (err) {
            if (token !== refreshToken) return;
            menu.replaceChildren();
            wrap.classList.remove('empty');
            selectedText.textContent = 'models unavailable';
            selectedMeta.textContent = '';
            selectedMeta.hidden = true;
            wrap.title = err.message || 'Could not load model catalog';
            currentOptions = [];
            setBusy(false, 'error');
            scheduleRetry();
        }
    }

    async function selectModel(nextModel) {
        if (!nextModel || !currentProvider || nextModel === currentModel) return;
        refreshToken++;
        // Pessimistic update — keep displaying the previous model until the
        // backend confirms the switch, so the picker label can never claim a
        // model that isn't actually running yet.
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
                detail: { provider: currentProvider, model: currentModel, source: 'model-picker' },
            }));
            setBusy(false);
        } catch (err) {
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
        if (event.detail?.source === 'model-picker') return;
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

module.exports = { createModelPicker };
