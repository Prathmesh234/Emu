// Header component — app title bar with window controls

const store = require('../state/store');

function Header({ onExpand, onClose, onNewTask }) {
    const header = document.createElement('div');
    header.className = 'header';

    // Left side: new task button + title
    const leftGroup = document.createElement('div');
    leftGroup.className = 'header-left';

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
    toggleWrap.title = 'Auto-approve all shell commands';

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

    // Dark mode toggle button (moon = light mode active, sun = dark mode active)
    const themeBtn = document.createElement('button');
    themeBtn.className = 'theme-btn';
    themeBtn.title = store.state.darkMode ? 'Switch to light mode' : 'Switch to dark mode';
    themeBtn.textContent = store.state.darkMode ? '\u2600\uFE0F' : '\uD83C\uDF19';
    themeBtn.onclick = () => {
        const newDark = !store.state.darkMode;
        store.setDarkMode(newDark);
        document.getElementById('app').classList.toggle('dark', newDark);
        themeBtn.textContent = newDark ? '\u2600\uFE0F' : '\uD83C\uDF19';
        themeBtn.title = newDark ? 'Switch to light mode' : 'Switch to dark mode';
    };
    actions.appendChild(themeBtn);

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
        setCompact(compact) {
            // In compact/side-panel mode, hide title text and toggle label
            emuText.style.display = compact ? 'none' : '';
            emuSvg.style.display = compact ? 'none' : '';
            toggleLabel.style.display = compact ? 'none' : '';
        },
    };
}

module.exports = { Header };
