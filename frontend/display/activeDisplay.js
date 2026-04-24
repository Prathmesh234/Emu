// frontend/display/activeDisplay.js
//
// Single source of truth for "which display is Emu working on?"
//
// At session start (when the agent begins generating), the display that
// contains the Emu window is locked in. All subsequent screenshots,
// coordinate mapping, and border window positioning use that locked display
// until the session ends — even if the user moves the window mid-task.

let _lockedDisplay = null;

/**
 * Returns the display that contains the majority of the given window's bounds.
 * Falls back to the primary display when no window is available.
 *
 * @param {Electron.Screen} screen
 * @param {Electron.BrowserWindow|null} win
 * @returns {Electron.Display}
 */
function getActiveDisplay(screen, win) {
    if (!win) return screen.getPrimaryDisplay();
    return screen.getDisplayMatching(win.getBounds());
}

/**
 * Lock the working display for the current session.
 * Call this when the agent starts generating so mid-task window moves
 * don't shift which screen is being captured.
 *
 * @param {Electron.Screen} screen
 * @param {Electron.BrowserWindow|null} win
 * @returns {Electron.Display}
 */
function lockSessionDisplay(screen, win) {
    _lockedDisplay = getActiveDisplay(screen, win);
    const b = _lockedDisplay.bounds;
    console.log(`[display] session locked → display ${_lockedDisplay.id} (${b.width}×${b.height} @ ${b.x},${b.y})`);
    return _lockedDisplay;
}

/**
 * Returns the locked session display, or null if no session is active.
 * @returns {Electron.Display|null}
 */
function getLockedDisplay() {
    return _lockedDisplay;
}

/**
 * Clear the session lock. Call when the agent stops generating.
 */
function clearSessionLock() {
    if (_lockedDisplay) {
        console.log(`[display] session lock cleared (was display ${_lockedDisplay.id})`);
    }
    _lockedDisplay = null;
}

module.exports = { getActiveDisplay, lockSessionDisplay, getLockedDisplay, clearSessionLock };
