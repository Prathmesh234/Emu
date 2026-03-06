/**
 * frontend/emu/init.js
 *
 * Idempotent .emu/ folder scaffold.
 * Called once from main.js on app.whenReady().
 * Creates the directory tree and default workspace files only if they
 * don't already exist (manifest.json is the creation guard).
 */

const fs   = require('fs');
const path = require('path');
const os   = require('os');

// ── Paths ──────────────────────────────────────────────────────────────────
const PROJECT_ROOT = path.resolve(__dirname, '..', '..');
const EMU_DIR      = path.join(PROJECT_ROOT, '.emu');
const WORKSPACE    = path.join(EMU_DIR, 'workspace');
const MEMORY       = path.join(WORKSPACE, 'memory');
const SESSIONS     = path.join(EMU_DIR, 'sessions');
const GLOBAL       = path.join(EMU_DIR, 'global');
const MANIFEST     = path.join(EMU_DIR, 'manifest.json');

// ── Default workspace file contents ────────────────────────────────────────
const DEFAULTS = require('./defaults');

// ── Public API ─────────────────────────────────────────────────────────────

/**
 * Ensure .emu/ exists with all required subdirectories and default files.
 * Safe to call on every launch — skips anything already present.
 *
 * @param {string} appVersion - package.json version (passed from main.js)
 * @returns {{ created: boolean, emuDir: string }}
 */
function initEmu(appVersion = '0.0.0') {
  const alreadyExists = fs.existsSync(MANIFEST);

  // 1. Create directory tree
  [EMU_DIR, WORKSPACE, MEMORY, SESSIONS, GLOBAL].forEach(dir => {
    fs.mkdirSync(dir, { recursive: true });
  });

  // 2. Write default workspace files (only if missing)
  const workspaceFiles = {
    'SOUL.md':      DEFAULTS.SOUL,
    'AGENTS.md':    DEFAULTS.AGENTS,
    'USER.md':      DEFAULTS.USER,
    'IDENTITY.md':  DEFAULTS.IDENTITY,
    'MEMORY.md':    DEFAULTS.MEMORY_FILE,
    'BOOTSTRAP.md': DEFAULTS.BOOTSTRAP,
  };

  for (const [filename, content] of Object.entries(workspaceFiles)) {
    const filePath = path.join(WORKSPACE, filename);
    if (!fs.existsSync(filePath)) {
      fs.writeFileSync(filePath, content, 'utf-8');
    }
  }

  // 3. Write global preferences (only if missing)
  const prefsPath = path.join(GLOBAL, 'preferences.md');
  if (!fs.existsSync(prefsPath)) {
    fs.writeFileSync(prefsPath, DEFAULTS.PREFERENCES, 'utf-8');
  }

  // 4. Write or update manifest.json
  if (!alreadyExists) {
    const manifest = {
      schema_version: 1,
      created_at:     new Date().toISOString(),
      app_version:    appVersion,
      bootstrap_complete: false,
      sessions: {
        total:           0,
        last_session_id: null,
        last_active_at:  null,
      },
      providers: {
        active:  'claude',
        history: ['claude'],
      },
      platform: {
        os:       os.platform(),
        arch:     os.arch(),
        electron: process.versions.electron || 'unknown',
        python:   'unknown',   // filled in by backend later
      },
    };
    fs.writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2), 'utf-8');
  }

  console.log(`[emu] .emu/ ${alreadyExists ? 'verified' : 'created'} at ${EMU_DIR}`);
  return { created: !alreadyExists, emuDir: EMU_DIR };
}

/**
 * Return absolute path to the .emu directory.
 */
function getEmuDir() {
  return EMU_DIR;
}

module.exports = { initEmu, getEmuDir, EMU_DIR, WORKSPACE, SESSIONS, GLOBAL, MANIFEST };
