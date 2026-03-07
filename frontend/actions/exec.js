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
const psProcess = require('../process/psProcess');

// Protected files that the agent must NEVER modify.
// Read access is fine — only write/modify operations are blocked.
const PROTECTED_FILES = ['SOUL.md', 'AGENTS.md', 'USER.md', 'IDENTITY.md'];

// Patterns that indicate a write operation targeting a file
const WRITE_PATTERNS = [
    'Set-Content', 'Out-File', 'Add-Content',
    'sc ', // alias for Set-Content
    '>', '>>', // redirection
    'Remove-Item', 'rm ', 'del ',
    'Move-Item', 'mv ',
    'Rename-Item', 'ren ',
    'Copy-Item',   // only blocked if destination is a protected file
];

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
}

module.exports = { shellExec, register };
