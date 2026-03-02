// Message component

function Message(role, content, onClick) {
    const msg = document.createElement('div');
    msg.className = 'message ' + role;

    const contentEl = document.createElement('div');
    contentEl.className = 'message-content';
    contentEl.textContent = content;

    if (onClick) contentEl.onclick = onClick;

    msg.appendChild(contentEl);
    return { element: msg, content: contentEl };
}

module.exports = { Message };
