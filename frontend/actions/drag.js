// Action: Drag — click and drag from one position to another
//
// Uses xdotool to move to start, press left button, interpolate movement
// to the target coordinates, then release. Smooth interpolated movement
// ensures drag-sensitive UI elements register the drag.
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

async function drag(startX, startY, endX, endY) {
    return await ipcRenderer.invoke('mouse:drag', { startX, startY, endX, endY });
}

function register(ipcMain) {
    ipcMain.handle('mouse:drag', async (_event, { startX, startY, endX, endY }) => {
        try {
            // Move to start position, press left button down, interpolate
            // to end position in steps, then release left button.
            // The interpolation is important: many apps (e.g. drawing tools,
            // file managers, sliders) require intermediate mouse move events
            // to register a drag operation.
            const steps = 10;
            const cmds = [
                // Move to start position
                `xdotool mousemove ${startX} ${startY}`,
                `sleep 0.05`,
                // Press left button down
                `xdotool mousedown 1`,
                `sleep 0.05`,
            ];

            // Interpolate movement from start to end
            for (let i = 1; i <= steps; i++) {
                const t = i / steps;
                const x = Math.round(startX + (endX - startX) * t);
                const y = Math.round(startY + (endY - startY) * t);
                cmds.push(`xdotool mousemove ${x} ${y}`);
                cmds.push(`sleep 0.015`);
            }

            // Release left button
            cmds.push(`sleep 0.05`);
            cmds.push(`xdotool mouseup 1`);

            await psProcess.run(cmds.join('; '));
            return { success: true, startX, startY, endX, endY };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { drag, register };
