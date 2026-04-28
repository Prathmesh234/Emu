// Window management for SkyLight coworker mode

const { activateWithoutRaise, keepAXTreeAlive } = require('./bindings');

/**
 * Activate a window for input without raising it (yabai pattern)
 * @param {number} pid - Process ID
 * @returns {Promise<boolean>}
 */
async function focusWithoutRaise(pid) {
  console.log(`[skylight-window] focusWithoutRaise: pid=${pid}`);
  return await activateWithoutRaise(pid);
}

/**
 * Keep AX tree alive for backgrounded Electron apps
 * @param {number} pid - Process ID
 * @returns {Promise<boolean>}
 */
async function maintainAXTree(pid) {
  console.log(`[skylight-window] maintainAXTree: pid=${pid}`);
  return await keepAXTreeAlive(pid);
}

/**
 * Get window PID at screen coordinates
 * (Placeholder - would use system APIs to hit-test)
 */
async function getWindowPIDAtCoordinates(x, y) {
  console.log(`[skylight-window] getWindowPIDAtCoordinates: (${x}, ${y})`);
  // TODO: Implement via macOS system calls
  return null;
}

module.exports = {
  focusWithoutRaise,
  maintainAXTree,
  getWindowPIDAtCoordinates,
};
