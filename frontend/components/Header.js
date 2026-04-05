// Header component — app title bar with window controls

const store = require('../state/store');

function Header({ onExpand, onClose, onNewTask }) {
    const header = document.createElement('div');
    header.className = 'header';

    // Left side: new task button + title
    const leftGroup = document.createElement('div');
    leftGroup.className = 'header-left';

    // + New Task button
    const newTaskBtn = document.createElement('button');
    newTaskBtn.className = 'new-task-btn';
    newTaskBtn.textContent = '+';
    newTaskBtn.title = 'Start a new task';
    newTaskBtn.onclick = () => {
        if (store.state.isGenerating) {
            // Show disclaimer tooltip that the task will be queued
            const disclaimer = document.createElement('div');
            disclaimer.className = 'queue-disclaimer';
            disclaimer.textContent = 'A task is currently running. Your new task will be queued and start after the current one finishes.';
            newTaskBtn.parentElement.appendChild(disclaimer);
            // Auto-remove after 4s
            setTimeout(() => disclaimer.remove(), 4000);
        }
        if (onNewTask) onNewTask();
    };
    leftGroup.appendChild(newTaskBtn);

    const h1 = document.createElement('h1');
    const emuSvg = document.createElement('span');
    emuSvg.className = 'emu-icon';
    emuSvg.innerHTML = '<svg width="20" height="20" viewBox="0 0 40 36" fill="none" class="emu-static-svg"><g><path class="emu-main-stroke" d="M14 18 Q12 10 10 5 Q9 3 10 2" stroke-width="2.2" stroke-linecap="round" fill="none"/><circle class="emu-main-fill" cx="9" cy="2.5" r="2.5"/><path class="emu-accent-fill" d="M6.5 2.5 L3 3.5 L6.5 4"/><circle cx="8.2" cy="1.8" r="0.7" fill="#fff"/><ellipse class="emu-main-fill" cx="20" cy="20" rx="9" ry="6"/><path class="emu-main-stroke" d="M29 18 Q33 14 32 11" stroke-width="2" stroke-linecap="round" fill="none"/><path class="emu-main-stroke" d="M28 19 Q34 16 34 13" stroke-width="1.8" stroke-linecap="round" fill="none"/></g><path class="emu-accent-stroke" d="M18 25 L16 33 L13 33" stroke-width="1.8" stroke-linecap="round" fill="none"/><path class="emu-accent-stroke" d="M22 25 L20 33 L17 33" stroke-width="1.8" stroke-linecap="round" fill="none"/></svg>';
    h1.appendChild(emuSvg);
    const emuText = document.createElement('span');
    emuText.textContent = 'Emu';
    h1.appendChild(emuText);
    leftGroup.appendChild(h1);

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
    expandBtn.title = 'Expand window';
    expandBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>';
    expandBtn.style.display = 'none';
    if (onExpand) expandBtn.onclick = onExpand;
    actions.appendChild(expandBtn);

    // Dark mode toggle (moon/sun)
    const darkBtn = document.createElement('button');
    darkBtn.className = 'dark-mode-btn';
    darkBtn.title = 'Toggle dark mode';
    const moonSVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
    const sunSVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>';
    darkBtn.innerHTML = store.state.darkMode ? sunSVG : moonSVG;
    darkBtn.onclick = () => {
        const newMode = !store.state.darkMode;
        store.setDarkMode(newMode);
        darkBtn.innerHTML = newMode ? sunSVG : moonSVG;
        darkBtn.title = newMode ? 'Switch to light mode' : 'Toggle dark mode';
    };
    actions.appendChild(darkBtn);

    // Close button
    const closeBtn = document.createElement('button');
    closeBtn.className = 'close-btn';
    closeBtn.textContent = '\u2715';
    if (onClose) closeBtn.onclick = onClose;
    actions.appendChild(closeBtn);

    header.appendChild(leftGroup);
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
