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
const crypto = require('crypto');
const { screen } = require('electron');

// ── Paths ──────────────────────────────────────────────────────────────────
const PROJECT_ROOT = path.resolve(__dirname, '..', '..');
const EMU_DIR      = path.join(PROJECT_ROOT, '.emu');
const WORKSPACE    = path.join(EMU_DIR, 'workspace');
const MEMORY       = path.join(WORKSPACE, 'memory');
const SESSIONS     = path.join(EMU_DIR, 'sessions');
const SKILLS       = path.join(EMU_DIR, 'skills');
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
  [EMU_DIR, WORKSPACE, MEMORY, SESSIONS, SKILLS, GLOBAL].forEach(dir => {
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

  // 4. Gather device / display details for the manifest
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width: screenWidth, height: screenHeight } = primaryDisplay.size;
  const scaleFactor = primaryDisplay.scaleFactor || 1;
  const physicalWidth  = Math.round(screenWidth * scaleFactor);
  const physicalHeight = Math.round(screenHeight * scaleFactor);

  // Collect macOS version information
  const osVersion = typeof process.getSystemVersion === 'function'
      ? process.getSystemVersion()     // Electron API: e.g. "14.5.0"
      : os.release();                  // Fallback: Darwin kernel version

  // Map macOS version number to marketing name
  const macOSNames = {
    '15': 'Sequoia', '14': 'Sonoma', '13': 'Ventura', '12': 'Monterey',
    '11': 'Big Sur', '10.15': 'Catalina', '10.14': 'Mojave',
  };
  const majorVersion = osVersion.split('.').slice(0, os.platform() === 'darwin' && parseInt(osVersion) >= 11 ? 1 : 2).join('.');
  const macOSName = macOSNames[majorVersion] || '';
  const osDisplayName = os.platform() === 'darwin'
      ? `macOS ${macOSName} ${osVersion}`.trim()
      : `${os.platform()} ${osVersion}`;

  const deviceDetails = {
    screen_width:    screenWidth,
    screen_height:   screenHeight,
    scale_factor:    scaleFactor,
    physical_width:  physicalWidth,
    physical_height: physicalHeight,
    color_depth:     primaryDisplay.colorDepth || null,
    rotation:        primaryDisplay.rotation || 0,
    coordinate_system: 'normalized_0_1',
  };

  // Gather hardware info (no personal data)
  const cpus = os.cpus();
  const hardware = {
    cpu_model:    cpus.length > 0 ? cpus[0].model.trim() : 'unknown',
    cpu_cores:    cpus.length,
    total_memory_gb: Math.round(os.totalmem() / (1024 ** 3) * 10) / 10,
    free_memory_gb:  Math.round(os.freemem() / (1024 ** 3) * 10) / 10,
    endianness:   os.endianness(),
  };

  // Working directory info — expose folder name only, never full path
  const workingDir = {
    folder_name:  path.basename(PROJECT_ROOT),
    is_git_repo:  fs.existsSync(path.join(PROJECT_ROOT, '.git')),
  };

  // Anonymized device fingerprint (hashed hostname, no PII)
  const deviceId = crypto.createHash('sha256').update(os.hostname()).digest('hex').slice(0, 12);

  // 5. Write or update manifest.json
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
        os:           os.platform(),
        os_version:   osVersion,
        os_name:      osDisplayName,
        arch:         os.arch(),
        electron:     process.versions.electron || 'unknown',
        node:         process.versions.node || 'unknown',
        chrome:       process.versions.chrome || 'unknown',
        python:       'unknown',   // filled in by backend later
      },
      device_details: deviceDetails,
      hardware,
      working_directory: workingDir,
      device_id: deviceId,
      system: {
        uptime_hours:  Math.round(os.uptime() / 3600 * 10) / 10,
        shell:         process.env.SHELL || process.env.COMSPEC || 'unknown',
        locale:        Intl.DateTimeFormat().resolvedOptions().locale || 'unknown',
        timezone:      Intl.DateTimeFormat().resolvedOptions().timeZone || 'unknown',
      },
    };
    fs.writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2), 'utf-8');
  } else {
    // Always update device_details, hardware, and platform on launch (screen or OS may have changed)
    try {
      const existing = JSON.parse(fs.readFileSync(MANIFEST, 'utf-8'));
      existing.device_details = deviceDetails;
      existing.hardware = hardware;
      existing.working_directory = workingDir;
      existing.device_id = existing.device_id || deviceId;
      existing.platform = {
        ...existing.platform,
        os:         os.platform(),
        os_version: osVersion,
        os_name:    osDisplayName,
        arch:       os.arch(),
        electron:   process.versions.electron || 'unknown',
        node:       process.versions.node || 'unknown',
        chrome:     process.versions.chrome || 'unknown',
      };
      existing.system = {
        uptime_hours:  Math.round(os.uptime() / 3600 * 10) / 10,
        shell:         process.env.SHELL || process.env.COMSPEC || 'unknown',
        locale:        Intl.DateTimeFormat().resolvedOptions().locale || 'unknown',
        timezone:      Intl.DateTimeFormat().resolvedOptions().timeZone || 'unknown',
      };
      fs.writeFileSync(MANIFEST, JSON.stringify(existing, null, 2), 'utf-8');
    } catch (e) {
      console.warn('[emu] failed to update device_details in manifest:', e.message);
    }
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

module.exports = { initEmu, getEmuDir, EMU_DIR, WORKSPACE, SESSIONS, SKILLS, GLOBAL, MANIFEST };
