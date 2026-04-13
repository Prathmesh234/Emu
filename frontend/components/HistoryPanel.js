// HistoryPanel — left sidebar showing past sessions

const { PanelButton } = require('./PanelButton');

function HistoryPanel({ onNewChat, onSelectSession, onToggle }) {
    const panel = document.createElement('div');
    panel.className = 'history-panel';

    // ── Header (always visible — contains hamburger) ───────────────────
    const header = document.createElement('div');
    header.className = 'history-panel-header';

    const title = document.createElement('span');
    title.className = 'history-panel-title';
    title.textContent = 'Emu';

    const hamburgerBtn = document.createElement('button');
    hamburgerBtn.className = 'history-panel-hamburger';
    hamburgerBtn.title = 'Toggle sidebar';
    hamburgerBtn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>`;
    hamburgerBtn.onclick = (e) => {
        e.stopPropagation();
        if (onToggle) onToggle();
    };

    header.appendChild(title);
    header.appendChild(hamburgerBtn);
    panel.appendChild(header);

    // ── Body (fades in when expanded) ─────────────────────────────────
    const body = document.createElement('div');
    body.className = 'history-panel-body';

    // ── New Chat button ────────────────────────────────────────────────
    const newChatBtn = document.createElement('button');
    newChatBtn.className = 'history-new-chat';
    newChatBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg><span>New chat</span>`;
    newChatBtn.onclick = () => { if (onNewChat) onNewChat(); };
    body.appendChild(newChatBtn);

    // ── Sessions list ──────────────────────────────────────────────────
    const sectionLabel = document.createElement('div');
    sectionLabel.className = 'history-section-label';
    sectionLabel.textContent = 'Recents';
    body.appendChild(sectionLabel);

    const list = document.createElement('div');
    list.className = 'history-list';
    body.appendChild(list);

    panel.appendChild(body);

    // Clicking anywhere on the collapsed strip expands it
    panel.onclick = () => {
        if (!panel.classList.contains('open')) {
            if (onToggle) onToggle();
        }
    };

    // ── State ──────────────────────────────────────────────────────────
    let activeSessionId = null;

    function setActive(sessionId) {
        activeSessionId = sessionId;
        list.querySelectorAll('.panel-button').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.sessionId === sessionId);
        });
    }

    function populate(sessions) {
        list.innerHTML = '';
        if (!sessions || sessions.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'history-empty';
            empty.textContent = 'No past sessions';
            list.appendChild(empty);
            return;
        }

        sessions.forEach(session => {
            const btn = PanelButton({
                preview: session.preview,
                sessionId: session.session_id,
                messageCount: session.message_count,
                active: session.session_id === activeSessionId,
            }, (sid) => {
                setActive(sid);
                if (onSelectSession) onSelectSession(sid);
            });
            list.appendChild(btn.element);
        });
    }

    return {
        element: panel,
        populate,
        setActive,
    };
}

module.exports = { HistoryPanel };
