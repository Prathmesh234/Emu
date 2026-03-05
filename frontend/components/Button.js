// Button component

const icons = {
    plus: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14"/><path d="M5 12h14"/></svg>',
    send: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/></svg>',
    stop: '<svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" stroke="none"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>'
};

function Button(className, icon, text, onClick) {
    const btn = document.createElement('button');
    btn.className = className;
    btn.innerHTML = (icon ? icons[icon] : '') + (text ? `<span>${text}</span>` : '');
    if (onClick) btn.onclick = onClick;
    return btn;
}

module.exports = { Button, icons };
