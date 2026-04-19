// components/conversation/Greeting.js — Idle frame greeting
//
// Part of the Emu Design System v1 refactor (see FRONTEND_REDESIGN.md).
// Design source: Emu-handoff.zip → project/frames/frames-a.jsx > F_Idle
//
// Changes vs prior version:
//   - First name only: uses `id -F` (macOS display name) then takes first word.
//     Falls back to USER env var split on common separators.
//   - Memory hint: reads first meaningful line from .emu/workspace/MEMORY.md
//     and shows it below the subtitle as a dim italic "continue from" nudge.

const fs   = require('fs');
const path = require('path');
const { execSync } = require('child_process');

function Greeting() {
    const wrap = document.createElement('div');
    wrap.className = 'idle-greeting';

    // ── Heading: "Good afternoon, Prathmesh." ─────────────────────────────
    const heading = document.createElement('h1');
    heading.className = 'idle-greeting-heading';

    const greetText = _timeGreeting();
    const name = _firstName();

    heading.appendChild(document.createTextNode(greetText + ', '));
    const em = document.createElement('em');
    em.textContent = name;
    heading.appendChild(em);
    heading.appendChild(document.createTextNode('.'));
    wrap.appendChild(heading);

    // ── Subtitle ──────────────────────────────────────────────────────────
    const sub = document.createElement('p');
    sub.className = 'idle-greeting-sub';
    sub.textContent = 'Tell me what to do and I\'ll take it from there.';
    wrap.appendChild(sub);

    // ── Memory hint (from .emu/workspace/MEMORY.md) ───────────────────────
    const hint = _memoryHint();
    if (hint) {
        const hintEl = document.createElement('p');
        hintEl.className = 'idle-greeting-hint';
        hintEl.textContent = hint;
        wrap.appendChild(hintEl);
    }

    return { element: wrap };
}

// ── Private helpers ───────────────────────────────────────────────────────

function _timeGreeting() {
    const h = new Date().getHours();
    if (h < 12) return 'Good morning';
    if (h < 18) return 'Good afternoon';
    return 'Good evening';
}

function _firstName() {
    // Preferred: macOS Full Name via `id -F` (e.g. "Prathmesh Bhatt" → "Prathmesh")
    try {
        const full = execSync('id -F', { timeout: 500, stdio: ['pipe', 'pipe', 'ignore'] })
            .toString().trim();
        if (full) return full.split(/\s+/)[0];
    } catch (_) { /* fallback below */ }

    // Fallback: USER env var, split on `.` / `_` / space
    const raw = (typeof process !== 'undefined' && process.env && process.env.USER) || '';
    if (!raw) return 'there';
    const first = raw.split(/[._\s]/)[0];
    return first.charAt(0).toUpperCase() + first.slice(1).toLowerCase();
}

function _memoryHint() {
    try {
        // __dirname = frontend/components/conversation → ../../../.emu
        const emuRoot = path.join(__dirname, '..', '..', '..', '.emu');
        const memPath = path.join(emuRoot, 'workspace', 'MEMORY.md');
        const raw = fs.readFileSync(memPath, 'utf-8').trim();
        if (!raw) return null;

        // Skip headings; take the first non-empty bullet/line
        const firstLine = raw
            .split('\n')
            .map(l => l.trim())
            .find(l => l && !l.startsWith('#'));

        if (!firstLine) return null;

        // Strip markdown list marker, limit to ~100 chars
        const clean = firstLine.replace(/^[-*•]\s*/, '').trim();
        return clean.length > 100 ? clean.slice(0, 97) + '…' : clean;
    } catch (_) {
        return null;
    }
}

module.exports = { Greeting };
