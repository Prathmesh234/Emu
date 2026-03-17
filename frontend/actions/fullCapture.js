// Action: Full Capture — screenshot WITHOUT the Electron panel + cursor
// Moves the window off-screen, captures via platform-native tools
// (screencapture on macOS, scrot on Linux), then restores the window.
const { ipcRenderer } = require('electron');
const path = require('path');
const fs = require('fs');
const psProcess = require('../process/psProcess');

const isMac = process.platform === 'darwin';

const SCREENSHOTS_DIR = path.join(__dirname, '..', '..', 'backend', 'emulation_screen_shots');

async function fullCapture() {
    return await ipcRenderer.invoke('screenshot:fullCapture');
}

/** Shell capture command — platform-native screenshot + base64 output */
function buildCaptureCommand(filepath) {
    if (isMac) {
        // macOS: screencapture -C includes cursor, -x suppresses sound
        return [
            `screencapture -C -x "${filepath}"`,
            // Get image dimensions
            `_w=$(sips -g pixelWidth "${filepath}" | tail -1 | awk '{print $2}')`,
            `_h=$(sips -g pixelHeight "${filepath}" | tail -1 | awk '{print $2}')`,
            // Output format: "width,height|base64data"
            `printf "%s,%s|" "$_w" "$_h"`,
            `base64 < "${filepath}" | tr -d '\\n'`,
        ].join('; ');
    } else {
        // Linux: scrot captures full screen
        return [
            `scrot -o "${filepath}"`,
            // Get image dimensions via ImageMagick identify
            `_dims=$(identify -format '%w,%h' "${filepath}")`,
            // Output format: "width,height|base64data"
            `printf "%s|" "$_dims"`,
            `base64 < "${filepath}" | tr -d '\\n'`,
        ].join('; ');
    }
}

function register(ipcMain, { screen, getMainWindow }) {
    if (!fs.existsSync(SCREENSHOTS_DIR)) fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });

    ipcMain.handle('screenshot:fullCapture', async () => {
        try {
            const win = getMainWindow();
            const { width, height } = screen.getPrimaryDisplay().size;

            // Move window off-screen so it doesn't appear in the capture.
            let savedBounds = null;
            if (win) {
                savedBounds = win.getBounds();
                win.setBounds({ ...savedBounds, x: -9999 }, false);
            }

            // Tiny delay for the OS to composite the frame without our window
            await new Promise(r => setTimeout(r, 80));

            const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
            const filename = `fullcapture_${timestamp}.png`;
            const filepath = path.join(SCREENSHOTS_DIR, filename);

            let output;
            try {
                output = await psProcess.run(buildCaptureCommand(filepath));
            } finally {
                // Restore window immediately after capture — even on error
                if (win && savedBounds) {
                    win.setBounds(savedBounds, false);
                    win.setAlwaysOnTop(true, 'screen-saver');
                }
            }

            // Parse output format: "width,height|base64data"
            const pipeIdx = output.indexOf('|');
            if (pipeIdx === -1) {
                throw new Error('Invalid capture output format');
            }
            const dims = output.slice(0, pipeIdx).split(',');
            const imageWidth = parseInt(dims[0], 10);
            const imageHeight = parseInt(dims[1], 10);
            const base64 = output.slice(pipeIdx + 1).trim();

            console.log(`[fullCapture] saved ${filepath}`);
            return { success: true, filename, path: filepath, width, height, base64, imageWidth, imageHeight };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { fullCapture, register };
