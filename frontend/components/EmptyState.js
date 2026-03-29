// EmptyState component — shown when chat has no messages

function EmptyState() {
    const empty = document.createElement('div');
    empty.className = 'empty-state';

    const emoji = document.createElement('div');
    emoji.className = 'empty-state-emoji';
    emoji.textContent = '\u{1F9A4}';

    const h2 = document.createElement('h2');
    h2.textContent = 'Hey, I\'m Emu';

    empty.appendChild(emoji);
    empty.appendChild(h2);

    return { element: empty };
}

module.exports = { EmptyState };
