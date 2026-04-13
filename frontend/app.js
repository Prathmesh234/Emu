// App — Minimal entry point
//
// Mounts the active page into #app.
// All chat logic lives in pages/Chat.js.

const { Chat } = require('./pages');
const store = require('./state/store');

function init() {
    const app = document.getElementById('app');
    // Apply saved dark mode preference on startup
    if (store.state.darkMode) app.classList.add('dark');
    Chat.mount(app);
}

init();
