// Action: Full Capture — screenshot WITHOUT the Emu panel visible.
// Moves the window off-screen, captures via desktopCapturer, restores window.
// Used only when the user explicitly requests a clean capture.

const { ipcRenderer } = require('electron');

let desktopCapturer = null;

async function fullCapture() {
    return await ipcRenderer.invoke('screenshot:fullCapture');
}

function register(ipcMain, { screen, getMainWindow }) {
    desktopCapturer = require('electron').desktopCapturer;

    ipcMain.handle('screenshot:fullCapture', async () => {
        try {
            const win = getMainWindow();
            const { getActiveDisplay, getLockedDisplay } = require('../display/activeDisplay');

            // Resolve active display BEFORE moving window off-screen so
            // getDisplayMatching still returns the right result.
            const activeDisplay = getLockedDisplay() || getActiveDisplay(screen, win);
            const { width: screenWidth, height: screenHeight } = activeDisplay.size;
            const scaleFactor = activeDisplay.scaleFactor || 1;
            const targetId = String(activeDisplay.id);

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

                // Match source to active display by display_id; fall back to first source
                const nativeImage = (sources.find(s => String(s.display_id) === targetId) || sources[0]).thumbnail;
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

                console.log(`[fullCapture] captured ${finalSize.width}×${finalSize.height} (screen: ${screenWidth}×${screenHeight})`);
                result = {
                    success: true,
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
