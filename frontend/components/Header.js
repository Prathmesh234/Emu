// Header component — app title bar with window controls

function Header({ onExpand, onClose }) {
    const header = document.createElement('div');
    header.className = 'header';

    const h1 = document.createElement('h1');
    h1.textContent = '\u{1F9A4} Emu';

    const actions = document.createElement('div');
    actions.className = 'header-actions';

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
        setExpandVisible(visible) {
            expandBtn.style.display = visible ? 'block' : 'none';
        },
    };
}

module.exports = { Header };
