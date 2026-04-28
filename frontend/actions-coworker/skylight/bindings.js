// SkyLight bindings wrapper for coworker mode
// Communicates with macOS daemon via Unix socket to invoke SkyLight framework APIs

const net = require('net');
const path = require('path');

class SkyLightError extends Error {
  constructor(message) {
    super(message);
    this.name = 'SkyLightError';
  }
}

const SOCKET_PATH = '/tmp/skylight-daemon.sock';
const RPC_TIMEOUT = 5000;
const MAX_RETRIES = 3;

/**
 * Send an RPC request to the daemon over Unix socket with retry logic.
 * @param {Object} request - JSON-RPC request {method, pid, eventType?, params?}
 * @returns {Promise<Object>} RPC response
 */
async function sendRPC(request) {
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      return await sendRPCOnce(request);
    } catch (err) {
      if (attempt === MAX_RETRIES) {
        throw err;
      }
      console.warn(`[skylight-bindings] RPC attempt ${attempt} failed: ${err.message}, retrying...`);
      await new Promise(resolve => setTimeout(resolve, 100));
    }
  }
}

/**
 * Send a single RPC request with timeout.
 * @param {Object} request - JSON-RPC request
 * @returns {Promise<Object>} RPC response
 */
function sendRPCOnce(request) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection({ path: SOCKET_PATH }, () => {
      socket.write(JSON.stringify(request));
    });

    const timeoutId = setTimeout(() => {
      socket.destroy();
      reject(new SkyLightError(`RPC timeout after ${RPC_TIMEOUT}ms`));
    }, RPC_TIMEOUT);

    let responseBuffer = '';

    socket.on('data', (data) => {
      clearTimeout(timeoutId);
      responseBuffer += data.toString();
      
      try {
        const response = JSON.parse(responseBuffer);
        socket.end();
        
        if (response.success === false) {
          reject(new SkyLightError(response.error || 'Unknown RPC error'));
        } else {
          resolve(response);
        }
      } catch (e) {
        // JSON not complete yet, wait for more data
      }
    });

    socket.on('error', (err) => {
      clearTimeout(timeoutId);
      reject(new SkyLightError(`Socket error: ${err.message}`));
    });

    socket.on('end', () => {
      clearTimeout(timeoutId);
      if (!responseBuffer) {
        reject(new SkyLightError('Socket closed without response'));
      }
    });
  });
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
 * @returns {Promise<Object>} {success, result?, error?}
 */
async function eventPostToPid(pid, eventType, params) {
  console.log(`[skylight-bindings] eventPostToPid: pid=${pid}, event=${eventType}`);
  
  return sendRPC({
    method: 'eventPostToPid',
    pid,
    eventType,
    params: params || {}
  });
}

/**
 * Activate window without raising it (yabai pattern).
 *
 * Two SLPSPostEventRecordTo calls to flip AppKit-active state
 * without calling SLPSSetFrontProcessWithOptions.
 *
 * @param {number} pid - Process ID to activate
 * @returns {Promise<Object>} {success, result?, error?}
 */
async function activateWithoutRaise(pid) {
  console.log(`[skylight-bindings] activateWithoutRaise: pid=${pid}`);
  
  return sendRPC({
    method: 'activateWithoutRaise',
    pid
  });
}

/**
 * Keep AX tree alive for backgrounded Electron apps.
 *
 * Uses _AXObserverAddNotificationAndCheckRemote to mark observer
 * as remote-aware so Blink doesn't short-circuit when occluded.
 *
 * @param {number} pid - Process ID
 * @returns {Promise<Object>} {success, result?, error?}
 */
async function keepAXTreeAlive(pid) {
  console.log(`[skylight-bindings] keepAXTreeAlive: pid=${pid}`);
  
  return sendRPC({
    method: 'keepAXTreeAlive',
    pid
  });
}

/**
 * Send off-screen primer click at (-1, -1).
 *
 * Advances Chromium's user-activation gate so subsequent real click
 * is treated as "trusted continuation".
 *
 * @param {number} pid - Process ID
 * @returns {Promise<Object>} {success, result?, error?}
 */
async function primerClick(pid) {
  console.log(`[skylight-bindings] primerClick: pid=${pid} at (-1, -1)`);
  
  return sendRPC({
    method: 'primerClick',
    pid
  });
}

module.exports = {
  SkyLightError,
  eventPostToPid,
  activateWithoutRaise,
  keepAXTreeAlive,
  primerClick,
};
