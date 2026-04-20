// components/conversation/Greeting.js — Idle frame greeting
//
// Part of the Emu Design System v1 refactor (see FRONTEND_REDESIGN.md).
// Design source: Emu-handoff.zip → project/frames/frames-a.jsx > F_Idle
//
// Layout:
//   "Good afternoon, Prathmesh."          (large serif, italic first name)
//   <contextual subtitle>                  (what the user was recently on)
//
// The subtitle starts with a neutral fallback ("Tell me what to do…"),
// then asynchronously reads the latest .emu/workspace/memory/YYYY-MM-DD.md
// file and asks the configured EMU_DAEMON_* provider for a one-sentence
// recap. If any step fails (no memory, no API key, network error) the
// fallback stays.

const fs   = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const FALLBACK_SUB = "Tell me what to do and I'll take it from there.";
const EMU_ROOT = path.join(__dirname, '..', '..', '..', '.emu');

function Greeting() {
    const wrap = document.createElement('div');
    wrap.className = 'idle-greeting';

    // ── Heading ───────────────────────────────────────────────────────────
    const heading = document.createElement('h1');
    heading.className = 'idle-greeting-heading';

    heading.appendChild(document.createTextNode(_timeGreeting() + ', '));
    const em = document.createElement('em');
    em.textContent = _firstName();
    heading.appendChild(em);
    heading.appendChild(document.createTextNode('.'));
    wrap.appendChild(heading);

    // ── Subtitle (neutral fallback first, contextual updated async) ───────
    const sub = document.createElement('p');
    sub.className = 'idle-greeting-sub';
    sub.textContent = FALLBACK_SUB;
    wrap.appendChild(sub);

    _fetchContextualSubtitle().then(text => {
        if (!text || !sub.isConnected) return;
        sub.style.opacity = '0';
        setTimeout(() => {
            sub.textContent = text;
            sub.style.transition = 'opacity 0.3s var(--ease, ease)';
            sub.style.opacity = '1';
        }, 180);
    }).catch((e) => { console.warn('[greeting]', e.message); });

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
    try {
        const full = execSync('id -F', { timeout: 500, stdio: ['pipe', 'pipe', 'ignore'] })
            .toString().trim();
        if (full) return full.split(/\s+/)[0];
    } catch (_) { /* fallback below */ }

    const raw = (typeof process !== 'undefined' && process.env && process.env.USER) || '';
    if (!raw) return 'there';
    const first = raw.split(/[._\s]/)[0];
    return first.charAt(0).toUpperCase() + first.slice(1).toLowerCase();
}

/**
 * Find the latest .emu/workspace/memory/YYYY-MM-DD.md and ask the daemon
 * provider to summarize what was worked on. Returns null on any failure.
 */
async function _fetchContextualSubtitle() {
    // 1. Find the newest daily memory file
    const memDir = path.join(EMU_ROOT, 'workspace', 'memory');
    if (!fs.existsSync(memDir)) return null;

    const files = fs.readdirSync(memDir)
        .filter(f => /^\d{4}-\d{2}-\d{2}\.md$/.test(f))
        .sort()
        .reverse();
    if (!files.length) return null;

    const latestPath = path.join(memDir, files[0]);
    const content = fs.readFileSync(latestPath, 'utf-8').trim();
    if (!content) return null;

    // 2. Load provider credentials from backend/.env
    const env = _readEnv();
    const apiKey = (env.EMU_DAEMON_API_KEY || env.OPENROUTER_API_KEY || '').trim();
    const model  = (env.EMU_DAEMON_MODEL   || 'openai/gpt-5.4').trim();
    if (!apiKey) return null;

    // 3. Prompt: one-sentence recap in second person, no dates
    const system = [
        'Write ONE ultra-short sentence (max 14 words) telling the user what',
        'they were recently working on, in second person. Start with "You".',
        'Do not mention dates, session ids, or filenames. Do not greet.',
        'Examples:',
        '  "You were researching Perplexity Computer pricing."',
        '  "You were drafting a reply to Priya about the Q3 invoices."',
    ].join(' ');

    const snippet = content.slice(0, 1500);

    // 4. Call OpenRouter (direct chat/completions)
    const resp = await fetch('https://openrouter.ai/api/v1/chat/completions', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${apiKey}`,
            'HTTP-Referer': 'https://emu.local',
            'X-Title':      'Emu',
        },
        body: JSON.stringify({
            model,
            messages: [
                { role: 'system', content: system },
                { role: 'user',   content: snippet },
            ],
            max_tokens: 60,
            temperature: 0.4,
        }),
    });

    if (!resp.ok) {
        console.warn('[greeting] openrouter returned', resp.status);
        return null;
    }

    const data = await resp.json();
    const text = data?.choices?.[0]?.message?.content?.trim();
    if (!text) return null;

    // Strip quotes the model sometimes wraps the sentence in
    return text.replace(/^["'"'`\s]+|["'"'`\s]+$/g, '');
}

/**
 * Minimal .env parser. Reads backend/.env line by line.
 * Ignores comments, handles KEY=VALUE with optional quotes.
 */
function _readEnv() {
    try {
        const envPath = path.join(__dirname, '..', '..', '..', 'backend', '.env');
        const raw = fs.readFileSync(envPath, 'utf-8');
        const out = {};
        raw.split('\n').forEach(line => {
            const trimmed = line.trim();
            if (!trimmed || trimmed.startsWith('#')) return;
            const m = trimmed.match(/^([A-Z0-9_]+)\s*=\s*(.*)$/i);
            if (!m) return;
            let val = m[2];
            // Strip surrounding quotes if any
            if ((val.startsWith('"') && val.endsWith('"')) ||
                (val.startsWith("'") && val.endsWith("'"))) {
                val = val.slice(1, -1);
            }
            out[m[1]] = val;
        });
        return out;
    } catch (_) {
        return {};
    }
}

module.exports = { Greeting };
