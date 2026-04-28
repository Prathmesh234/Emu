# CUA Coworker Mode Integration Guide

This guide explains how to set up and use CUA (Computer Use Agent) driver for background computer control in Emu.

## Prerequisites

- macOS 10.13+
- Node.js 14+
- Electron (included in dependencies)

## Installation

### Step 1: Install cua-driver

The `cua-driver` CLI must be installed and available in your PATH. Installation depends on your system:

**macOS (Homebrew):**
```bash
brew tap your-org/cua
brew install cua-driver
```

**Manual Installation:**
Download the latest release from the project repository and add it to your PATH:
```bash
# Extract to /usr/local/bin or similar
sudo cp cua-driver /usr/local/bin/
sudo chmod +x /usr/local/bin/cua-driver
```

**Verify Installation:**
```bash
cua-driver --version
which cua-driver
```

### Step 2: Enable Coworker Mode

Set the environment variable to enable CUA coworker mode:

```bash
export EMU_COWORKER_MODE=cua
```

Or run Emu with the variable set:
```bash
EMU_COWORKER_MODE=cua npm start
```

### Step 3: Grant Accessibility Permissions (macOS)

cua-driver requires accessibility permissions to control other applications:

1. Open **System Preferences** > **Security & Privacy** > **Accessibility**
2. Unlock the settings
3. Add the application running Emu to the Accessibility list
4. Grant permission when prompted

## Testing

### Run Unit Tests

```bash
npm run test:cua
```

This runs comprehensive tests for:
- Error handling (missing binary, invalid args, timeouts)
- Response parsing (JSON, text fallback, error messages)
- Retry logic with exponential backoff
- Input validation for all event types
- Module exports and structure

Expected output:
```
=== CUA Shell Test Suite ===

[TEST] isCUAAvailable returns boolean ... ✓ pass
[TEST] executeCUACommand fails gracefully when cua-driver missing ... ✓ pass
...

=== Test Summary ===
Passed: 20
Failed: 0
Total: 20
```

### Manual Testing with Clicks

Once coworker mode is enabled, you can test manual click events:

```javascript
const { dispatchClick } = require('./frontend/actions-coworker/cua-shell/events');

// Click at coordinates (100, 200) on target app with PID 1234
await dispatchClick(100, 200, 1234);
```

## CLI Command Reference

All commands support target PID routing and have a 5-second timeout default.

### Click Events

```bash
cua-driver click --pid 1234 --x 100 --y 200
cua-driver right-click --pid 1234 --x 100 --y 200
cua-driver double-click --pid 1234 --x 100 --y 200
```

### Keyboard Events

```bash
cua-driver key --pid 1234 --key "Return"
cua-driver key --pid 1234 --key "cmd" --modifiers "shift"
cua-driver type --pid 1234 --text "Hello, World!"
```

### Mouse & Scroll

```bash
cua-driver move --pid 1234 --x 100 --y 200
cua-driver scroll --pid 1234 --direction "up" --amount 5
```

### Window Control

```bash
cua-driver activate --pid 1234 --no-raise
```

## Troubleshooting

### Error: "command not found: cua-driver"

**Problem:** cua-driver is not installed or not in PATH.

**Solution:**
1. Install cua-driver using the instructions above
2. Verify: `which cua-driver`
3. Add to PATH if needed: `export PATH="/path/to/cua-driver:$PATH"`

### Error: "Permission denied"

**Problem:** cua-driver lacks accessibility permissions.

**Solution:**
1. Go to **System Preferences** > **Security & Privacy** > **Accessibility**
2. Check if your app is listed; if not, click "+" and add it
3. Grant Full Disk Access if required
4. Restart the application

### Error: "Timeout after 3 attempts"

**Problem:** Commands are timing out (>5 seconds).

**Causes & Solutions:**
- Target PID doesn't exist: Verify the process is running (`pgrep -l "app name"`)
- Target app is unresponsive: Try again after the app recovers
- System load is high: Reduce background processes
- Network issues (if remote): Check connectivity

**Custom Timeout:**
```javascript
const { executeCUACommand } = require('./frontend/actions-coworker/cua-shell/bindings');

// Set 10 second timeout instead of default 5
await executeCUACommand('click', { pid, x, y }, 10000);
```

### Error: "Invalid coordinates"

**Problem:** Negative or out-of-bounds coordinates.

**Solution:**
Ensure coordinates are non-negative and within screen bounds:
- X: 0 to screen width
- Y: 0 to screen height

