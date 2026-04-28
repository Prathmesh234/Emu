// CUA event dispatch for coworker mode
// Routes desktop actions through cua-driver CLI

const { eventPostToPid, primerClick } = require('./bindings');

/**
 * Dispatch left click via cua-driver
 * @param {number} x - Absolute X coordinate
 * @param {number} y - Absolute Y coordinate
 * @param {number} pid - Target process ID
 * @returns {Promise<Object>}
 */
async function dispatchClick(x, y, pid) {
  console.log(`[cua-event] click at (${x}, ${y}), pid=${pid}`);
  
  // Send primer click first
  await primerClick(pid);
  
  // Send real click
  return await eventPostToPid(pid, 'left_click', { x, y });
}

/**
 * Dispatch right click via cua-driver
 */
async function dispatchRightClick(x, y, pid) {
  console.log(`[cua-event] right_click at (${x}, ${y}), pid=${pid}`);
  return await eventPostToPid(pid, 'right_click', { x, y });
}

/**
 * Dispatch double click via cua-driver
 */
async function dispatchDoubleClick(x, y, pid) {
  console.log(`[cua-event] double_click at (${x}, ${y}), pid=${pid}`);
  return await eventPostToPid(pid, 'double_click', { x, y });
}

/**
 * Dispatch triple click via cua-driver
 */
async function dispatchTripleClick(x, y, pid) {
  console.log(`[cua-event] triple_click at (${x}, ${y}), pid=${pid}`);
  return await eventPostToPid(pid, 'triple_click', { x, y });
}

/**
 * Dispatch keyboard event via cua-driver
 */
async function dispatchKeyboard(key, modifiers, pid) {
  const modsStr = (modifiers || []).join('+');
  console.log(`[cua-event] keyboard: ${modsStr}+${key}, pid=${pid}`);
  return await eventPostToPid(pid, 'key_press', { key, modifiers });
}

/**
 * Dispatch text input via cua-driver
 */
async function dispatchTypeText(text, pid) {
  console.log(`[cua-event] type_text: "${text.substring(0, 50)}", pid=${pid}`);
  return await eventPostToPid(pid, 'type_text', { text });
}

/**
 * Dispatch mouse move via cua-driver
 */
async function dispatchMouseMove(x, y, pid) {
  console.log(`[cua-event] mouse_move to (${x}, ${y}), pid=${pid}`);
  return await eventPostToPid(pid, 'mouse_move', { x, y });
}

/**
 * Dispatch scroll via cua-driver
 */
async function dispatchScroll(direction, amount, pid) {
  console.log(`[cua-event] scroll ${direction} ${amount}, pid=${pid}`);
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
