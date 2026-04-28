// CUA driver CLI wrapper for coworker mode
// Executes cua-driver commands to implement background computer-use

const { exec } = require('child_process');
const { promisify } = require('util');

const execAsync = promisify(exec);

// Configuration constants
const DEFAULT_TIMEOUT_MS = 5000;
const MAX_RETRIES = 3;
const RETRY_BACKOFF_MS = 500;

class CUAError extends Error {
  constructor(message, code) {
    super(message);
    this.name = 'CUAError';
    this.code = code;
  }
}

function getTimestamp() {
  return new Date().toISOString();
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function isCUAAvailable() {
  try {
    const { stdout } = await execAsync('which cua-driver');
    return !!stdout.trim();
  } catch (err) {
    return false;
  }
}

async function getCUAVersion() {
  try {
    const { stdout } = await execAsync('cua-driver --version');
    const version = stdout.trim();
    console.log(`[cua-shell] ${getTimestamp()} cua-driver version: ${version}`);
    return version;
  } catch (err) {
    console.warn(`[cua-shell] ${getTimestamp()} Failed to get cua-driver version: ${err.message}`);
    return null;
  }
}

function classifyError(err) {
  const message = err.message || '';
  const stderr = err.stderr || '';
  const combined = `${message}${stderr}`.toLowerCase();

  if (combined.includes('command not found') || combined.includes('enoent')) {
    return 'not_found';
  }
  if (combined.includes('invalid') || combined.includes('argument')) {
    return 'invalid_args';
  }
  if (combined.includes('timeout')) {
    return 'timeout';
  }
  return 'execution_error';
}

function parseJSON(str) {
  try {
    return JSON.parse(str);
  } catch (e) {
    return null;
  }
}

function isValidResponse(resp) {
  if (!resp) return false;
  return typeof resp === 'object' && (resp.success !== undefined || Object.keys(resp).length > 0);
}

async function executeCUACommand(command, args, timeoutMs = DEFAULT_TIMEOUT_MS) {
  let lastError;

  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      let cmd = `cua-driver ${command}`;

      for (const [key, value] of Object.entries(args)) {
        if (value === null || value === undefined) continue;
        if (typeof value === 'boolean') {
          if (value) cmd += ` --${key}`;
        } else {
          cmd += ` --${key} "${value}"`;
        }
      }

      const timestamp = getTimestamp();
      console.log(`[cua-shell] ${timestamp} [attempt ${attempt}/${MAX_RETRIES}] Executing: ${cmd}`);

      const { stdout, stderr } = await Promise.race([
        execAsync(cmd),
        new Promise((_, reject) =>
          setTimeout(
            () => reject(new Error('Command timeout')),
            timeoutMs
          )
        ),
      ]);

      if (stderr) {
        console.warn(`[cua-shell] ${timestamp} stderr: ${stderr}`);
      }

      const jsonResponse = parseJSON(stdout);

      if (jsonResponse) {
        if (isValidResponse(jsonResponse)) {
          console.log(`[cua-shell] ${timestamp} Command succeeded on attempt ${attempt}`);
          return jsonResponse;
        }
      }

      if (stdout) {
        console.log(`[cua-shell] ${timestamp} Parsed as text response`);
        return { success: true, output: stdout.trim() };
      }

      console.log(`[cua-shell] ${timestamp} Command succeeded (no output)`);
      return { success: true };
    } catch (err) {
      lastError = err;
      const errorType = classifyError(err);
      const timestamp = getTimestamp();

      console.error(`[cua-shell] ${timestamp} Attempt ${attempt} failed (${errorType}): ${err.message}`);

      if (errorType === 'not_found' || errorType === 'invalid_args') {
        console.error(`[cua-shell] ${timestamp} Not retrying due to error type: ${errorType}`);
        throw new CUAError(
          `CUA command failed: ${err.message}`,
          errorType
        );
      }

      if (errorType === 'timeout' && attempt === MAX_RETRIES) {
        throw new CUAError(`CUA command timeout after ${attempt} attempts`, errorType);
      }

      if (attempt < MAX_RETRIES) {
        const backoffMs = RETRY_BACKOFF_MS * attempt;
        console.log(`[cua-shell] ${timestamp} Retrying in ${backoffMs}ms...`);
        await sleep(backoffMs);
        continue;
      }
    }
  }

  throw new CUAError(
    `CUA command failed after ${MAX_RETRIES} attempts: ${lastError?.message}`,
    'max_retries_exceeded'
  );
}

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

async function activateWithoutRaise(pid) {
  return await executeCUACommand('activate', { pid, 'no-raise': true });
}

async function keepAXTreeAlive(pid) {
  console.log(`[cua-shell] ${getTimestamp()} AX tree kept alive by cua-driver for pid=${pid}`);
  return { success: true, observer_set: true };
}

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
  getCUAVersion,
  executeCUACommand,
  eventPostToPid,
  activateWithoutRaise,
  keepAXTreeAlive,
  primerClick,
};
