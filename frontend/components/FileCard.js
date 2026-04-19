// FileCard — inline file-written notification in Trace style
//
// Part of the Emu Design System v1 refactor (see FRONTEND_REDESIGN.md).
// Design source: Emu-handoff.zip → project/frames/chrome.jsx > Trace
//
// Design change: replaces the old file card (icon + label + view button)
// with a single trace line containing an underlined clickable filename.
// The file dialog (full-screen overlay) is preserved unchanged.
// Same function signature: FileCard(filename, action, filepath).

const fs = require('fs');
const { renderMarkdown } = require('./markdown');

function FileCard(filename, action, filepath) {
    const wrap = document.createElement('div');
    wrap.className = 'trace';

    const verb = action === 'created' ? 'created' : 'updated';

    const textNode = document.createTextNode(verb + ' ');
    wrap.appendChild(textNode);

    if (filepath) {
        const link = document.createElement('span');
        link.className = 'trace-file-link';
        link.textContent = filename;
        link.addEventListener('click', () => showFileDialog(filename, filepath));
        wrap.appendChild(link);
    } else {
        const span = document.createElement('span');
        span.textContent = filename;
        wrap.appendChild(span);
    }

    return { element: wrap };
}

// ── File dialog (visual design updated, functionality unchanged) ──────────

function showFileDialog(filename, filepath) {
    const overlay = document.createElement('div');
    overlay.className = 'file-dialog-overlay';

    const dialog = document.createElement('div');
    dialog.className = 'file-dialog';

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

    const body = document.createElement('div');
    body.className = 'file-dialog-body';

    try {
        const content = fs.readFileSync(filepath, 'utf-8');
        if (filename.toLowerCase().endsWith('.md')) {
            renderMarkdown(body, content);
        } else {
            const pre = document.createElement('pre');
            pre.className = 'file-dialog-raw';
            pre.textContent = content;
            body.appendChild(pre);
        }
    } catch (err) {
        body.textContent = `Could not read file: ${err.message}`;
    }

    dialog.appendChild(body);
    overlay.appendChild(dialog);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);
}

module.exports = { FileCard };
