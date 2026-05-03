// components/chrome/PermissionsCard.js
//
// A small, dismissible permission widget for Coworker mode. It follows the
// Emu design system instead of looking like a system alert.

const PERMISSION_COPY = {
    accessibility: {
        title: 'Accessibility',
        description: 'Allows Emu to read app interfaces and dispatch input.',
        glyph: 'accessibility',
    },
    screen: {
        title: 'Screen Recording',
        description: 'Lets Emu see the target window between actions.',
        glyph: 'screen',
    },
};

function PermissionsCard({
    missing = [],
    onAllow,
    onDismiss,
    onRecheck,
} = {}) {
    const overlay = document.createElement('div');
    overlay.className = 'permissions-overlay';
    overlay.tabIndex = -1;

    const card = document.createElement('div');
    card.className = 'permissions-card';
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-modal', 'false');
    overlay.appendChild(card);

    const header = document.createElement('div');
    header.className = 'permissions-header';

    const mark = document.createElement('div');
    mark.className = 'permissions-mark';
    mark.textContent = 'Emu';
    header.appendChild(mark);

    const headerText = document.createElement('div');
    headerText.className = 'permissions-header-text';

    const title = document.createElement('h2');
    title.className = 'permissions-title';
    title.id = 'permissions-card-title';
    title.textContent = 'Enable Emu Coworker Mode';
    card.setAttribute('aria-labelledby', title.id);
    headerText.appendChild(title);

    const subtitle = document.createElement('p');
    subtitle.className = 'permissions-subtitle';
    subtitle.textContent = 'Emu needs these permissions to control apps on your Mac. Permissions are only used while Coworker mode is running.';
    headerText.appendChild(subtitle);
    header.appendChild(headerText);

    const closeButton = document.createElement('button');
    closeButton.className = 'permissions-close';
    closeButton.type = 'button';
    closeButton.title = 'Dismiss';
    closeButton.textContent = '×';
    header.appendChild(closeButton);

    card.appendChild(header);

    const rows = document.createElement('div');
    rows.className = 'permissions-rows';
    card.appendChild(rows);

    const footer = document.createElement('div');
    footer.className = 'permissions-footer';
    footer.textContent = 'After allowing access in System Settings, return to Emu and this card will update automatically.';
    card.appendChild(footer);

    let currentMissing = _normaliseMissing(missing);
    let closed = false;
    let pollTimer = null;
    let successTimer = null;
    const waiting = new Set();
    const errors = new Map();

    function render() {
        rows.innerHTML = '';
        card.classList.toggle('all-set', currentMissing.length === 0);
        footer.hidden = currentMissing.length === 0;

        if (currentMissing.length === 0) {
            title.textContent = 'Coworker Mode is ready';
            subtitle.textContent = 'All required permissions are enabled.';
            const done = document.createElement('div');
            done.className = 'permissions-done';
            done.textContent = 'All set';
            rows.appendChild(done);
            return;
        }

        title.textContent = 'Enable Emu Coworker Mode';
        subtitle.textContent = 'Emu needs these permissions to control apps on your Mac. Permissions are only used while Coworker mode is running.';

        currentMissing.forEach((kind, index) => {
            const spec = PERMISSION_COPY[kind];
            if (!spec) return;

            const row = document.createElement('div');
            row.className = 'permissions-row';
            row.setAttribute('role', 'group');
            if (waiting.has(kind)) row.classList.add('waiting');
            if (errors.has(kind)) row.classList.add('errored');

            const icon = document.createElement('div');
            icon.className = 'permissions-icon';
            icon.setAttribute('aria-hidden', 'true');
            icon.innerHTML = _glyph(spec.glyph);
            row.appendChild(icon);

            const copy = document.createElement('div');
            copy.className = 'permissions-copy';

            const rowTitle = document.createElement('div');
            rowTitle.className = 'permissions-row-title';
            rowTitle.id = `permissions-row-${kind}-${index}`;
            rowTitle.textContent = spec.title;
            row.setAttribute('aria-labelledby', rowTitle.id);
            copy.appendChild(rowTitle);

            const rowDescription = document.createElement('div');
            rowDescription.className = 'permissions-row-description';
            rowDescription.textContent = spec.description;
            copy.appendChild(rowDescription);

            const rowStatus = document.createElement('div');
            rowStatus.className = 'permissions-row-status';
            if (errors.has(kind)) {
                rowStatus.textContent = errors.get(kind);
            } else if (waiting.has(kind)) {
                rowStatus.textContent = 'waiting for permission…';
            } else {
                rowStatus.textContent = 'not granted yet';
            }
            copy.appendChild(rowStatus);
            row.appendChild(copy);

            const button = document.createElement('button');
            button.className = 'permissions-button';
            button.type = 'button';
            button.disabled = waiting.has(kind);
            button.textContent = waiting.has(kind) ? 'Waiting' : 'Allow';
            button.addEventListener('click', () => allow(kind));
            row.appendChild(button);

            rows.appendChild(row);
        });
    }

    async function allow(kind) {
        errors.delete(kind);
        waiting.add(kind);
        render();

        try {
            const result = onAllow ? await onAllow(kind) : null;
            if (result && result.success === false) {
                throw new Error(result.error || 'Could not open System Settings');
            }
            startPolling();
        } catch (err) {
            waiting.delete(kind);
            errors.set(kind, err?.message || 'Could not open System Settings');
            render();
        }
    }

    function update(nextMissing) {
        if (closed) return;
        currentMissing = _normaliseMissing(nextMissing);
        for (const kind of Array.from(waiting)) {
            if (!currentMissing.includes(kind)) waiting.delete(kind);
        }
        for (const kind of Array.from(errors.keys())) {
            if (!currentMissing.includes(kind)) errors.delete(kind);
        }

        render();

        if (currentMissing.length === 0) {
            stopPolling();
            clearTimeout(successTimer);
            successTimer = setTimeout(close, 700);
        } else {
            clearTimeout(successTimer);
            if (waiting.size > 0) {
                startPolling();
            }
        }
    }

    async function pollOnce({ force = false } = {}) {
        if (closed || !onRecheck) return;
        if (!force && document.hasFocus && !document.hasFocus()) return;

        try {
            const result = await onRecheck();
            if (result && result.success === false) {
                return;
            }
            const nextMissing = result?.missing || result?.permissions?.missing || [];
            update(nextMissing);
        } catch (_) {
            // Keep the visible waiting state; the next poll/focus event can recover.
        }
    }

    function startPolling() {
        if (pollTimer || !onRecheck) return;
        pollTimer = setInterval(() => pollOnce(), 2000);
        if (pollTimer.unref) pollTimer.unref();
        window.addEventListener('focus', handleFocus);
    }

    function stopPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
        window.removeEventListener('focus', handleFocus);
    }

    function handleFocus() {
        pollOnce({ force: true });
    }

    function close() {
        if (closed) return;
        closed = true;
        clearTimeout(successTimer);
        stopPolling();
        overlay.remove();
        if (onDismiss) onDismiss();
    }

    overlay.addEventListener('click', (event) => {
        if (event.target === overlay) close();
    });
    closeButton.addEventListener('click', close);
    overlay.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            event.preventDefault();
            close();
        }
    });

    render();
    requestAnimationFrame(() => {
        if (!closed && document.body.contains(overlay)) {
            overlay.focus({ preventScroll: true });
        }
    });

    return {
        element: overlay,
        update,
        close,
    };
}

function _normaliseMissing(missing) {
    const raw = Array.isArray(missing) ? missing : [];
    const result = [];
    raw.forEach((item) => {
        const value = String(item || '').toLowerCase();
        let kind = null;
        if (value === 'accessibility' || value.includes('access')) {
            kind = 'accessibility';
        } else if (value === 'screen' || value === 'screenrecording' || value.includes('screen')) {
            kind = 'screen';
        }
        if (kind && !result.includes(kind)) result.push(kind);
    });
    return result;
}

function _glyph(kind) {
    if (kind === 'screen') {
        return `
            <svg viewBox="0 0 24 24" role="img" aria-label="Screen Recording">
                <rect x="4" y="5" width="16" height="11" rx="2.5"></rect>
                <path d="M9 20h6"></path>
                <path d="M12 16v4"></path>
            </svg>
        `;
    }
    return `
        <svg viewBox="0 0 24 24" role="img" aria-label="Accessibility">
            <circle cx="12" cy="5" r="2.25"></circle>
            <path d="M5.5 9.5h13"></path>
            <path d="M12 9.5v9"></path>
            <path d="M8 21l4-11.5L16 21"></path>
        </svg>
    `;
}

module.exports = { PermissionsCard };
