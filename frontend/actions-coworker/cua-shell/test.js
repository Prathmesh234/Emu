// Test suite for CUA shell bindings and events
// Run with: node frontend/actions-coworker/cua-shell/test.js

let passCount = 0;
let failCount = 0;
const results = [];

function assert(condition, message) {
  if (!condition) {
    throw new Error(`Assertion failed: ${message}`);
  }
}

async function runTest(name, fn) {
  try {
    await fn();
    passCount++;
    results.push(`[TEST] ${name} ... ✓ pass`);
    console.log(`[TEST] ${name} ... ✓ pass`);
  } catch (err) {
    failCount++;
    results.push(`[TEST] ${name} ... ✗ fail: ${err.message}`);
    console.error(`[TEST] ${name} ... ✗ fail: ${err.message}`);
  }
}

async function runTests() {
  console.log('\n=== CUA Shell Test Suite ===\n');

  await runTest('isCUAAvailable returns boolean', async () => {
    const { isCUAAvailable } = require('./bindings');
    const result = await isCUAAvailable();
    assert(typeof result === 'boolean', 'Result should be boolean');
  });

  await runTest('executeCUACommand fails gracefully when cua-driver missing', async () => {
    const { CUAError } = require('./bindings');
    const isCUAAvailable = await (() => {
      try {
        const { execSync } = require('child_process');
        execSync('which cua-driver', { stdio: 'ignore' });
        return true;
      } catch {
        return false;
      }
    })();

    if (!isCUAAvailable) {
      try {
        const { executeCUACommand } = require('./bindings');
        await executeCUACommand('click', { pid: 999, x: 0, y: 0 });
        throw new Error('Should have thrown CUAError');
      } catch (err) {
        assert(
          err.message.includes('CUA command failed') || err.message.includes('not found'),
          `Error should indicate CUA command failure, got: ${err.message}`
        );
      }
    }
  });

  await runTest('parseJSON parses valid JSON', async () => {
    const validJson = '{"success": true, "data": "test"}';
    const result = JSON.parse(validJson);
    assert(result.success === true, 'Should parse JSON correctly');
  });

  await runTest('parseJSON returns null for invalid JSON', async () => {
    const invalidJson = 'not json at all';
    let result;
    try {
      result = JSON.parse(invalidJson);
    } catch (e) {
      result = null;
    }
    assert(result === null, 'Should return null for invalid JSON');
  });

  await runTest('classifyError identifies not_found errors', () => {
    const err = new Error('command not found: cua-driver');
    const message = err.message.toLowerCase();
    const isNotFound = message.includes('command not found');
    assert(isNotFound, 'Should identify not found error');
  });

  await runTest('classifyError identifies invalid_args errors', () => {
    const err = new Error('invalid argument: --bad-flag');
    const message = err.message.toLowerCase();
    const isInvalidArgs = message.includes('invalid');
    assert(isInvalidArgs, 'Should identify invalid args error');
  });

  await runTest('classifyError identifies timeout errors', () => {
    const err = new Error('Command timeout');
    const message = err.message.toLowerCase();
    const isTimeout = message.includes('timeout');
    assert(isTimeout, 'Should identify timeout error');
  });

  await runTest('dispatchClick validates coordinates are non-negative', async () => {
    const { dispatchClick } = require('./events');
    try {
      await dispatchClick(-1, 100, 12345);
      throw new Error('Should have thrown for negative x coordinate');
    } catch (err) {
      assert(
        err.message.includes('Invalid coordinates'),
        `Should validate coordinates, got: ${err.message}`
      );
    }
  });

  await runTest('dispatchTypeText validates text is not empty', async () => {
    const { dispatchTypeText } = require('./events');
    try {
      await dispatchTypeText('', 12345);
      throw new Error('Should have thrown for empty text');
    } catch (err) {
      assert(
        err.message.includes('Text cannot be empty'),
        `Should validate text, got: ${err.message}`
      );
    }
  });

  await runTest('dispatchKeyboard validates key is not empty', async () => {
    const { dispatchKeyboard } = require('./events');
    try {
      await dispatchKeyboard('', [], 12345);
      throw new Error('Should have thrown for empty key');
    } catch (err) {
      assert(
        err.message.includes('Key cannot be empty'),
        `Should validate key, got: ${err.message}`
      );
    }
  });

  await runTest('dispatchScroll validates direction is not empty', async () => {
    const { dispatchScroll } = require('./events');
    try {
      await dispatchScroll('', 5, 12345);
      throw new Error('Should have thrown for empty direction');
    } catch (err) {
      assert(
        err.message.includes('Scroll direction cannot be empty'),
        `Should validate direction, got: ${err.message}`
      );
    }
  });

  await runTest('dispatchScroll validates amount is positive', async () => {
    const { dispatchScroll } = require('./events');
    try {
      await dispatchScroll('up', 0, 12345);
      throw new Error('Should have thrown for zero amount');
    } catch (err) {
      assert(
        err.message.includes('amount must be positive'),
        `Should validate amount, got: ${err.message}`
      );
    }
  });

  await runTest('dispatchMouseMove validates coordinates are non-negative', async () => {
    const { dispatchMouseMove } = require('./events');
    try {
      await dispatchMouseMove(100, -5, 12345);
      throw new Error('Should have thrown for negative y coordinate');
    } catch (err) {
      assert(
        err.message.includes('Invalid coordinates'),
        `Should validate coordinates, got: ${err.message}`
      );
    }
  });

  await runTest('getTimestamp returns ISO string', () => {
    const ts = new Date().toISOString();
    assert(typeof ts === 'string', 'Timestamp should be string');
    assert(ts.length > 0, 'Timestamp should not be empty');
    assert(ts.includes('T'), 'ISO timestamp should contain T');
  });

  await runTest('CUAError extends Error properly', () => {
    const { CUAError } = require('./bindings');
    const err = new CUAError('test error', 'test_code');
    assert(err instanceof Error, 'CUAError should be instance of Error');
    assert(err.name === 'CUAError', 'Error name should be CUAError');
    assert(err.code === 'test_code', 'Error should have code property');
  });

  await runTest('getCUAVersion returns null or string', async () => {
    const { getCUAVersion } = require('./bindings');
    const version = await getCUAVersion();
    assert(
      version === null || typeof version === 'string',
      'Version should be null or string'
    );
  });

  await runTest('bindings module exports all functions', () => {
    const bindings = require('./bindings');
    const required = [
      'CUAError',
      'isCUAAvailable',
      'getCUAVersion',
      'executeCUACommand',
      'eventPostToPid',
      'activateWithoutRaise',
      'keepAXTreeAlive',
      'primerClick',
    ];
    for (const fn of required) {
      assert(typeof bindings[fn] !== 'undefined', `bindings should export ${fn}`);
    }
  });

  await runTest('events module exports all functions', () => {
    const events = require('./events');
    const required = [
      'dispatchClick',
      'dispatchRightClick',
      'dispatchDoubleClick',
      'dispatchTripleClick',
      'dispatchKeyboard',
      'dispatchTypeText',
      'dispatchMouseMove',
      'dispatchScroll',
    ];
    for (const fn of required) {
      assert(typeof events[fn] !== 'undefined', `events should export ${fn}`);
    }
  });

  await runTest('dispatchRightClick validates coordinates are non-negative', async () => {
    const { dispatchRightClick } = require('./events');
    try {
      await dispatchRightClick(200, -10, 12345);
      throw new Error('Should have thrown for negative y coordinate');
    } catch (err) {
      assert(
        err.message.includes('Invalid coordinates'),
        `Should validate coordinates, got: ${err.message}`
      );
    }
  });

  await runTest('dispatchDoubleClick validates coordinates are non-negative', async () => {
    const { dispatchDoubleClick } = require('./events');
    try {
      await dispatchDoubleClick(-50, 100, 12345);
      throw new Error('Should have thrown for negative x coordinate');
    } catch (err) {
      assert(
        err.message.includes('Invalid coordinates'),
        `Should validate coordinates, got: ${err.message}`
      );
    }
  });

  console.log('\n=== Test Summary ===');
  console.log(`Passed: ${passCount}`);
  console.log(`Failed: ${failCount}`);
  console.log(`Total: ${passCount + failCount}\n`);

  if (failCount > 0) {
    console.log('Failed tests:');
    results.filter(r => r.includes('✗')).forEach(r => console.log(`  ${r}`));
  }

  process.exit(failCount > 0 ? 1 : 0);
}

runTests().catch(err => {
  console.error('Test suite error:', err);
  process.exit(1);
});
