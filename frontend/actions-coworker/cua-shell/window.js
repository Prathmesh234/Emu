// Window management for CUA coworker mode

const { activateWithoutRaise, keepAXTreeAlive } = require('./bindings');

/**
 * Activate window without raising via cua-driver
 * @param {number} pid - Process ID
 * @returns {Promise<Object>}
 */
async function focusWithoutRaise(pid) {
  console.log(`[cua-window] focusWithoutRaise: pid=${pid}`);
  return await activateWithoutRaise(pid);
}

/**
 * Keep AX tree alive via cua-driver
 * @param {number} pid - Process ID
 * @returns {Promise<Object>}
 */
async function maintainAXTree(pid) {
  console.log(`[cua-window] maintainAXTree: pid=${pid}`);
  return await keepAXTreeAlive(pid);
}

/**
 * Get window PID at coordinates via cua-driver
 * @param {number} x - X coordinate
 * @param {number} y - Y coordinate
 * @returns {Promise<number|null>}
 */
async function getWindowPIDAtCoordinates(x, y) {
  console.log(`[cua-window] getWindowPIDAtCoordinates: (${x}, ${y})`);
  // TODO: Implement via cua-driver if available
  return null;
}

module.exports = {
  focusWithoutRaise,
  maintainAXTree,
  getWindowPIDAtCoordinates,
};
