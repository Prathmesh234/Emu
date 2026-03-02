// ChatInput component

const { Button, icons } = require('./Button');

function ChatInput(onSend) {
    const container = document.createElement('div');
    container.className = 'input-container';

    const wrapper = document.createElement('div');
    wrapper.className = 'input-wrapper';

    const textarea = document.createElement('textarea');
    textarea.className = 'chat-input';
    textarea.placeholder = 'Ask anything...';
    textarea.rows = 1;

    const sendBtn = document.createElement('button');
    sendBtn.className = 'send-btn';
    sendBtn.innerHTML = icons.send;
    sendBtn.disabled = true;

    // Auto-resize
    textarea.oninput = () => {
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
        sendBtn.disabled = !textarea.value.trim();
    };

    // Enter to send
    textarea.onkeydown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (textarea.value.trim() && onSend) onSend();
        }
    };

    sendBtn.onclick = () => {
        if (textarea.value.trim() && onSend) onSend();
    };

    wrapper.appendChild(textarea);
    wrapper.appendChild(sendBtn);
    container.appendChild(wrapper);

    return { element: container, textarea, sendBtn };
}

module.exports = { ChatInput };
