// SkyLight event dispatch for coworker mode
// Routes desktop actions through SkyLight instead of regular macOS APIs

const { eventPostToPid, primerClick } = require('./bindings');

/**
 * Dispatch left click via SkyLight
 * @param {number} x - Absolute X coordinate
 * @param {number} y - Absolute Y coordinate
 * @param {number} pid - Target process ID
 * @returns {Promise<{success: boolean}>}
 */
async function dispatchClick(x, y, pid) {
  console.log(`[skylight-event] click at (${x}, ${y}), pid=${pid}`);
  
  // Send primer click first if Chrome/Chromium
  await primerClick(pid);
  
  // Send real click
  return await eventPostToPid(pid, 'left_click', { x, y });
}

/**
 * Dispatch right click via SkyLight
 */
async function dispatchRightClick(x, y, pid) {
  console.log(`[skylight-event] right_click at (${x}, ${y}), pid=${pid}`);
  return await eventPostToPid(pid, 'right_click', { x, y });
}

/**
 * Dispatch double click via SkyLight
 */
async function dispatchDoubleClick(x, y, pid) {
  console.log(`[skylight-event] double_click at (${x}, ${y}), pid=${pid}`);
  return await eventPostToPid(pid, 'double_click', { x, y });
}

/**
 * Dispatch triple click via SkyLight
 */
async function dispatchTripleClick(x, y, pid) {
  console.log(`[skylight-event] triple_click at (${x}, ${y}), pid=${pid}`);
  return await eventPostToPid(pid, 'triple_click', { x, y });
}

/**
 * Dispatch keyboard event via SkyLight
 */
async function dispatchKeyboard(key, modifiers, pid) {
  const modsStr = (modifiers || []).join('+');
  console.log(`[skylight-event] keyboard: ${modsStr}+${key}, pid=${pid}`);
  return await eventPostToPid(pid, 'key_press', { key, modifiers });
}

/**
 * Dispatch text input via SkyLight
 */
async function dispatchTypeText(text, pid) {
  console.log(`[skylight-event] type_text: "${text.substring(0, 50)}", pid=${pid}`);
  return await eventPostToPid(pid, 'type_text', { text });
}

/**
 * Dispatch mouse move via SkyLight
 */
async function dispatchMouseMove(x, y, pid) {
  console.log(`[skylight-event] mouse_move to (${x}, ${y}), pid=${pid}`);
  return await eventPostToPid(pid, 'mouse_move', { x, y });
}

/**
 * Dispatch scroll via SkyLight
 */
async function dispatchScroll(direction, amount, pid) {
  console.log(`[skylight-event] scroll ${direction} ${amount}, pid=${pid}`);
  return await eventPostToPid(pid, 'scroll', { direction, amount });
}

module.exports = {
  dispatchClick,
  dispatchRightClick,
  dispatchDoubleClick,
  dispatchTripleClick,
  dispatchKeyboard,
  dispatchTypeText,
  dispatchMouseMove,
  dispatchScroll,
};
