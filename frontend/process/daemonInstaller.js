/**
 * frontend/process/daemonInstaller.js — Auto-install the macOS memory
 * daemon LaunchAgent on app startup if it isn't installed yet.
 *
 * Dev mode (source checkout):
 *   Runs `python3 -m daemon.install_macos install` from the repo root
 *   with EMU_ROOT set. Requires python3 on PATH (stdlib plistlib only).
 *
 * Packaged DMG:
 *   Guarded by PACKAGED_MODE=1. When enabled, spawns the frozen
 *   `emu-daemon` runtime from the .app Resources directory.
 *
 * The installer itself is idempotent — if the plist is already loaded
 * and current, it's a no-op. We still invoke it when a plist exists so
 * it can repair stale paths after the app/repo moves.
 *
 * Opt-out: EMU_SKIP_DAEMON_INSTALL=1
 */

const os = require('os');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

const LABEL = 'com.emu.memory-daemon';
const PLIST_PATH = path.join(os.homedir(), 'Library', 'LaunchAgents', `${LABEL}.plist`);
const PACKAGED_MODE_FLAG = process.env.PACKAGED_MODE || '0';
const PACKAGED_MODE = PACKAGED_MODE_FLAG === '1';

function _pythonBin(repoRoot) {
    // Prefer the repo's venv python if present — it matches what dev runs
    // manually, and isolates from system python quirks.
    const venvPy = path.join(repoRoot, '.venv', 'bin', 'python3');
    if (fs.existsSync(venvPy)) return venvPy;
    return 'python3';
}

function _packagedDaemonBin(app) {
    if (!app || !app.isPackaged || !PACKAGED_MODE) return null;
    const resourcesPath = process.resourcesPath || '';
    const candidates = [
        path.join(resourcesPath, 'daemon', 'emu-daemon'),
        path.join(resourcesPath, 'daemon', 'emu-daemon.exe'),
        path.join(resourcesPath, 'emu-daemon'),
        path.join(resourcesPath, 'emu-daemon.exe'),
    ];
    return candidates.find((candidate) => fs.existsSync(candidate)) || null;
}

function _commandSpec({ app, command }) {
    if (app && app.isPackaged) {
        if (!PACKAGED_MODE) return null;
        const daemonBin = _packagedDaemonBin(app);
        if (!daemonBin) return null;
        return { cmd: daemonBin, args: [command], cwd: path.dirname(daemonBin) };
    }

    const repoRoot = path.resolve(__dirname, '..', '..');
    const py = _pythonBin(repoRoot);
    return { cmd: py, args: ['-m', 'daemon.install_macos', command], cwd: repoRoot };
}

function _runInstallerCommand({ app, emuRoot, command }) {
    return new Promise((resolve) => {
        if (process.platform !== 'darwin') {
            resolve({ ok: true, skipped: true, stdout: 'not macOS', stderr: '' });
            return;
        }

        const spec = _commandSpec({ app, command });
        if (!spec) {
            const reason = app && app.isPackaged
                ? 'packaged daemon install disabled (PACKAGED_MODE=0) or packaged runtime missing'
                : 'daemon installer command unavailable';
            resolve({ ok: false, skipped: true, stdout: '', stderr: reason });
            return;
        }

        const env = { ...process.env, EMU_ROOT: emuRoot };
        const child = spawn(spec.cmd, spec.args, {
            cwd: spec.cwd,
            env,
            stdio: ['ignore', 'pipe', 'pipe'],
        });

        // Echo the child's output to the parent terminal only for commands
        // the human likely wants to see (install/repair). `status` is polled
        // by the Settings panel every time it opens — echoing its verbose
        // `launchctl print` + last-3-ticks output spams the backend log.
        const echo = command !== 'status';

        let stdout = '';
        let stderr = '';
        child.stdout.on('data', (d) => {
            const text = d.toString();
            stdout += text;
            if (echo) process.stdout.write(`[daemon-install] ${text}`);
        });
        child.stderr.on('data', (d) => {
            const text = d.toString();
            stderr += text;
            if (echo) process.stderr.write(`[daemon-install] ${text}`);
        });
        child.on('error', (err) => {
            resolve({ ok: false, skipped: false, stdout, stderr: stderr || err.message });
        });
        child.on('exit', (code) => {
            resolve({ ok: code === 0, skipped: false, code, stdout, stderr });
        });
    });
}

function maybeInstall({ app, emuRoot }) {
    if (process.platform !== 'darwin') return;
    if (process.env.EMU_SKIP_DAEMON_INSTALL === '1') {
        console.log('[daemon-install] EMU_SKIP_DAEMON_INSTALL=1 — skipping');
        return;
    }
    if (app && app.isPackaged && !PACKAGED_MODE) {
        console.log('[daemon-install] packaged mode disabled (PACKAGED_MODE=0) — skipping');
        return;
    }

    console.log('[daemon-install] installing/repairing LaunchAgent');
    _runInstallerCommand({ app, emuRoot, command: 'install' }).then((result) => {
        if (result.ok) console.log('[daemon-install] installed OK');
        else console.warn(`[daemon-install] install failed: ${result.stderr || result.code || 'unknown error'}`);
    });
}

async function getStatus({ app, emuRoot }) {
    const plistPresent = fs.existsSync(PLIST_PATH);
    if (process.platform !== 'darwin') {
        return { ok: true, platform: process.platform, plistPresent, loaded: false, current: false, detail: 'not macOS' };
    }

    if (app && app.isPackaged && !PACKAGED_MODE) {
        return {
            ok: true,
            platform: process.platform,
            packagedMode: false,
            plistPresent,
            loaded: plistPresent,
            current: false,
            detail: 'packaged daemon install disabled',
        };
    }

    const result = await _runInstallerCommand({ app, emuRoot, command: 'status' });
    const output = `${result.stdout || ''}\n${result.stderr || ''}`;
    return {
        ok: result.ok,
        platform: process.platform,
        packagedMode: PACKAGED_MODE,
        plistPresent,
        loaded: /Loaded:\s+true/.test(output),
        current: /Current:\s+true/.test(output),
        detail: output.trim() || result.stderr || '',
    };
}

async function repair({ app, emuRoot }) {
    return _runInstallerCommand({ app, emuRoot, command: 'install' });
}

module.exports = { maybeInstall, getStatus, repair, PLIST_PATH, PACKAGED_MODE };
