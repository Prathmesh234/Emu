// Action: Relative Drag — press at current cursor, drag by an offset, release.
//
// macOS: uses cliclick dd:. (drag down at current pos), then interpolated
//        relative dm:+dx,+dy moves, ending in du:. (drag up at current pos).
// Linux: xdotool mousedown + mousemove_relative + mouseup.
const { ipcRenderer } = require('electron');
const psProcess = require('../process/psProcess');

const isMac = process.platform === 'darwin';

async function relativeDrag(dxPx, dyPx) {
    return await ipcRenderer.invoke('mouse:relative-drag', { dxPx, dyPx });
}

function _signed(n) {
    const v = Math.round(n);
    return v >= 0 ? `+${v}` : `${v}`;
}

function register(ipcMain) {
    ipcMain.handle('mouse:relative-drag', async (_event, { dxPx, dyPx }) => {
        try {
            if (isMac) {
                const steps = 10;
                const cmds = [
                    `cliclick dd:.`,           // press at current cursor position
                    `sleep 0.05`,
                ];
                // Interpolate: split the total offset into N relative micro-moves.
                const stepDx = dxPx / steps;
                const stepDy = dyPx / steps;
                for (let i = 0; i < steps; i++) {
                    cmds.push(`cliclick dm:${_signed(stepDx)},${_signed(stepDy)}`);
                    cmds.push(`sleep 0.015`);
                }
                cmds.push(`sleep 0.05`);
                cmds.push(`cliclick du:.`);    // release at current cursor position
                console.log(`[relative_drag] dx=${dxPx} dy=${dyPx} (${steps} interpolated steps)`);
                await psProcess.run(cmds.join('; '));
            } else {
                const steps = 10;
                const cmds = [`xdotool mousedown 1`, `sleep 0.05`];
                const stepDx = dxPx / steps;
                const stepDy = dyPx / steps;
                for (let i = 0; i < steps; i++) {
                    cmds.push(`xdotool mousemove_relative -- ${Math.round(stepDx)} ${Math.round(stepDy)}`);
                    cmds.push(`sleep 0.015`);
                }
                cmds.push(`sleep 0.05`);
                cmds.push(`xdotool mouseup 1`);
                await psProcess.run(cmds.join('; '));
            }
            return { success: true, dxPx, dyPx };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { relativeDrag, register };
