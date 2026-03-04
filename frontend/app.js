// App — Minimal entry point
//
// Mounts the active page into #app.
// All chat logic lives in pages/Chat.js.

const { Chat } = require('./pages');

function init() {
    const app = document.getElementById('app');
    Chat.mount(app);
}

init();
