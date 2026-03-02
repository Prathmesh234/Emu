// Action: Full Capture — screenshot WITHOUT the Electron panel
// Moves the window off-screen, captures, then restores.
const { ipcRenderer } = require('electron');
const path = require('path');
const fs = require('fs');

const SCREENSHOTS_DIR = path.join(__dirname, '..', '..', 'backend', 'emulation_screen_shots');

async function fullCapture() {
    return await ipcRenderer.invoke('screenshot:fullCapture');
}

function register(ipcMain, { desktopCapturer, screen, BACKEND_URL, getMainWindow }) {
    // Ensure folder exists
    if (!fs.existsSync(SCREENSHOTS_DIR)) fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });

    ipcMain.handle('screenshot:fullCapture', async () => {
        try {
            const win = getMainWindow();
            const { width, height } = screen.getPrimaryDisplay().size;

            // Move window off-screen so it doesn't appear in the capture.
            // setBounds with animate=false is instant — no visible flicker.
            let savedBounds = null;
            if (win) {
                savedBounds = win.getBounds();
                win.setBounds({ ...savedBounds, x: -9999 }, false);
            }

            // Tiny delay for the OS to composite the frame without our window
            await new Promise(r => setTimeout(r, 80));

            const sources = await desktopCapturer.getSources({
                types: ['screen'],
                thumbnailSize: { width, height }
            });

            // Restore window immediately after capture
            if (win && savedBounds) {
                win.setBounds(savedBounds, false);
                win.setAlwaysOnTop(true, 'screen-saver');
            }

            if (sources.length === 0) return { success: false, error: 'No screen source found' };

            const base64 = sources[0].thumbnail.toDataURL().split(',')[1];

            // Save locally
            const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
            const filename = `fullcapture_${timestamp}.png`;
            const filepath = path.join(SCREENSHOTS_DIR, filename);
            fs.writeFileSync(filepath, Buffer.from(base64, 'base64'));
            console.log(`[fullCapture] saved ${filepath}`);

            return { success: true, filename, path: filepath, width, height };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { fullCapture, register };
