// Action: Get Mouse Position — report the current cursor x,y back to the model.
//
// macOS: `cliclick p` prints "x,y" to stdout.
// Linux: xdotool getmouselocation --shell prints X=… Y=… lines.
//
// The result is returned as `output` so backend's /action/complete handler
// can inject it into the model's context (treated like shell_exec stdout).
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

const isMac = process.platform === 'darwin';

async function getMousePosition() {
    return await ipcRenderer.invoke('mouse:get-position');
}

function register(ipcMain) {
    ipcMain.handle('mouse:get-position', async () => {
        try {
            let output;
            if (isMac) {
                // cliclick p → "1234,567"
                const raw = await psProcess.run(`cliclick p`);
                const text = String(raw || '').trim();
                // Pull the first "x,y" pair to ignore any shell noise.
                const match = text.match(/(-?\d+)\s*,\s*(-?\d+)/);
                if (match) {
                    output = `Cursor at x=${match[1]}, y=${match[2]} (absolute screen pixels)`;
                } else {
                    output = `Cursor position raw output: ${text}`;
                }
            } else {
                const raw = await psProcess.run(`xdotool getmouselocation --shell`);
                const text = String(raw || '').trim();
                const xMatch = text.match(/X=(-?\d+)/);
                const yMatch = text.match(/Y=(-?\d+)/);
                if (xMatch && yMatch) {
                    output = `Cursor at x=${xMatch[1]}, y=${yMatch[1]} (absolute screen pixels)`;
                } else {
                    output = `Cursor position raw output: ${text}`;
                }
            }
            console.log(`[get_mouse_position] ${output}`);
            return { success: true, output };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { getMousePosition, register };
