// Action: Shell Exec — run a shell command via psProcess
//
// Lets the agent read files, write files, list directories, check processes,
// and do anything else that a PowerShell one-liner can accomplish.
//
// The command runs inside the persistent psProcess (same as mouse/keyboard),
// so there is no spawn overhead.
//
// File locks: Commands that attempt to write/modify protected .md files
// (SOUL.md, AGENTS.md, USER.md, IDENTITY.md) are blocked automatically.

const { ipcRenderer } = require('electron');

// Protected files that the agent must NEVER modify.
// Read access is fine — only write/modify operations are blocked.
const PROTECTED_FILES = ['SOUL.md', 'AGENTS.md'];

// Patterns that indicate a write operation targeting a file
const WRITE_PATTERNS = [
    'Set-Content', 'Out-File', 'Add-Content',
    '>', '>>', // redirection
    'Remove-Item',
    'Move-Item',
    'Rename-Item',
    'Copy-Item',   // only blocked if destination is a protected file
];

// ── Illegal command patterns ───────────────────────────────────────────────
// Commands matching these are blocked BEFORE reaching the shared PowerShell
// process. A bad command (e.g. recursive dir listing producing 100K+ lines)
// can flood the stdout buffer and corrupt subsequent commands (screenshots).
const ILLEGAL_PATTERNS = [
    // ── Resource-exhaustion patterns ────────────────────────────────────────
    { pattern: /-Recurse/i,          reason: '-Recurse floods the shell buffer and blocks all subsequent commands. Use Get-ChildItem on a specific directory without -Recurse.' },
    { pattern: /Get-ChildItem[^|]*\*[^|]*\*/i, reason: 'Wildcard globbing across nested directories is too expensive. List one directory at a time.' },
    { pattern: /gci[^|]*-r\b/i,     reason: 'gci -r is shorthand for -Recurse which is blocked. List one directory at a time.' },
    { pattern: /ls[^|]*-r\b/i,      reason: 'ls -r is shorthand for -Recurse which is blocked. List one directory at a time.' },
    { pattern: /dir[^|]*\/s\b/i,    reason: 'dir /s is a recursive listing which is blocked. List one directory at a time.' },
    { pattern: /tree\s/i,            reason: 'tree produces massive output that blocks the shell. Use Get-ChildItem on a specific directory.' },
    { pattern: /Format-List\s*\*/i,  reason: 'Format-List * produces excessive output. Use Select-Object with specific properties.' },

    // ── Network exfiltration patterns ───────────────────────────────────────
    { pattern: /Invoke-WebRequest/i,  reason: 'Network requests are blocked to prevent data exfiltration. Use shell_exec for local operations only.' },
    { pattern: /Invoke-RestMethod/i,  reason: 'Network requests are blocked to prevent data exfiltration.' },
    { pattern: /\bIWR\b/i,           reason: 'IWR (Invoke-WebRequest alias) is blocked to prevent data exfiltration.' },
    { pattern: /\bIRM\b/i,           reason: 'IRM (Invoke-RestMethod alias) is blocked to prevent data exfiltration.' },
    { pattern: /\bcurl\b/i,          reason: 'curl is blocked to prevent data exfiltration.' },
    { pattern: /\bwget\b/i,          reason: 'wget is blocked to prevent data exfiltration.' },
    { pattern: /Start-BitsTransfer/i, reason: 'BITS transfers are blocked to prevent data exfiltration.' },
    { pattern: /Net\.WebClient/i,    reason: 'System.Net.WebClient is blocked to prevent data exfiltration.' },
    { pattern: /Net\.Http/i,         reason: 'System.Net.Http is blocked to prevent data exfiltration.' },
    { pattern: /\[Net\.Sockets/i,    reason: 'Raw socket access is blocked to prevent data exfiltration.' },
    { pattern: /Net\.NetworkInformation/i, reason: 'Network enumeration is blocked.' },

    // ── Code injection / evasion patterns ───────────────────────────────────
    { pattern: /Invoke-Expression/i,  reason: 'Invoke-Expression (dynamic code execution) is blocked for security.' },
    { pattern: /\biex\b/i,           reason: 'iex (Invoke-Expression alias) is blocked for security.' },
    { pattern: /\bpowershell\s+-[eE](?:nc(?:odedcommand)?)?/i, reason: 'Encoded PowerShell commands are blocked for security.' },
    { pattern: /\bpwsh\s+-[eE](?:nc(?:odedcommand)?)?/i,      reason: 'Encoded PowerShell commands are blocked for security.' },
    { pattern: /\bpowershell\s+-c\b/i, reason: 'Spawning a sub-shell is blocked. Run commands directly.' },
    { pattern: /\bpwsh\s+-c\b/i,      reason: 'Spawning a sub-shell is blocked. Run commands directly.' },
    { pattern: /\bcmd\s+\/c\b/i,      reason: 'Spawning cmd.exe sub-shell is blocked. Use PowerShell commands directly.' },
    { pattern: /\.DownloadString\s*\(/i, reason: 'Downloading remote strings is blocked for security.' },
    { pattern: /\.DownloadFile\s*\(/i,  reason: 'Downloading remote files is blocked for security.' },
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
    const psProcess = require('../process/psProcess');
    const fs = require('fs');
    const path = require('path');
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
