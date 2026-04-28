// services/windowManager.js — Window placement / chrome IPC helpers.
//
// Extracted from pages/Chat.js. Behavior is identical: each function
// invokes the same IPC channel and toggles the same store + header
// state it did when it lived inside Chat.js.
//
// Usage:
//     const win = createWindowManager(header);
//     await win.toggleWindow();
//     await win.moveToSidePanel();

const { ipcRenderer } = require('electron');
const store = require('../state/store');

function createWindowManager(header) {
    async function toggleWindow() {
        const { state } = store;
        if (state.isSidePanel) {
            await ipcRenderer.invoke('window:centered');
            store.setSidePanel(false);
            header.setExpandVisible(false);
            header.setCompact(false);
        } else {
            await ipcRenderer.invoke('window:side-panel');
            store.setSidePanel(true);
            header.setExpandVisible(true);
            header.setCompact(true);
        }
    }

    async function moveToSidePanel() {
        if (!store.state.isSidePanel) {
            await ipcRenderer.invoke('window:side-panel');
            store.setSidePanel(true);
            header.setExpandVisible(true);
            header.setCompact(true);
        }
    }

    async function moveToCentered() {
        if (store.state.isSidePanel) {
            await ipcRenderer.invoke('window:centered');
            store.setSidePanel(false);
            header.setExpandVisible(false);
            header.setCompact(false);
        }
    }

    async function minimizeWindow() {
        try {
            await ipcRenderer.invoke('window:minimize');
        } catch (err) {
            console.warn('[window] minimize failed:', err.message);
        }
    }

    async function maximizeWindow() {
        try {
            await ipcRenderer.invoke('window:maximize');
        } catch (err) {
            console.warn('[window] maximize failed:', err.message);
        }
    }

    return { toggleWindow, moveToSidePanel, moveToCentered, minimizeWindow, maximizeWindow };
}

module.exports = { createWindowManager };
