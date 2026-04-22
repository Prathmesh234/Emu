/**
 * Persistent shell process — shared by all mouse/keyboard actions.
 *
 * Motivation: spawning a new shell per action costs 100–300 ms of
 * process startup. Running a single long-lived process with stdin piping
 * drops that to <5 ms per command.
 *
 * Commands are Base64-encoded before piping to prevent unclosed quotes,
 * here-strings, or multi-line content from consuming the sentinel marker.
 *
 * Usage (from any action register() function):
 *   const { run } = require('../process/psProcess');
 *   await run(`xdotool mousemove 100 200`);
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

const isMac = process.platform === 'darwin';

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

    // Base64-encode the command so that any quotes or multi-line content
    // can never interfere with the sentinel line.
    // On the bash side we decode → eval in the current shell.
    const encoded = Buffer.from(pending.cmd, 'utf-8').toString('base64');
    const decode = isMac
        ? `_code_=$(echo "$_enc_" | base64 -D)`
        : `_code_=$(echo "$_enc_" | base64 -d)`;

    // Decode, eval in the current shell, capture exit status.
    // stderr is sent to a temp file so it doesn't contaminate stdout
    // (critical for screenshot base64 output). On failure the stderr
    // contents are surfaced via ERR_MARKER.
    const safeWrapped = [
        `_enc_='${encoded}'`,
        decode,
        `_stderr_=$(mktemp)`,
        `eval "$_code_" 2>"$_stderr_"; _rc_=$?`,
        `if [ $_rc_ -ne 0 ]; then _emsg_=$(cat "$_stderr_" 2>/dev/null); rm -f "$_stderr_"; echo "${ERR_MARKER}$_emsg_"; else rm -f "$_stderr_"; fi`,
        `echo "${SENTINEL}"`,
    ].join('; ');

    ps.stdin.write(safeWrapped + '\n');
}

// ── Public: start the persistent process ──────────────────────────────────
// Secrets are stripped from the child environment so that an LLM-triggered
// `env`, `printenv`, `cat /proc/self/environ`, or shell substitution cannot
// exfiltrate provider API keys. The Node/Electron main process still has
// them (needed for its own API calls); only the agent-controlled shell is
// sanitized. Extend this list whenever a new provider lands.
const _SECRET_ENV_KEYS = [
    'ANTHROPIC_API_KEY',
    'OPENAI_API_KEY',
    'OPENROUTER_API_KEY',
    'GOOGLE_API_KEY',
    'GEMINI_API_KEY',
    'AZURE_OPENAI_API_KEY',
    'AZURE_OPENAI_ENDPOINT',
    'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY',
    'AWS_SESSION_TOKEN',
    'FIREWORKS_API_KEY',
    'TOGETHER_API_KEY',
    'BASETEN_API_KEY',
    'BASETEN_API_URL',
    'H_COMPANY_API_KEY',
    'EMU_DAEMON_API_KEY',
    'EMU_AUTH_TOKEN',
    'GITHUB_TOKEN',
    'HF_TOKEN',
    'HUGGING_FACE_HUB_TOKEN',
];

function _sanitizeEnv() {
    const out = { ...process.env, TERM: 'dumb' };
    for (const k of _SECRET_ENV_KEYS) delete out[k];
    // Defense-in-depth: drop anything that looks like a credential by name.
    for (const k of Object.keys(out)) {
        if (/(_API_KEY|_SECRET|_TOKEN|_PASSWORD|_PRIVATE_KEY)$/i.test(k)) {
            delete out[k];
        }
    }
    return out;
}

function start() {
    if (ps) return;

    const shell = isMac ? '/bin/zsh' : '/bin/bash';
    const shellArgs = isMac ? ['-f'] : ['--norc', '--noprofile'];
    ps = spawn(shell, shellArgs, {
        stdio: ['pipe', 'pipe', 'pipe'],
        env: _sanitizeEnv()
    });

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
            pending.reject(new Error('Shell process exited unexpectedly'));
            pending = null;
        }
        for (const item of cmdQueue) item.reject(new Error('Shell process exited'));
        cmdQueue.length = 0;
    });

    console.log(`[psProcess] started (${shell})`);
}

// ── Public: run a shell command, returns a Promise<string> ────────────────
function run(cmd) {
    return new Promise((resolve, reject) => {
        if (!ps) {
            return reject(new Error('Shell process is not running. Call start() first.'));
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

module.exports = { start, run, stop, isMac };
