/**
 * Persistent PowerShell process — shared by all mouse/keyboard actions.
 *
 * Motivation: spawning a new powershell.exe per action costs 300–700 ms of
 * process startup. Running a single long-lived process with stdin piping
 * drops that to <5 ms per command.
 *
 * Usage (from any action register() function):
 *   const { run } = require('../process/psProcess');
 *   await run(`[System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point(100, 200)`);
 *
 * start() is called once in main.js as soon as the app is ready.
 * stop() is called in app 'will-quit'.
 */

const { spawn } = require('child_process');

let ps = null;
let buffer = '';
let pending = null;         // currently executing { cmd, resolve, reject }
const cmdQueue = [];        // waiting commands
const SENTINEL = '##PS_DONE##';

// ── Internal: dequeue and send the next command ────────────────────────────
function _flush() {
    if (pending || cmdQueue.length === 0 || !ps) return;
    pending = cmdQueue.shift();
    const preview = pending.cmd.slice(0, 80).replace(/\n/g, '\\n');
    console.log(`[psProcess] >> ${preview}${pending.cmd.length > 80 ? '...' : ''}`);
    // Append a sentinel write so we know exactly when the command finished
    ps.stdin.write(`${pending.cmd}\nWrite-Output "${SENTINEL}"\n`);
}

// ── Public: start the persistent process ──────────────────────────────────
function start() {
    if (ps) return;

    ps = spawn('powershell', ['-NoProfile', '-NonInteractive', '-Command', '-'], {
        stdio: ['pipe', 'pipe', 'pipe']
    });

    // Accumulate stdout and resolve pending promise when sentinel appears
    ps.stdout.on('data', chunk => {
        buffer += chunk.toString();
        const idx = buffer.indexOf(SENTINEL);
        if (idx !== -1 && pending) {
            const output = buffer.slice(0, idx).trim();
            buffer = buffer.slice(idx + SENTINEL.length).replace(/^\r?\n/, '');
            const preview = pending.cmd.slice(0, 60).replace(/\n/g, '\\n');
            console.log(`[psProcess] << done (${preview}) output=${output ? JSON.stringify(output) : '(empty)'}`);
            const { resolve } = pending;
            pending = null;
            resolve(output);
            _flush();
        }
    });

    ps.stderr.on('data', d => console.error('[psProcess]', d.toString().trim()));

    ps.on('exit', code => {
        console.warn('[psProcess] exited with code', code);
        ps = null;
        if (pending) {
            pending.reject(new Error('PowerShell process exited unexpectedly'));
            pending = null;
        }
        // Reject anything still waiting in the queue
        for (const item of cmdQueue) item.reject(new Error('PowerShell process exited'));
        cmdQueue.length = 0;
    });

    // Pre-load assemblies used by all actions.
    // Each run() call is a single-line command — no multi-line here-strings.
    // The queue serialises them automatically.
    const MEMBER_DEF = [
        '[DllImport("user32.dll")] public static extern void mouse_event(int f, int x, int y, int d, int e);',
        '[DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, int dwFlags, int dwExtraInfo);',
    ].join(' ');

    run('Add-Type -AssemblyName System.Windows.Forms')
        .then(() => console.log('[psProcess] Forms assembly loaded'))
        .catch(err => console.error('[psProcess] Forms load error:', err));

    run(`Add-Type -MemberDefinition '${MEMBER_DEF}' -Name U32 -Namespace W`)
        .then(() => console.log('[psProcess] U32 type loaded — ready'))
        .catch(err => console.error('[psProcess] U32 load error:', err));

    console.log('[psProcess] started');
}

// ── Public: run a PowerShell command, returns a Promise<string> ───────────
function run(cmd) {
    return new Promise((resolve, reject) => {
        if (!ps) {
            return reject(new Error('PowerShell process is not running. Call start() first.'));
        }
        cmdQueue.push({ cmd, resolve, reject });
        _flush();
    });
}

// ── Public: shut down the process (called on app quit) ────────────────────
function stop() {
    if (ps) {
        try { ps.stdin.end(); } catch (_) {}
        ps = null;
        console.log('[psProcess] stopped');
    }
}

module.exports = { start, run, stop };
