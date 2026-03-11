/**
 * Persistent PowerShell process — shared by all mouse/keyboard actions.
 *
 * Motivation: spawning a new powershell.exe per action costs 300–700 ms of
 * process startup. Running a single long-lived process with stdin piping
 * drops that to <5 ms per command.
 *
 * Commands are Base64-encoded before piping to prevent unclosed quotes,
 * here-strings, or multi-line content from consuming the sentinel marker.
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
const ERR_MARKER = '##PS_ERR##';
const CMD_TIMEOUT_MS = 30_000;  // 30s per-command timeout

// ── Internal: dequeue and send the next command ────────────────────────────
function _flush() {
    if (pending || cmdQueue.length === 0 || !ps) return;
    pending = cmdQueue.shift();
    const preview = pending.cmd.slice(0, 80).replace(/\n/g, '\\n');
    console.log(`[psProcess] >> ${preview}${pending.cmd.length > 80 ? '...' : ''}`);

    // Start a timeout timer — if the command doesn't complete in time, reject it
    pending.timer = setTimeout(() => {
        if (!pending) return;
        const { reject } = pending;
        const timedOutCmd = pending.cmd.slice(0, 80);
        console.error(`[psProcess] TIMEOUT (${CMD_TIMEOUT_MS}ms): ${timedOutCmd}`);
        pending = null;
        // Drain any partial output so it doesn't bleed into the next command
        buffer = '';
        reject(new Error(`Command timed out after ${CMD_TIMEOUT_MS / 1000}s. Avoid long-running or recursive commands.`));
        _flush();
    }, CMD_TIMEOUT_MS);

    // Base64-encode the command so that any quotes, here-strings, or
    // multi-line content can never interfere with the sentinel line.
    // On the PowerShell side we decode → create a ScriptBlock → dot-source it
    // in the current scope (so Add-Type, variable assignments, etc. persist).
    const encoded = Buffer.from(pending.cmd, 'utf-8').toString('base64');
    const wrapped = [
        `$_enc_ = '${encoded}'`,
        `$_code_ = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_enc_))`,
        `try { $_sb_ = [ScriptBlock]::Create($_code_); . $_sb_ } catch { Write-Output "${ERR_MARKER}$($_.Exception.Message)" }`,
        `Write-Output "${SENTINEL}"`,
    ].join('; ');

    ps.stdin.write(wrapped + '\n');
}

// ── Public: start the persistent process ──────────────────────────────────
function start() {
    if (ps) return;

    ps = spawn('powershell', ['-NoProfile', '-NonInteractive', '-Command', '-'], {
        stdio: ['pipe', 'pipe', 'pipe']
    });

    // Accumulate stdout and resolve pending promise when sentinel appears.
    // Uses a loop to handle multiple sentinels arriving in a single chunk
    // (can happen if commands complete very quickly back-to-back).
    ps.stdout.on('data', chunk => {
        buffer += chunk.toString();
        _drainBuffer();
    });

    function _drainBuffer() {
        let idx;
        while ((idx = buffer.indexOf(SENTINEL)) !== -1 && pending) {
            let output = buffer.slice(0, idx).trim();
            buffer = buffer.slice(idx + SENTINEL.length).replace(/^\r?\n/, '');

            const cmdPreview = pending.cmd.slice(0, 60).replace(/\n/g, '\\n');

            // Check for error marker emitted by the catch block
            let error = null;
            const errIdx = output.lastIndexOf(ERR_MARKER);
            if (errIdx !== -1) {
                error = output.slice(errIdx + ERR_MARKER.length).trim();
                output = output.slice(0, errIdx).trim();
            }

            if (pending.timer) clearTimeout(pending.timer);
            const { resolve, reject } = pending;
            pending = null;

            if (error) {
                console.log(`[psProcess] << error (${cmdPreview}): ${error}`);
                reject(new Error(error));
            } else {
                const outputPreview = output ? JSON.stringify(output).slice(0, 200) : '(empty)';
                console.log(`[psProcess] << done (${cmdPreview}) output=${outputPreview}`);
                resolve(output);
            }
            _flush();
        }
    }

    ps.stderr.on('data', d => console.error('[psProcess] stderr:', d.toString().trim()));

    ps.on('exit', code => {
        console.warn('[psProcess] exited with code', code);
        ps = null;
        if (pending) {
            if (pending.timer) clearTimeout(pending.timer);
            pending.reject(new Error('PowerShell process exited unexpectedly'));
            pending = null;
        }
        // Reject anything still waiting in the queue
        for (const item of cmdQueue) item.reject(new Error('PowerShell process exited'));
        cmdQueue.length = 0;
    });

    // Pre-load assemblies and P/Invoke types used by all actions.
    const MEMBER_DEF = [
        '[DllImport("user32.dll")] public static extern void mouse_event(int f, int x, int y, int d, int e);',
        '[DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, int dwFlags, int dwExtraInfo);',
    ].join(' ');

    // GDI types for physical-pixel screen capture (GetDeviceCaps).
    const GDI_DEF = [
        '[DllImport("gdi32.dll")] public static extern int GetDeviceCaps(IntPtr hdc, int index);',
        '[DllImport("user32.dll")] public static extern IntPtr GetDC(IntPtr hwnd);',
        '[DllImport("user32.dll")] public static extern int ReleaseDC(IntPtr hwnd, IntPtr hdc);',
    ].join(' ');

    run('Add-Type -AssemblyName System.Windows.Forms')
        .then(() => console.log('[psProcess] Forms assembly loaded'))
        .catch(err => console.error('[psProcess] Forms load error:', err));

    run(`Add-Type -MemberDefinition '${MEMBER_DEF}' -Name U32 -Namespace W`)
        .then(() => console.log('[psProcess] U32 type loaded — ready'))
        .catch(err => console.error('[psProcess] U32 load error:', err));

    run(`Add-Type -MemberDefinition '${GDI_DEF}' -Name GDI -Namespace W`)
        .then(() => console.log('[psProcess] GDI type loaded'))
        .catch(err => console.error('[psProcess] GDI load error:', err));

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
        try { ps.kill('SIGTERM'); } catch (_) {}
        ps = null;
        pending = null;
        cmdQueue.length = 0;
        console.log('[psProcess] stopped');
    }
}

module.exports = { start, run, stop };
