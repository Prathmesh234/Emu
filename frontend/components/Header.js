// Header component — app title bar with window controls

const store = require('../state/store');

function Header({ onExpand, onClose }) {
    const header = document.createElement('div');
    header.className = 'header';

    const h1 = document.createElement('h1');
    h1.textContent = '\u{1F9A4} Emu';

    const actions = document.createElement('div');
    actions.className = 'header-actions';

    // Dangerous mode toggle
    const toggleWrap = document.createElement('label');
    toggleWrap.className = 'danger-toggle';
    toggleWrap.title = 'Auto-approve all shell commands (dangerous)';

    const toggleInput = document.createElement('input');
    toggleInput.type = 'checkbox';
    toggleInput.checked = store.state.dangerousMode;
    toggleInput.addEventListener('change', () => {
        store.setDangerousMode(toggleInput.checked);
        toggleLabel.textContent = toggleInput.checked ? '--dangerous' : '--safe';
        toggleWrap.classList.toggle('active', toggleInput.checked);
    });

    const toggleSlider = document.createElement('span');
    toggleSlider.className = 'danger-slider';

    const toggleLabel = document.createElement('span');
    toggleLabel.className = 'danger-label';
    toggleLabel.textContent = store.state.dangerousMode ? '--dangerous' : '--safe';

    toggleWrap.appendChild(toggleInput);
    toggleWrap.appendChild(toggleSlider);
    toggleWrap.appendChild(toggleLabel);
    if (store.state.dangerousMode) toggleWrap.classList.add('active');
    actions.appendChild(toggleWrap);

    // Expand button (hidden by default, shown when in side panel)
    const expandBtn = document.createElement('button');
    expandBtn.className = 'expand-btn';
    expandBtn.textContent = 'Expand';
    expandBtn.style.display = 'none';
    if (onExpand) expandBtn.onclick = onExpand;
    actions.appendChild(expandBtn);

    // Close button
    const closeBtn = document.createElement('button');
    closeBtn.className = 'close-btn';
    closeBtn.textContent = '\u2715';
    if (onClose) closeBtn.onclick = onClose;
    actions.appendChild(closeBtn);

    header.appendChild(h1);
    header.appendChild(actions);

    return {
        element: header,
        expandBtn,
        toggleInput,
        setExpandVisible(visible) {
            expandBtn.style.display = visible ? 'block' : 'none';
        },
        setToggleDisabled(disabled) {
            toggleInput.disabled = disabled;
            toggleWrap.classList.toggle('disabled', disabled);
        },
    };
}

module.exports = { Header };
