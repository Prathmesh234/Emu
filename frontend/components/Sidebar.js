// Sidebar component

const { Button } = require('./Button');

function Sidebar(title, onNewChat) {
    const sidebar = document.createElement('div');
    sidebar.className = 'sidebar';

    const header = document.createElement('div');
    header.className = 'sidebar-header';

    const titleEl = document.createElement('div');
    titleEl.className = 'sidebar-title';
    titleEl.textContent = title;

    const newChatBtn = Button('new-chat-btn', 'plus', 'New Chat', onNewChat);

    header.appendChild(titleEl);
    header.appendChild(newChatBtn);

    const history = document.createElement('div');
    history.className = 'chat-history';

    sidebar.appendChild(header);
    sidebar.appendChild(history);

    return { element: sidebar, history };
}

function HistoryItem(text, active, onClick) {
    const item = document.createElement('div');
    item.className = 'chat-history-item' + (active ? ' active' : '');
    item.textContent = text;
    if (onClick) item.onclick = onClick;
    return item;
}

module.exports = { Sidebar, HistoryItem };
