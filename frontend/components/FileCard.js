// FileCard component — compact notification for file operations
// Clicking the filename opens a dialog showing file contents.

const fs = require('fs');
const { renderMarkdown } = require('./markdown');

function FileCard(filename, action, filepath) {
    const card = document.createElement('div');
    card.className = 'step-card file-card';

    const icon = document.createElement('span');
    icon.className = 'file-card-icon';
    icon.textContent = action === 'created' ? '\u{1F4C4}' : '\u270F\uFE0F';

    const left = document.createElement('div');
    left.className = 'file-card-left';
    left.appendChild(icon);

    const info = document.createElement('div');
    info.className = 'file-card-info';

    const label = document.createElement('span');
    label.className = 'file-card-label';
    label.textContent = action === 'created' ? 'File created' : 'File edited';
    info.appendChild(label);

    // Filename as a clickable button (only if filepath provided)
    const nameBtn = document.createElement('button');
    nameBtn.className = 'file-card-name' + (filepath ? ' file-card-name-clickable' : '');
    nameBtn.textContent = filename;
    nameBtn.disabled = !filepath;
    info.appendChild(nameBtn);

    left.appendChild(info);
    card.appendChild(left);

    if (filepath) {
        const viewBtn = document.createElement('button');
        viewBtn.className = 'file-card-view-btn';
        viewBtn.textContent = 'View';
        card.appendChild(viewBtn);

        const openDialog = () => showFileDialog(filename, filepath);
        nameBtn.addEventListener('click', openDialog);
        viewBtn.addEventListener('click', openDialog);
    }

    return { element: card };
}

function showFileDialog(filename, filepath) {
    // Overlay
    const overlay = document.createElement('div');
    overlay.className = 'file-dialog-overlay';

    const dialog = document.createElement('div');
    dialog.className = 'file-dialog';

    // Header
    const header = document.createElement('div');
    header.className = 'file-dialog-header';

    const title = document.createElement('span');
    title.className = 'file-dialog-title';
    title.textContent = filename;
    header.appendChild(title);

    const closeBtn = document.createElement('button');
    closeBtn.className = 'file-dialog-close';
    closeBtn.textContent = '✕';
    closeBtn.addEventListener('click', () => overlay.remove());
    header.appendChild(closeBtn);

    dialog.appendChild(header);

    // Content
    const body = document.createElement('div');
    body.className = 'file-dialog-body';

    try {
        const content = fs.readFileSync(filepath, 'utf-8');
        const isMarkdown = filename.toLowerCase().endsWith('.md');
        if (isMarkdown) {
            renderMarkdown(body, content);
        } else {
            const pre = document.createElement('pre');
            pre.className = 'file-dialog-raw';
            pre.textContent = content;
            body.appendChild(pre);
        }
    } catch (err) {
        body.textContent = `Could not read file: ${err.message}`;
        body.style.color = '#dc2626';
    }

    dialog.appendChild(body);
    overlay.appendChild(dialog);

    // Close on overlay click (outside dialog)
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.remove();
    });

    document.body.appendChild(overlay);
}

module.exports = { FileCard };
