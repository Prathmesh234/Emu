// Action: Scroll
// Fires scroll events via xdotool through the persistent shell process.
// Works on any scrollable surface.
//
// direction: 'up' | 'down'
// amount:    number of "notches" to scroll (each notch = one scroll click)
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

async function scroll(direction = 'down', amount = 3) {
    return await ipcRenderer.invoke('mouse:scroll', { direction, amount });
}

function register(ipcMain, BACKEND_URL) {
    ipcMain.handle('mouse:scroll', async (_event, { direction = 'down', amount = 3 }) => {
        try {
            // xdotool: button 4 = scroll up, button 5 = scroll down
            const button = direction === 'up' ? 4 : 5;
            await psProcess.run(
                `xdotool click --repeat ${amount} --delay 50 ${button}`
            );
            return { success: true, direction, amount };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { scroll, register };
