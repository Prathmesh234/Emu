// CUA driver CLI wrapper for coworker mode
// Executes cua-driver commands to implement background computer-use

const { exec } = require('child_process');
const { promisify } = require('util');

const execAsync = promisify(exec);

class CUAError extends Error {
  constructor(message) {
    super(message);
    this.name = 'CUAError';
  }
}

/**
 * Check if cua-driver is installed and available
 * @returns {Promise<boolean>}
 */
async function isCUAAvailable() {
  try {
    const { stdout } = await execAsync('which cua-driver');
    return !!stdout.trim();
  } catch (err) {
    return false;
  }
}

/**
 * Execute a cua-driver command
 * @param {string} command - cua-driver command (e.g., 'click', 'type', 'key')
 * @param {Object} args - Command arguments
 * @returns {Promise<Object>} Parsed response
 */
async function executeCUACommand(command, args) {
  try {
    // Build command line
    let cmd = `cua-driver ${command}`;
    
    for (const [key, value] of Object.entries(args)) {
      if (value === null || value === undefined) continue;
      if (typeof value === 'boolean') {
        if (value) cmd += ` --${key}`;
      } else {
        cmd += ` --${key} "${value}"`;
      }
    }
    
    console.log(`[cua-shell] Executing: ${cmd}`);
    
    const { stdout, stderr } = await execAsync(cmd);
    
    if (stderr) {
      console.warn(`[cua-shell] stderr: ${stderr}`);
    }
    
    // Parse JSON response
    try {
      return JSON.parse(stdout);
    } catch (e) {
      // Some commands might not return JSON
      return { success: true, output: stdout.trim() };
    }
  } catch (err) {
    console.error(`[cua-shell] Command failed: ${err.message}`);
    throw new CUAError(`CUA command failed: ${err.message}`);
  }
}

/**
 * Post event to process via cua-driver
 * @param {number} pid - Process ID
 * @param {string} eventType - "click", "keyboard", "mouse_move"
 * @param {Object} params - Event parameters
 * @returns {Promise<Object>}
 */
async function eventPostToPid(pid, eventType, params) {
  let command;
  
  switch (eventType) {
    case 'left_click':
      command = 'click';
      break;
    case 'right_click':
      command = 'right-click';
      break;
    case 'double_click':
      command = 'double-click';
      break;
    case 'key_press':
      command = 'key';
      break;
    case 'type_text':
      command = 'type';
      break;
    case 'mouse_move':
      command = 'move';
      break;
    case 'scroll':
      command = 'scroll';
      break;
    default:
      throw new CUAError(`Unknown event type: ${eventType}`);
  }
  
  const args = { pid, ...params };
  return await executeCUACommand(command, args);
}

/**
 * Activate window without raising via cua-driver
 * @param {number} pid - Process ID
 * @returns {Promise<Object>}
 */
async function activateWithoutRaise(pid) {
  return await executeCUACommand('activate', { pid, 'no-raise': true });
}

/**
 * Keep AX tree alive via cua-driver (if supported)
 * @param {number} pid - Process ID
 * @returns {Promise<Object>}
 */
async function keepAXTreeAlive(pid) {
  // cua-driver handles this automatically with remote observer
  console.log(`[cua-shell] AX tree kept alive by cua-driver for pid=${pid}`);
  return { success: true, observer_set: true };
}

/**
 * Send primer click via cua-driver
 * @param {number} pid - Process ID
 * @returns {Promise<Object>}
 */
async function primerClick(pid) {
  return await executeCUACommand('click', { 
    pid, 
    x: -1, 
    y: -1 
  });
}

module.exports = {
  CUAError,
  isCUAAvailable,
  executeCUACommand,
  eventPostToPid,
  activateWithoutRaise,
  keepAXTreeAlive,
  primerClick,
};
