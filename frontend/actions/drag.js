// Action: Drag — click and drag from one position to another
//
// Uses cliclick on macOS, xdotool on Linux.
// cliclick dd: (drag down = press) + dm: (drag move) + du: (drag up = release)
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

const isMac = process.platform === 'darwin';

async function drag(startX, startY, endX, endY) {
    return await ipcRenderer.invoke('mouse:drag', { startX, startY, endX, endY });
}

function register(ipcMain) {
    ipcMain.handle('mouse:drag', async (_event, { startX, startY, endX, endY }) => {
        try {
            if (isMac) {
                // cliclick drag: move to start, press, interpolate to end, release
                const steps = 10;
                const cmds = [
                    `cliclick m:${startX},${startY}`,
                    `sleep 0.05`,
                    `cliclick dd:${startX},${startY}`,   // drag down (press)
                    `sleep 0.05`,
                ];

                for (let i = 1; i <= steps; i++) {
                    const t = i / steps;
                    const x = Math.round(startX + (endX - startX) * t);
                    const y = Math.round(startY + (endY - startY) * t);
                    cmds.push(`cliclick dm:${x},${y}`);   // drag move
                    cmds.push(`sleep 0.015`);
                }

                cmds.push(`sleep 0.05`);
                cmds.push(`cliclick du:${endX},${endY}`);  // drag up (release)

                await psProcess.run(cmds.join('; '));
            } else {
                const steps = 10;
                const cmds = [
                    `xdotool mousemove ${startX} ${startY}`,
                    `sleep 0.05`,
                    `xdotool mousedown 1`,
                    `sleep 0.05`,
                ];

                for (let i = 1; i <= steps; i++) {
                    const t = i / steps;
                    const x = Math.round(startX + (endX - startX) * t);
                    const y = Math.round(startY + (endY - startY) * t);
                    cmds.push(`xdotool mousemove ${x} ${y}`);
                    cmds.push(`sleep 0.015`);
                }

                cmds.push(`sleep 0.05`);
                cmds.push(`xdotool mouseup 1`);

                await psProcess.run(cmds.join('; '));
            }
            return { success: true, startX, startY, endX, endY };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { drag, register };
