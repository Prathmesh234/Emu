// Action: Scroll
// Uses cliclick on macOS (scroll via AppleScript), xdotool on Linux.
//
// direction: 'up' | 'down'
// amount:    number of "notches" to scroll (each notch = one scroll click)
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

const isMac = process.platform === 'darwin';

async function scroll(direction = 'down', amount = 3) {
    return await ipcRenderer.invoke('mouse:scroll', { direction, amount });
}

function register(ipcMain, BACKEND_URL) {
    ipcMain.handle('mouse:scroll', async (_event, { direction = 'down', amount = 3 }) => {
        try {
            if (isMac) {
                // cliclick doesn't support scroll natively.
                // Use osascript to generate scroll wheel events.
                // Positive = scroll up, negative = scroll down.
                const scrollAmount = direction === 'up' ? amount : -amount;
                const cmd = `osascript -e 'tell application "System Events" to scroll area 1 of (first process whose frontmost is true) scroll {0, ${scrollAmount}}'`;
                // Fallback: use AppleScript mouse scroll via CGEvent
                // This uses a Python one-liner with Quartz for reliable scroll events
                const pycmd = `python3 -c "
import Quartz
e = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, ${scrollAmount})
Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)
"`;
                await psProcess.run(pycmd);
            } else {
                // xdotool: button 4 = scroll up, button 5 = scroll down
                const button = direction === 'up' ? 4 : 5;
                await psProcess.run(
                    `xdotool click --repeat ${amount} --delay 50 ${button}`
                );
            }
            return { success: true, direction, amount };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { scroll, register };
