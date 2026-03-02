// Action: Screenshot (default — includes panel)
const { ipcRenderer } = require('electron');
const path = require('path');
const fs = require('fs');

const SCREENSHOTS_DIR = path.join(__dirname, '..', '..', 'backend', 'emulation_screen_shots');

async function captureScreenshot() {
    return await ipcRenderer.invoke('screenshot:capture');
}

function register(ipcMain, { desktopCapturer, screen, BACKEND_URL }) {
    // Ensure folder exists
    if (!fs.existsSync(SCREENSHOTS_DIR)) fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });

    ipcMain.handle('screenshot:capture', async () => {
        try {
            const { width, height } = screen.getPrimaryDisplay().size;

            const sources = await desktopCapturer.getSources({
                types: ['screen'],
                thumbnailSize: { width, height }
            });

            if (sources.length === 0) return { success: false, error: 'No screen source found' };

            const base64 = sources[0].thumbnail.toDataURL().split(',')[1];

            const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
            const filename = `screenshot_${timestamp}.png`;
            const filepath = path.join(SCREENSHOTS_DIR, filename);
            fs.writeFileSync(filepath, Buffer.from(base64, 'base64'));
            console.log(`[screenshot] saved ${filepath}`);

            return { success: true, filename, path: filepath, width, height };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { captureScreenshot, register };
