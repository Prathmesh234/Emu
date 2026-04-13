// EmptyState component — shown when chat has no messages

function EmptyState() {
    const empty = document.createElement('div');
    empty.className = 'empty-state';

    const emoji = document.createElement('div');
    emoji.className = 'empty-state-emoji';
    emoji.innerHTML = '<svg width="48" height="48" viewBox="0 0 40 36" fill="none" class="emu-static-svg"><g><path class="emu-main-stroke" d="M14 18 Q12 10 10 5 Q9 3 10 2" stroke-width="2.2" stroke-linecap="round" fill="none"/><circle class="emu-main-fill" cx="9" cy="2.5" r="2.5"/><path class="emu-accent-fill" d="M6.5 2.5 L3 3.5 L6.5 4"/><circle cx="8.2" cy="1.8" r="0.7" fill="#fff"/><ellipse class="emu-main-fill" cx="20" cy="20" rx="9" ry="6"/><path class="emu-main-stroke" d="M29 18 Q33 14 32 11" stroke-width="2" stroke-linecap="round" fill="none"/><path class="emu-main-stroke" d="M28 19 Q34 16 34 13" stroke-width="1.8" stroke-linecap="round" fill="none"/></g><path class="emu-accent-stroke" d="M18 25 L16 33 L13 33" stroke-width="1.8" stroke-linecap="round" fill="none"/><path class="emu-accent-stroke" d="M22 25 L20 33 L17 33" stroke-width="1.8" stroke-linecap="round" fill="none"/></svg>';

    const h2 = document.createElement('h2');
    h2.textContent = 'Hey, I\'m Emu';

    empty.appendChild(emoji);
    empty.appendChild(h2);

    return { element: empty };
}

module.exports = { EmptyState };
