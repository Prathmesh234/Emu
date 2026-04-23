// Action: Horizontal Scroll
//
// macOS: cliclick has no scroll primitive, so we use Quartz CGEvents
//        (same approach as vertical scroll). For horizontal scroll we
//        request a 2-axis scroll wheel event and supply the units on
//        axis 2 (horizontal). Positive units = scroll right, negative
//        units = scroll left.
// Linux: xdotool — button 6 = scroll left, button 7 = scroll right.
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

const isMac = process.platform === 'darwin';

async function horizontalScroll(direction = 'right', amount = 5) {
    return await ipcRenderer.invoke('mouse:horizontal-scroll', { direction, amount });
}

function register(ipcMain) {
    ipcMain.handle('mouse:horizontal-scroll', async (_event, { direction = 'right', amount = 5 }) => {
        try {
            if (isMac) {
                // Positive axis-2 units = scroll right, negative = scroll left.
                const scrollAmount = direction === 'left' ? -amount : amount;
                const backendDir = require('path').resolve(__dirname, '../../backend');
                // wheelCount=2 enables the second axis (horizontal). The first
                // axis (vertical) value is 0, the second (horizontal) carries
                // the scroll amount.
                const cmd = `cd "${backendDir}" && uv run python3 -c "
import Quartz
e = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 2, 0, ${scrollAmount})
Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)
"`;
                await psProcess.run(cmd);
            } else {
                // xdotool: button 6 = scroll left, button 7 = scroll right
                const button = direction === 'left' ? 6 : 7;
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

module.exports = { horizontalScroll, register };
