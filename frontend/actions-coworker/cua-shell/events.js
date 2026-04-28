// CUA event dispatch for coworker mode
// Routes desktop actions through cua-driver CLI

const { eventPostToPid, primerClick } = require('./bindings');

function getTimestamp() {
  return new Date().toISOString();
}

async function dispatchClick(x, y, pid) {
  try {
    console.log(`[cua-shell] ${getTimestamp()} [event] left_click at (${x}, ${y}), pid=${pid}`);

    if (x < 0 || y < 0) {
      throw new Error(`Invalid coordinates: (${x}, ${y}). Coordinates must be non-negative.`);
    }

    console.log(`[cua-shell] ${getTimestamp()} [primer] Sending primer click for pid=${pid}`);
    await primerClick(pid);

    console.log(`[cua-shell] ${getTimestamp()} [click] Sending real click to (${x}, ${y})`);
    return await eventPostToPid(pid, 'left_click', { x, y });
  } catch (err) {
    console.error(`[cua-shell] ${getTimestamp()} [error] dispatchClick failed: ${err.message}`);
    throw err;
  }
}

async function dispatchRightClick(x, y, pid) {
  try {
    console.log(`[cua-shell] ${getTimestamp()} [event] right_click at (${x}, ${y}), pid=${pid}`);

    if (x < 0 || y < 0) {
      throw new Error(`Invalid coordinates: (${x}, ${y}). Coordinates must be non-negative.`);
    }

    return await eventPostToPid(pid, 'right_click', { x, y });
  } catch (err) {
    console.error(`[cua-shell] ${getTimestamp()} [error] dispatchRightClick failed: ${err.message}`);
    throw err;
  }
}

async function dispatchDoubleClick(x, y, pid) {
  try {
    console.log(`[cua-shell] ${getTimestamp()} [event] double_click at (${x}, ${y}), pid=${pid}`);

    if (x < 0 || y < 0) {
      throw new Error(`Invalid coordinates: (${x}, ${y}). Coordinates must be non-negative.`);
    }

    return await eventPostToPid(pid, 'double_click', { x, y });
  } catch (err) {
    console.error(`[cua-shell] ${getTimestamp()} [error] dispatchDoubleClick failed: ${err.message}`);
    throw err;
  }
}

async function dispatchTripleClick(x, y, pid) {
  try {
    console.log(`[cua-shell] ${getTimestamp()} [event] triple_click at (${x}, ${y}), pid=${pid}`);

    if (x < 0 || y < 0) {
      throw new Error(`Invalid coordinates: (${x}, ${y}). Coordinates must be non-negative.`);
    }

    return await eventPostToPid(pid, 'triple_click', { x, y });
  } catch (err) {
    console.error(`[cua-shell] ${getTimestamp()} [error] dispatchTripleClick failed: ${err.message}`);
    throw err;
  }
}

async function dispatchKeyboard(key, modifiers, pid) {
  try {
    const modsStr = (modifiers || []).join('+');
    console.log(`[cua-shell] ${getTimestamp()} [event] keyboard: ${modsStr ? modsStr + '+' : ''}${key}, pid=${pid}`);

    if (!key) {
      throw new Error('Key cannot be empty');
    }

    return await eventPostToPid(pid, 'key_press', { key, modifiers });
  } catch (err) {
    console.error(`[cua-shell] ${getTimestamp()} [error] dispatchKeyboard failed: ${err.message}`);
    throw err;
  }
}

async function dispatchTypeText(text, pid) {
  try {
    const preview = text.substring(0, 50) + (text.length > 50 ? '...' : '');
    console.log(`[cua-shell] ${getTimestamp()} [event] type_text: "${preview}", pid=${pid}`);

    if (!text) {
      throw new Error('Text cannot be empty');
    }

    return await eventPostToPid(pid, 'type_text', { text });
  } catch (err) {
    console.error(`[cua-shell] ${getTimestamp()} [error] dispatchTypeText failed: ${err.message}`);
    throw err;
  }
}

async function dispatchMouseMove(x, y, pid) {
  try {
    console.log(`[cua-shell] ${getTimestamp()} [event] mouse_move to (${x}, ${y}), pid=${pid}`);

    if (x < 0 || y < 0) {
      throw new Error(`Invalid coordinates: (${x}, ${y}). Coordinates must be non-negative.`);
    }

    return await eventPostToPid(pid, 'mouse_move', { x, y });
  } catch (err) {
    console.error(`[cua-shell] ${getTimestamp()} [error] dispatchMouseMove failed: ${err.message}`);
    throw err;
  }
}

async function dispatchScroll(direction, amount, pid) {
  try {
    console.log(`[cua-shell] ${getTimestamp()} [event] scroll ${direction} ${amount}, pid=${pid}`);

    if (!direction) {
      throw new Error('Scroll direction cannot be empty');
    }

    if (amount === null || amount === undefined || amount <= 0) {
      throw new Error(`Scroll amount must be positive, got: ${amount}`);
    }

    return await eventPostToPid(pid, 'scroll', { direction, amount });
  } catch (err) {
    console.error(`[cua-shell] ${getTimestamp()} [error] dispatchScroll failed: ${err.message}`);
    throw err;
  }
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
