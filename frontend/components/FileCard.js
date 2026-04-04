// FileCard component — compact notification for file operations

function FileCard(filename, action) {
    const card = document.createElement('div');
    card.className = 'step-card file-card';

    const icon = document.createElement('span');
    icon.className = 'file-card-icon';
    icon.textContent = action === 'created' ? '\u{1F4C4}' : '\u{270F}\u{FE0F}';

    const text = document.createElement('span');
    text.className = 'file-card-text';
    text.textContent = `${filename} has been ${action}`;

    card.appendChild(icon);
    card.appendChild(text);

    return { element: card };
}

module.exports = { FileCard };
