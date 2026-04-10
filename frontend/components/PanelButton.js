// PanelButton — a single session entry in the history sidebar

function PanelButton({ preview, sessionId, messageCount, active }, onClick) {
    const btn = document.createElement('button');
    btn.className = 'panel-button' + (active ? ' active' : '');
    btn.dataset.sessionId = sessionId;

    const icon = document.createElement('span');
    icon.className = 'panel-button-icon';
    icon.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`;

    const text = document.createElement('span');
    text.className = 'panel-button-text';
    text.textContent = preview;

    btn.appendChild(icon);
    btn.appendChild(text);

    btn.onclick = () => {
        if (onClick) onClick(sessionId);
    };

    return { element: btn };
}

module.exports = { PanelButton };
