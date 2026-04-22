/**
 * frontend/process/backendProcess.js — Lifecycle for the FastAPI backend.
 *
 * In development (source checkout): spawns `./backend.sh`. Requires the
 * developer to have `uv` installed — same requirement as running it by
 * hand, but now hidden behind `npm run dev`.
 *
 * In a packaged app: spawns the frozen backend binary shipped inside
 * Resources/. That binary is self-contained (PyInstaller) and needs no
 * system Python.
 *
 * Opt-out: set EMU_SKIP_BACKEND_SPAWN=1 to keep the historical workflow of
 * running backend.sh in a separate terminal. Useful when iterating on
 * backend code with --reload.
 */

const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

let _child = null;

function _resolveBackendCommand(app) {
    // Packaged: look for the frozen binary inside Resources/.
    if (app && app.isPackaged) {
        const resourcesPath = process.resourcesPath;
        const candidates = [
            path.join(resourcesPath, 'backend', 'emu-backend'),
            path.join(resourcesPath, 'backend', 'emu-backend.exe'),
        ];
        for (const c of candidates) {
            if (fs.existsSync(c)) return { cmd: c, args: [], cwd: path.dirname(c) };
        }
        return null;
    }

    // Dev: spawn backend.sh from the repo root.
    const repoRoot = path.resolve(__dirname, '..', '..');
    const script = path.join(repoRoot, 'backend.sh');
    if (!fs.existsSync(script)) return null;
    return { cmd: '/bin/bash', args: [script], cwd: repoRoot };
}

function start({ app, emuRoot, authToken }) {
    if (_child) return;

    if (process.env.EMU_SKIP_BACKEND_SPAWN === '1') {
        console.log('[backend] EMU_SKIP_BACKEND_SPAWN=1 — not spawning');
        return;
    }

    const spec = _resolveBackendCommand(app);
    if (!spec) {
        console.warn('[backend] no backend command resolved — skipping spawn');
        return;
    }

    const env = {
        ...process.env,
        EMU_ROOT: emuRoot,
    };
    if (authToken) env.EMU_AUTH_TOKEN = authToken;

    console.log(`[backend] spawning ${spec.cmd} ${spec.args.join(' ')}`);
    _child = spawn(spec.cmd, spec.args, {
        cwd: spec.cwd,
        env,
        stdio: ['ignore', 'pipe', 'pipe'],
    });

    _child.stdout.on('data', (d) => process.stdout.write(`[backend] ${d}`));
    _child.stderr.on('data', (d) => process.stderr.write(`[backend] ${d}`));

    _child.on('exit', (code, signal) => {
        console.warn(`[backend] exited code=${code} signal=${signal}`);
        _child = null;
    });
}

function stop() {
    if (!_child) return;
    try {
        // SIGTERM lets uvicorn shut down cleanly.
        _child.kill('SIGTERM');
    } catch (_) { /* already gone */ }
    // Hard-kill fallback after a grace period.
    const pid = _child.pid;
    setTimeout(() => {
        try { process.kill(pid, 'SIGKILL'); } catch (_) {}
    }, 3000).unref();
    _child = null;
}

module.exports = { start, stop };
