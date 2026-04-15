// Action: Shell Exec — run a shell command via psProcess
//
// Lets the agent read files, write files, list directories, check processes,
// and do anything else that a bash one-liner can accomplish.
//
// The command runs inside the persistent shell process (same as mouse/keyboard),
// so there is no spawn overhead.
//
// File locks: Commands that attempt to write/modify protected .md files
// (SOUL.md, AGENTS.md, USER.md, IDENTITY.md) are blocked automatically.

const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');
const fs = require('fs');
const path = require('path');

// Protected files that the agent must NEVER modify.
// Read access is fine — only write/modify operations are blocked.
const PROTECTED_FILES = ['SOUL.md', 'AGENTS.md', 'USER.md', 'IDENTITY.md'];

// Patterns that indicate a write operation targeting a file
const WRITE_PATTERNS = [
    'tee', 'tee -a',
    '>', '>>', // redirection
    'rm ', 'rm -',
    'mv ',
    'cp ',
    'sed -i',
    'chmod',
    'chown',
];

// ── Illegal command patterns ───────────────────────────────────────────────
// Commands matching these are blocked BEFORE reaching the shared shell
// process. A bad command (e.g. recursive dir listing producing 100K+ lines)
// can flood the stdout buffer and corrupt subsequent commands (screenshots).
const ILLEGAL_PATTERNS = [
    { pattern: /find\s+\/\s/i,          reason: 'find from root floods the shell buffer and blocks all subsequent commands. Use find on a specific directory.' },
    { pattern: /ls\s+-[^\s]*R/i,        reason: 'ls -R is a recursive listing which is blocked. List one directory at a time.' },
    { pattern: /find\s.*-name\s.*\*.*\*/, reason: 'Wildcard globbing across nested directories is too expensive. List one directory at a time.' },
    { pattern: /tree\s/i,               reason: 'tree produces massive output that blocks the shell. Use ls on a specific directory.' },
    { pattern: /du\s+-[^\s]*a.*\//i,    reason: 'du -a on large directories produces excessive output. Use du on a specific directory without -a.' },
];

/**
 * Check if a command matches an illegal pattern.
 * Returns { blocked: true, reason } or { blocked: false }.
 */
function checkIllegalCommand(command) {
    for (const { pattern, reason } of ILLEGAL_PATTERNS) {
        if (pattern.test(command)) {
            return { blocked: true, reason };
        }
    }
    return { blocked: false };
}

/**
 * Check if a command attempts to modify a protected .md file.
 * Returns the name of the protected file if blocked, null otherwise.
 */
function checkFileLock(command) {
    const cmdUpper = command.toUpperCase();

    // Only check write-like commands
    const isWriteCmd = WRITE_PATTERNS.some(p => cmdUpper.includes(p.toUpperCase()));
    if (!isWriteCmd) return null;

    // Check if any protected file name appears in the command
    for (const file of PROTECTED_FILES) {
        if (cmdUpper.includes(file.toUpperCase())) {
            return file;
        }
    }

    return null;
}

async function shellExec(command) {
    return await ipcRenderer.invoke('shell:exec', { command });
}

function register(ipcMain) {
    ipcMain.handle('shell:exec', async (_event, { command }) => {
        console.log(`[exec] shell:exec invoked: ${command.slice(0, 120)}`);

        // Illegal command screening — catch dangerous patterns before they hit the shell
        const illegal = checkIllegalCommand(command);
        if (illegal.blocked) {
            const msg = `ILLEGAL COMMAND BLOCKED: ${illegal.reason}`;
            console.warn(`[exec] ${msg}`);
            return { success: false, error: msg };
        }

        // File lock check — block writes to protected .md files
        const lockedFile = checkFileLock(command);
        if (lockedFile) {
            const msg = `BLOCKED: ${lockedFile} is a protected file and cannot be modified by the agent.`;
            console.warn(`[exec] ${msg}`);
            return { success: false, error: msg };
        }

        try {
            const output = await psProcess.run(command);
            console.log(`[exec] shell:exec OK (${output.length} chars)`);
            return { success: true, output };
        } catch (err) {
            console.error(`[exec] shell:exec FAILED:`, err.message);
            return { success: false, error: err.message };
        }
    });

    ipcMain.handle('memory:read', async (_event, { path: filePath }) => {
        console.log(`[memory:read] reading: ${filePath}`);
        try {
            // Resolve relative to cwd (project root)
            const resolved = path.resolve(process.cwd(), filePath);
            // Security: only allow reading from .emu/ directory
            const emuDir = path.resolve(process.cwd(), '.emu');
            if (!resolved.startsWith(emuDir)) {
                const msg = 'BLOCKED: memory_read only allows reading files under .emu/';
                console.warn(`[memory:read] ${msg}`);
                return { success: false, error: msg };
            }
            const content = fs.readFileSync(resolved, 'utf8');
            console.log(`[memory:read] OK (${content.length} chars)`);
            return { success: true, output: content };
        } catch (err) {
            console.error(`[memory:read] FAILED:`, err.message);
            return { success: false, error: err.message };
        }
    });
}

module.exports = { shellExec, register };
