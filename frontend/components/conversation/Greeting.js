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
        if (!text) {
            console.warn('[greeting] no contextual subtitle — keeping fallback');
            return;
        }
        if (!sub.isConnected) {
            console.warn('[greeting] subtitle element detached before update');
            return;
        }
        console.log('[greeting] ✓ contextual subtitle:', JSON.stringify(text));
        sub.style.opacity = '0';
        setTimeout(() => {
            sub.textContent = text;
            sub.style.transition = 'opacity 0.3s var(--ease, ease)';
            sub.style.opacity = '1';
        }, 180);
    }).catch((e) => { console.warn('[greeting] fetch threw:', e.message); });

    return { element: wrap };
}

// ── Private helpers ───────────────────────────────────────────────────────

function _timeGreeting() {
    const h = new Date().getHours();
    if (h >= 6  && h < 12) return 'Good morning';
    if (h >= 12 && h < 16) return 'Good afternoon';
    if (h >= 16 && h < 20) return 'Good evening';
    return 'Late night session ☕';
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
    console.log('[greeting] fetching contextual subtitle…');

    // 1. Find the newest daily memory file
    const memDir = path.join(EMU_ROOT, 'workspace', 'memory');
    console.log('[greeting] memory dir:', memDir);
    if (!fs.existsSync(memDir)) {
        console.warn('[greeting] ✗ memory dir does not exist');
        return null;
    }

    const files = fs.readdirSync(memDir)
        .filter(f => /^\d{4}-\d{2}-\d{2}\.md$/.test(f))
        .sort()
        .reverse();
    console.log('[greeting] daily log files found:', files);
    if (!files.length) {
        console.warn('[greeting] ✗ no YYYY-MM-DD.md files in memory dir');
        return null;
    }

    const latestPath = path.join(memDir, files[0]);
    const content = fs.readFileSync(latestPath, 'utf-8').trim();
    console.log('[greeting] using', files[0], '— chars:', content.length);
    if (!content) {
        console.warn('[greeting] ✗ latest memory file is empty');
        return null;
    }

    // 2. Load provider credentials from backend/.env
    const env = _readEnv();
    const apiKey = (env.EMU_DAEMON_API_KEY || env.OPENROUTER_API_KEY || '').trim();
    const model  = (env.EMU_DAEMON_MODEL   || 'openai/gpt-5.4').trim();
    console.log('[greeting] model:', model, '| key:', apiKey ? apiKey.slice(0, 10) + '…' : '(missing)');
    if (!apiKey) {
        console.warn('[greeting] ✗ no API key (EMU_DAEMON_API_KEY / OPENROUTER_API_KEY)');
        return null;
    }

    // 3. Prompt: one quirky, clever nudge that teases the user back into the work
    const system = [
        'You write ONE short, witty line (max 18 words) that teases the user',
        'back into what they were recently working on. Voice: warm, clever,',
        'a little cheeky — like a sharp friend poking fun, not a butler. Use',
        'second person. No greetings ("hey", "hi"), no dates, no session ids,',
        'no filenames, no emoji, no preamble, no quotes. Output ONLY the line.',
        '',
        'Examples (match this vibe, do not copy):',
        '  "That SemiAnalysis deck isn\'t gonna build itself… or is it?"',
        '  "Priya\'s Q3 reply is still staring at you, y\'know."',
        '  "Perplexity pricing rabbit hole — shall we go deeper?"',
        '  "The scrollbar hunt continues. Ready for round two?"',
    ].join('\n');

    const snippet = content.slice(0, 1500);

    // 4. Call OpenRouter (direct chat/completions). max_tokens is generous
    //    to accommodate reasoning models (nemotron, o-series, etc.) that
    //    consume tokens on internal reasoning before emitting content.
    const t0 = Date.now();
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
            max_tokens: 400,
            temperature: 0.85,
        }),
    });
    const elapsed = Date.now() - t0;
    console.log('[greeting] openrouter status:', resp.status, `(${elapsed}ms)`);

    if (!resp.ok) {
        const body = await resp.text().catch(() => '');
        console.warn('[greeting] ✗ openrouter', resp.status, body.slice(0, 300));
        return null;
    }

    const data = await resp.json();
    const msg  = data?.choices?.[0]?.message;
    console.log('[greeting] raw message keys:', msg ? Object.keys(msg) : '(none)',
        '| finish_reason:', data?.choices?.[0]?.finish_reason);
    // Reasoning models may return content=null with the visible text buried
    // in `reasoning`. Fall back to that, and also handle array-shaped content.
    let text = msg?.content;
    if (Array.isArray(text)) {
        text = text.map(p => p?.text || '').join(' ');
    }
    if (!text || !String(text).trim()) {
        console.log('[greeting] content empty — falling back to reasoning field');
        text = msg?.reasoning || '';
    }
    text = String(text || '').trim();
    if (!text) {
        console.warn('[greeting] ✗ both content and reasoning are empty');
        return null;
    }

    // Extract the actual line. Reasoning models (nemotron, etc.) often dump
    // their internal monologue with tiny quoted word-fragments scattered
    // throughout ("a", "is", etc.), so picking "the last quoted string"
    // grabs garbage. Strategy: find complete-looking sentences (start with
    // capital, end with . ! or ?, at least 25 chars) and take the last one.
    // Prefer quoted sentences; fall back to unquoted.
    function _scoreSentence(s) {
        if (!s) return 0;
        const len = s.length;
        if (len < 25 || len > 180) return 0;
        if (!/^[A-Z"'`“‘]/.test(s)) return 0;           // starts capital-ish
        if (!/[.!?"'”’`]$/.test(s)) return 0;           // ends terminal-ish
        if (!/\s/.test(s)) return 0;                    // has at least one space (multi-word)
        return len;
    }

    // 1. Look inside quoted spans first (model often wraps its final answer)
    const quoteRe = /["'`“”‘’]([^"'`“”‘’\n]{20,200})["'`“”‘’]/g;
    const quotedCandidates = [...text.matchAll(quoteRe)]
        .map(m => m[1].trim())
        .filter(s => _scoreSentence(s) > 0);

    // 2. Look at non-meta lines as candidates
    const metaRe = /^(count|length|words?|note|here|let me|let's|thinking|so\b|ok\b|okay\b|actually\b|maybe:?\s*$|final:|answer:)/i;
    const lineCandidates = text
        .split(/\n+/)
        .map(l => l.trim())
        .filter(Boolean)
        .filter(l => !metaRe.test(l) && !/^\d+\s*$/.test(l))
        .filter(s => _scoreSentence(s) > 0);

    // 3. Look at ALL complete sentences across the whole blob (last resort)
    const allSentences = (text.match(/[A-Z"'`“‘][^.!?\n]{20,180}[.!?"'”’`]/g) || [])
        .map(s => s.trim())
        .filter(s => _scoreSentence(s) > 0);

    const pools = [quotedCandidates, lineCandidates, allSentences];
    let picked = null;
    for (const pool of pools) {
        if (pool.length) { picked = pool[pool.length - 1]; break; }
    }
    if (!picked) {
        console.warn('[greeting] ✗ no complete sentence found in output');
        return null;
    }
    text = picked;

    // Strip quotes / backticks / stray markdown the model sometimes adds
    const final = text.replace(/^["'`*_\s“”‘’]+|["'`*_\s“”‘’]+$/g, '');
    console.log('[greeting] ✓ final subtitle:', JSON.stringify(final));
    return final;
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
