// StatusIndicator component — pulsing dot + text for async status messages

function StatusIndicator(text) {
    const indicator = document.createElement('div');
    indicator.className = 'status-indicator';
    indicator.id = 'status-indicator';

    const dot = document.createElement('span');
    dot.className = 'dot';
    indicator.appendChild(dot);

    const span = document.createElement('span');
    span.textContent = text || '';
    indicator.appendChild(span);

    return {
        element: indicator,
        setText(newText) {
            span.textContent = newText;
        },
    };
}

module.exports = { StatusIndicator };
