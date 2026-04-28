// SkyLight bindings wrapper for coworker mode
// Communicates with macOS daemon to invoke SkyLight framework APIs

const { ipcRenderer } = require('electron');

class SkyLightError extends Error {
  constructor(message) {
    super(message);
    this.name = 'SkyLightError';
  }
}

/**
 * Post an event to a specific process via SkyLight.
 *
 * Bypasses HID pipeline, routes through WindowServer trust envelope.
 * Chrome and Chromium apps accept events from this channel.
 *
 * @param {number} pid - Process ID
 * @param {string} eventType - "click", "keyboard", "mouse_move"
 * @param {Object} params - Event parameters
 * @returns {Promise<boolean>} Success
 */
async function eventPostToPid(pid, eventType, params) {
  try {
    console.log(`[skylight-bindings] eventPostToPid: pid=${pid}, event=${eventType}`);
    // TODO: Implement via IPC to daemon that loads SkyLight
    return { success: true, event: eventType };
  } catch (err) {
    throw new SkyLightError(`Failed to post event: ${err.message}`);
  }
}

/**
 * Activate window without raising it (yabai pattern).
 *
 * Two SLPSPostEventRecordTo calls to flip AppKit-active state
 * without calling SLPSSetFrontProcessWithOptions.
 *
 * @param {number} pid - Process ID to activate
 * @returns {Promise<boolean>} Success
 */
async function activateWithoutRaise(pid) {
  try {
    console.log(`[skylight-bindings] activateWithoutRaise: pid=${pid}`);
    // TODO: Implement via IPC
    return { success: true, activated: true };
  } catch (err) {
    throw new SkyLightError(`Failed to activate: ${err.message}`);
  }
}

/**
 * Keep AX tree alive for backgrounded Electron apps.
 *
 * Uses _AXObserverAddNotificationAndCheckRemote to mark observer
 * as remote-aware so Blink doesn't short-circuit when occluded.
 *
 * @param {number} pid - Process ID
 * @returns {Promise<boolean>} Success
 */
async function keepAXTreeAlive(pid) {
  try {
    console.log(`[skylight-bindings] keepAXTreeAlive: pid=${pid}`);
    // TODO: Implement via IPC
    return { success: true, observer_set: true };
  } catch (err) {
    throw new SkyLightError(`Failed to set observer: ${err.message}`);
  }
}

/**
 * Send off-screen primer click at (-1, -1).
 *
 * Advances Chromium's user-activation gate so subsequent real click
 * is treated as "trusted continuation".
 *
 * @param {number} pid - Process ID
 * @returns {Promise<boolean>} Success
 */
async function primerClick(pid) {
  try {
    console.log(`[skylight-bindings] primerClick: pid=${pid} at (-1, -1)`);
    // TODO: Implement via IPC
    return { success: true, primed: true };
  } catch (err) {
    throw new SkyLightError(`Primer click failed: ${err.message}`);
  }
}

module.exports = {
  SkyLightError,
  eventPostToPid,
  activateWithoutRaise,
  keepAXTreeAlive,
  primerClick,
};