### Tests Fail: "Expected function to throw"

**Problem:** A validation test is failing.

**Solution:**
1. Check that events.js has proper input validation
2. Ensure bindings.js error classification works
3. Run with `-i` flag for debugging: `node -i frontend/actions-coworker/cua-shell/test.js`

## Architecture

### Components

- **bindings.js** - Low-level CLI wrapper with:
  - Retry logic (up to 3 attempts with exponential backoff)
  - Error classification and handling
  - JSON/text response parsing
  - Timeout handling (5 second default)
  - Timestamped logging

- **events.js** - High-level event dispatch with:
  - Input validation (coordinates, text, keys)
  - Error propagation
  - Click primer support
  - Comprehensive logging

- **test.js** - Test suite covering:
  - Module exports
  - Error scenarios
  - Input validation
  - Response parsing
  - Error classification

### Logging

All logs use the `[cua-shell]` prefix with ISO timestamps:

```
[cua-shell] 2024-04-27T23:30:45.123Z [attempt 1/3] Executing: cua-driver click --pid 1234 --x 100 --y 200
[cua-shell] 2024-04-27T23:30:45.456Z Command succeeded on attempt 1
```

Log levels:
- `console.log()` - Normal operations
- `console.warn()` - Warnings (stderr, retries)
- `console.error()` - Errors (failures, validation)

### Error Handling

**Error Classification:**
- `not_found` - Binary not installed
- `invalid_args` - Bad arguments
- `timeout` - Exceeded 5 seconds
- `execution_error` - Command failed
- `max_retries_exceeded` - Failed after 3 attempts

**Retry Strategy:**
- Retries only for transient errors (not for `not_found` or `invalid_args`)
- Exponential backoff: 500ms, 1000ms, 1500ms between attempts
- No retry on final attempt timeout

## Environment Variables

- `EMU_COWORKER_MODE=cua` - Enable CUA coworker mode

## Examples

### Example 1: Click on Button

```javascript
const { dispatchClick } = require('./frontend/actions-coworker/cua-shell/events');

// Get target app PID
const targetPID = 12345; // Get from system

// Click on button at (250, 150)
try {
  const result = await dispatchClick(250, 150, targetPID);
  console.log('Click succeeded:', result);
} catch (err) {
  console.error('Click failed:', err.message);
}
```

### Example 2: Type Text with Error Handling

```javascript
const { dispatchTypeText } = require('./frontend/actions-coworker/cua-shell/events');

const text = "Hello, CUA!";

try {
  await dispatchTypeText(text, targetPID);
  console.log(`Typed: "${text}"`);
} catch (err) {
  if (err.message.includes('Text cannot be empty')) {
    console.log('Empty text not allowed');
  } else {
    console.error('Type failed:', err.message);
  }
}
```

### Example 3: Keyboard Shortcut

```javascript
const { dispatchKeyboard } = require('./frontend/actions-coworker/cua-shell/events');

// Cmd+S (Save)
try {
  await dispatchKeyboard('s', ['cmd'], targetPID);
  console.log('Sent Cmd+S');
} catch (err) {
  console.error('Keyboard dispatch failed:', err.message);
}
```

### Example 4: Scroll Down

```javascript
const { dispatchScroll } = require('./frontend/actions-coworker/cua-shell/events');

try {
  // Scroll down 10 units
  await dispatchScroll('down', 10, targetPID);
  console.log('Scrolled down');
} catch (err) {
  console.error('Scroll failed:', err.message);
}
```

## Performance Notes

- Default timeout: 5 seconds per command
- Retry latency: 0-1.5 seconds added per failure
- Typical command latency: 100-500ms (varies by target app)
- Primer click overhead: ~100ms

## Security Considerations

- cua-driver requires full accessibility permissions
- All commands must target valid PIDs
- Coordinates are validated for non-negative values
- No support for executing arbitrary shell commands

## Support & Debugging

Enable detailed logging:
```bash
DEBUG=cua:* npm start
```

For issues, check:
1. `cua-driver --version` works
2. Accessibility permissions granted
3. Target app PID is valid
4. Test suite passes: `npm run test:cua`

## References

- [cua-driver Documentation](https://github.com/your-org/cua-driver)
- [Emu Repository](https://github.com/Prathmesh234/Emu)
- [Accessibility Permissions (Apple)](https://support.apple.com/en-us/HT202802)
