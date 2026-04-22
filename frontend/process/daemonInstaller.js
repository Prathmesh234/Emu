/**
 * frontend/process/daemonInstaller.js — Auto-install the macOS memory
 * daemon LaunchAgent on app startup if it isn't installed yet.
 *
 * Dev mode (source checkout):
 *   Runs `python3 -m daemon.install_macos install` from the repo root
 *   with EMU_ROOT set. Requires python3 on PATH (stdlib plistlib only).
 *
 * Packaged DMG:
 *   Deferred. Will spawn the frozen `emu-daemon --install` binary from
 *   inside the .app bundle once PyInstaller packaging lands.
 *
 * The installer itself is idempotent — if the plist is already loaded
 * and current, it's a no-op. We additionally early-out here when the
 * plist file exists so we don't shell out on every launch.
 *
 * Opt-out: EMU_SKIP_DAEMON_INSTALL=1
 */

const os = require('os');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

const LABEL = 'com.emu.memory-daemon';
const PLIST_PATH = path.join(os.homedir(), 'Library', 'LaunchAgents', `${LABEL}.plist`);

function _pythonBin(repoRoot) {
    // Prefer the repo's venv python if present — it matches what dev runs
    // manually, and isolates from system python quirks.
    const venvPy = path.join(repoRoot, '.venv', 'bin', 'python3');
    if (fs.existsSync(venvPy)) return venvPy;
    return 'python3';
}

function maybeInstall({ app, emuRoot }) {
    if (process.platform !== 'darwin') return;
    if (process.env.EMU_SKIP_DAEMON_INSTALL === '1') {
        console.log('[daemon-install] EMU_SKIP_DAEMON_INSTALL=1 — skipping');
        return;
    }
    if (fs.existsSync(PLIST_PATH)) {
        console.log(`[daemon-install] plist already present at ${PLIST_PATH} — skipping`);
        return;
    }

    // Packaged path deferred until frozen daemon binary is shipped.
    if (app && app.isPackaged) {
        console.log('[daemon-install] packaged mode — auto-install not yet implemented, skipping');
        return;
    }

    const repoRoot = path.resolve(__dirname, '..', '..');
    const py = _pythonBin(repoRoot);
    const env = { ...process.env, EMU_ROOT: emuRoot };

    console.log(`[daemon-install] installing LaunchAgent via ${py} -m daemon.install_macos install`);
    const child = spawn(py, ['-m', 'daemon.install_macos', 'install'], {
        cwd: repoRoot,
        env,
        stdio: ['ignore', 'pipe', 'pipe'],
    });
    child.stdout.on('data', (d) => process.stdout.write(`[daemon-install] ${d}`));
    child.stderr.on('data', (d) => process.stderr.write(`[daemon-install] ${d}`));
    child.on('exit', (code) => {
        if (code === 0) console.log('[daemon-install] installed OK');
        else console.warn(`[daemon-install] exited with code ${code}`);
    });
}

module.exports = { maybeInstall, PLIST_PATH };
