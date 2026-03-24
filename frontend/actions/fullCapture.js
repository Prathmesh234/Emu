// Action: Full Capture — screenshot WITHOUT the Emu panel visible.
// Moves the window off-screen, captures via desktopCapturer, restores window.
// Used only when the user explicitly requests a clean capture.

const { ipcRenderer } = require('electron');
const path = require('path');
const fs = require('fs');

let desktopCapturer = null;

const SCREENSHOTS_DIR = path.join(__dirname, '..', '..', 'backend', 'emulation_screen_shots');

async function fullCapture() {
    return await ipcRenderer.invoke('screenshot:fullCapture');
}

function register(ipcMain, { screen, getMainWindow }) {
    desktopCapturer = require('electron').desktopCapturer;
    if (!fs.existsSync(SCREENSHOTS_DIR)) fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });

    ipcMain.handle('screenshot:fullCapture', async () => {
        try {
            const win = getMainWindow();
            const primaryDisplay = screen.getPrimaryDisplay();
            const { width: screenWidth, height: screenHeight } = primaryDisplay.size;
            const scaleFactor = primaryDisplay.scaleFactor || 1;

            // Move window off-screen so it doesn't appear in the capture
            let savedBounds = null;
            if (win) {
                savedBounds = win.getBounds();
                win.setBounds({ ...savedBounds, x: -9999 }, false);
            }

            // Wait for the compositor to remove the window from the frame
            await new Promise(r => setTimeout(r, 100));

            let result;
            try {
                const sources = await desktopCapturer.getSources({
                    types: ['screen'],
                    thumbnailSize: {
                        width: Math.round(screenWidth * scaleFactor),
                        height: Math.round(screenHeight * scaleFactor),
                    },
                });

                if (!sources || sources.length === 0) {
                    throw new Error('desktopCapturer returned no sources');
                }

                const nativeImage = sources[0].thumbnail;
                if (nativeImage.isEmpty()) {
                    throw new Error('desktopCapturer returned empty image');
                }

                // Resize to max 1280px width (consistent with screenshot.js)
                const size = nativeImage.getSize();
                let finalImage = nativeImage;
                if (size.width > 1280) {
                    const newHeight = Math.round((1280 / size.width) * size.height);
                    finalImage = nativeImage.resize({ width: 1280, height: newHeight, quality: 'good' });
                }
                const finalSize = finalImage.getSize();

                // JPEG at 80% quality
                const jpegBuffer = finalImage.toJPEG(80);
                const base64 = jpegBuffer.toString('base64');

                const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
                const filename = `fullcapture_${timestamp}.jpg`;
                const filepath = path.join(SCREENSHOTS_DIR, filename);
                fs.writeFileSync(filepath, jpegBuffer);

                console.log(`[fullCapture] captured ${finalSize.width}×${finalSize.height} (screen: ${screenWidth}×${screenHeight})`);
                result = {
                    success: true,
                    filename,
                    path: filepath,
                    screenWidth,
                    screenHeight,
                    base64,
                    imageWidth: finalSize.width,
                    imageHeight: finalSize.height,
                };
            } finally {
                // Restore window immediately — even on error
                if (win && savedBounds) {
                    win.setBounds(savedBounds, false);
                    win.setAlwaysOnTop(true, 'screen-saver');
                }
            }

            return result;
        } catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            console.error('[fullCapture] failed:', msg);
            return { success: false, error: msg };
        }
    });
}

module.exports = { fullCapture, register };
