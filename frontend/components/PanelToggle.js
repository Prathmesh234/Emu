// PanelToggle — hamburger button to open/close the history sidebar

function PanelToggle(onToggle) {
    const btn = document.createElement('button');
    btn.className = 'panel-toggle';
    btn.title = 'Toggle history';
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>`;

    btn.onclick = () => {
        if (onToggle) onToggle();
    };

    return { element: btn };
}

module.exports = { PanelToggle };
