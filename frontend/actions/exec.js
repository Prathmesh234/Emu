// Action: Shell Exec — run a shell command via psProcess
//
// Lets the agent read files, write files, list directories, check processes,
// and do anything else that a PowerShell one-liner can accomplish.
//
// The command runs inside the persistent psProcess (same as mouse/keyboard),
// so there is no spawn overhead.

const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

async function shellExec(command) {
    return await ipcRenderer.invoke('shell:exec', { command });
}

function register(ipcMain) {
    ipcMain.handle('shell:exec', async (_event, { command }) => {
        console.log(`[exec] shell:exec invoked: ${command.slice(0, 120)}`);
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
