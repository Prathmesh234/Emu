/**
 * frontend/emu/index.js
 *
 * Public API for the .emu module.
 */

const { initEmu, getEmuDir, EMU_DIR, WORKSPACE, SESSIONS, SKILLS, GLOBAL, MANIFEST } = require('./init');

module.exports = {
  initEmu,
  getEmuDir,
  EMU_DIR,
  WORKSPACE,
  SESSIONS,
  SKILLS,
  GLOBAL,
  MANIFEST,
};
