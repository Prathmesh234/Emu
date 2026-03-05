// ChatInput component

const { Button, icons } = require('./Button');
const { Tooltip } = require('./Tooltip');

function ChatInput(onSend, onStop) {
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

    // Wrap send button with tooltip
    const sendBtnTooltip = Tooltip(sendBtn, '');

    let mode = 'send'; // 'send' | 'stop'

    // Auto-resize
    textarea.oninput = () => {
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
        if (mode === 'send') {
            sendBtn.disabled = !textarea.value.trim();
        }
    };

    // Enter to send
    textarea.onkeydown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (mode === 'stop') {
                if (onStop) onStop();
            } else if (textarea.value.trim() && !sendBtn.disabled && onSend) {
                onSend();
            }
        }
    };

    sendBtn.onclick = () => {
        if (mode === 'stop') {
            if (onStop) onStop();
        } else if (textarea.value.trim() && onSend) {
            onSend();
        }
    };

    function setMode(newMode) {
        mode = newMode;
        if (mode === 'stop') {
            sendBtn.innerHTML = icons.stop;
            sendBtn.className = 'send-btn stop-mode';
            sendBtn.disabled = false;
        } else {
            sendBtn.innerHTML = icons.send;
            sendBtn.className = 'send-btn';
            sendBtn.disabled = !textarea.value.trim();
        }
    }

    wrapper.appendChild(textarea);
    wrapper.appendChild(sendBtnTooltip.element);
    container.appendChild(wrapper);

    return {
        element: container,
        textarea,
        sendBtn,
        setTooltip: sendBtnTooltip.setText,
        setMode,
    };
}

module.exports = { ChatInput };
