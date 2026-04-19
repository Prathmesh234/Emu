// App — Minimal entry point
//
// Mounts the active page into #app.
// All chat logic lives in pages/Chat.js.
//
// Design change (Emu Design System v1 refactor):
//   Dark mode class changed from '.dark' on #app
//   to '.ink' on <body> — matches the new CSS token system.
//   Same localStorage key ('emu-dark-mode') so no user data loss.

const { Chat } = require('./pages');
const store = require('./state/store');

function init() {
    // Apply saved theme on startup.
    // New: toggle .ink on <body> (tokens.css uses body.ink to swap --paper/--ink).
    if (store.state.darkMode) document.body.classList.add('ink');
    Chat.mount(document.getElementById('app'));
}

init();
