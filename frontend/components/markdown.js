/**
 * markdown.js — lightweight inline markdown → HTML renderer.
 *
 * Handles: **bold**, *italic*, `inline code`, ```code blocks```,
 * ## headings, - lists, [ ] / [x] checkboxes, [links](url), --- hr.
 *
 * Returns sanitised HTML string (no raw user URLs executed).
 */

function md(text) {
    if (!text) return '';

    // Escape HTML entities first
    let html = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

    // Fenced code blocks (``` ... ```)
    html = html.replace(/```[\s\S]*?```/g, match => {
        const inner = match.slice(3, -3).replace(/^\w*\n/, ''); // strip optional language tag
        return `<pre class="md-code-block">${inner}</pre>`;
    });

    // Process line by line for block-level elements
    const lines = html.split('\n');
    const out = [];
    let inList = false;

    for (let i = 0; i < lines.length; i++) {
        let line = lines[i];

        // Headings: ## ... or ### ...
        const headingMatch = line.match(/^(#{1,4})\s+(.+)$/);
        if (headingMatch) {
            if (inList) { out.push('</ul>'); inList = false; }
            const level = headingMatch[1].length;
            out.push(`<div class="md-h${level}">${inline(headingMatch[2])}</div>`);
            continue;
        }

        // Horizontal rule
        if (/^-{3,}$/.test(line.trim())) {
            if (inList) { out.push('</ul>'); inList = false; }
            out.push('<hr class="md-hr">');
            continue;
        }

        // Checkbox list items: - [ ] or - [x] or numbered with checkbox
        const checkMatch = line.match(/^(\s*)(?:[-*]|\d+[.)]) \[([ xX])\]\s+(.+)$/);
        if (checkMatch) {
            if (!inList) { out.push('<ul class="md-list md-checklist">'); inList = true; }
            const checked = checkMatch[2].toLowerCase() === 'x';
            const icon = checked
                ? '<span class="md-check done">&#10003;</span>'
                : '<span class="md-check pending">&#9744;</span>';
            out.push(`<li class="md-check-item${checked ? ' checked' : ''}">${icon} ${inline(checkMatch[3])}</li>`);
            continue;
        }

        // Bullet / numbered list items: - item, * item, 1. item
        const listMatch = line.match(/^(\s*)(?:[-*]|\d+[.)]) (.+)$/);
        if (listMatch) {
            if (!inList) { out.push('<ul class="md-list">'); inList = true; }
            out.push(`<li>${inline(listMatch[2])}</li>`);
            continue;
        }

        // Regular line
        if (inList) { out.push('</ul>'); inList = false; }

        if (line.trim() === '') {
            out.push('<div class="md-spacer"></div>');
        } else {
            out.push(`<div>${inline(line)}</div>`);
        }
    }

    if (inList) out.push('</ul>');

    return out.join('\n');
}

/** Inline markdown: bold, italic, code, links */
function inline(text) {
    return text
        // Inline code
        .replace(/`([^`]+)`/g, '<code class="md-inline-code">$1</code>')
        // Bold + italic
        .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
        // Bold
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        // Italic
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        // Links [text](url)
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<span class="md-link" title="$2">$1</span>');
}

/**
 * Render markdown into a DOM element.
 * Sets innerHTML with parsed markdown.
 */
function renderMarkdown(el, text) {
    el.innerHTML = md(text);
}

module.exports = { md, renderMarkdown };
