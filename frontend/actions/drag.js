// Action: Drag — click and drag from one position to another
//
// Uses mouse_event to press left button at current position, move to
// the target coordinates, then release. A smooth interpolated movement
// is performed to ensure drag-sensitive UI elements register the drag.
const { ipcRenderer } = require('electron');

async function drag(startX, startY, endX, endY) {
    return await ipcRenderer.invoke('mouse:drag', { startX, startY, endX, endY });
}

function register(ipcMain) {
    const psProcess = require('../process/psProcess');
    ipcMain.handle('mouse:drag', async (_event, { startX, startY, endX, endY }) => {
        try {
            // Move to start position, press left button down, interpolate
            // to end position in steps, then release left button.
            // The interpolation is important: many apps (e.g. drawing tools,
            // file managers, sliders) require intermediate WM_MOUSEMOVE events
            // to register a drag operation.
            const steps = 10;
            const cmds = [
                // Move to start position
                `[System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point(${startX}, ${startY})`,
                `Start-Sleep -Milliseconds 50`,
                // Press left button down (MOUSEEVENTF_LEFTDOWN = 0x02)
                `[W.U32]::mouse_event(2,0,0,0,0)`,
                `Start-Sleep -Milliseconds 50`,
            ];

            // Interpolate movement from start to end
            for (let i = 1; i <= steps; i++) {
                const t = i / steps;
                const x = Math.round(startX + (endX - startX) * t);
                const y = Math.round(startY + (endY - startY) * t);
                cmds.push(`[System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point(${x}, ${y})`);
                cmds.push(`Start-Sleep -Milliseconds 15`);
            }

            // Release left button (MOUSEEVENTF_LEFTUP = 0x04)
            cmds.push(`Start-Sleep -Milliseconds 50`);
            cmds.push(`[W.U32]::mouse_event(4,0,0,0,0)`);

            await psProcess.run(cmds.join('; '));
            return { success: true, startX, startY, endX, endY };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { drag, register };
