// HistoryPanel — left sidebar showing past sessions

const { PanelButton } = require('./PanelButton');

function HistoryPanel({ onNewChat, onSelectSession, onClose }) {
    const panel = document.createElement('div');
    panel.className = 'history-panel';

    // ── Header ─────────────────────────────────────────────────────────
    const header = document.createElement('div');
    header.className = 'history-panel-header';

    const title = document.createElement('span');
    title.className = 'history-panel-title';
    title.textContent = 'Emu';

    const closeBtn = document.createElement('button');
    closeBtn.className = 'history-panel-close';
    closeBtn.title = 'Close sidebar';
    closeBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
    closeBtn.onclick = () => { if (onClose) onClose(); };

    header.appendChild(title);
    header.appendChild(closeBtn);
    panel.appendChild(header);

    // ── New Chat button ────────────────────────────────────────────────
    const newChatBtn = document.createElement('button');
    newChatBtn.className = 'history-new-chat';
    newChatBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg><span>New chat</span>`;
    newChatBtn.onclick = () => { if (onNewChat) onNewChat(); };
    panel.appendChild(newChatBtn);

    // ── Sessions list ──────────────────────────────────────────────────
    const sectionLabel = document.createElement('div');
    sectionLabel.className = 'history-section-label';
    sectionLabel.textContent = 'Recents';
    panel.appendChild(sectionLabel);

    const list = document.createElement('div');
    list.className = 'history-list';
    panel.appendChild(list);

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
