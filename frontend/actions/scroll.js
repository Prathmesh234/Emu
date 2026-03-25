// Action: Scroll
// Uses Python Quartz CGEvents on macOS, xdotool on Linux.
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
                // Use a Python one-liner with Quartz (PyObjC) to generate
                // reliable scroll-wheel CGEvents on macOS.
                // Positive = scroll up, negative = scroll down.
                const scrollAmount = direction === 'up' ? amount : -amount;
                const cmd = `python3 -c "
import Quartz
e = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, ${scrollAmount})
Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)
"`;
                await psProcess.run(cmd);
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
