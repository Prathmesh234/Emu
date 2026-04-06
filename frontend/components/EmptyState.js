// EmptyState component — shown when chat has no messages

function EmptyState() {
    const empty = document.createElement('div');
    empty.className = 'empty-state';

    const emoji = document.createElement('div');
    emoji.className = 'empty-state-emoji';
    emoji.textContent = '\u{1F9A4}';

    const h2 = document.createElement('h2');
    h2.textContent = 'Hey, I\'m Emu';

    const tagline = document.createElement('p');
    tagline.className = 'empty-state-tagline';
    tagline.textContent = 'Your desktop co-pilot. I see your screen, move your mouse, type on your keyboard, and run commands — so you don\'t have to.';

    const hints = document.createElement('div');
    hints.className = 'empty-state-hints';

    const hintItems = [
        { icon: '\u{1F5A5}', text: 'Open apps, navigate menus, fill out forms' },
        { icon: '\u{2328}',  text: 'Run shell commands and automate workflows' },
        { icon: '\u{1F4C1}', text: 'Manage files, organize folders, move things around' },
        { icon: '\u{1F50D}', text: 'Search the web, extract info, handle browser tasks' },
    ];

    hintItems.forEach(item => {
        const hint = document.createElement('div');
        hint.className = 'empty-state-hint';
        const icon = document.createElement('span');
        icon.className = 'empty-state-hint-icon';
        icon.textContent = item.icon;
        const text = document.createElement('span');
        text.textContent = item.text;
        hint.appendChild(icon);
        hint.appendChild(text);
        hints.appendChild(hint);
    });

    const cta = document.createElement('p');
    cta.className = 'empty-state-cta';
    cta.textContent = 'Tell me what\'s tedious. I\'ll handle it.';

    empty.appendChild(emoji);
    empty.appendChild(h2);
    empty.appendChild(tagline);
    empty.appendChild(hints);
    empty.appendChild(cta);

    return { element: empty };
}

module.exports = { EmptyState };
