// Action: Screenshot — captures the full screen INCLUDING the Emu overlay.
//
// The model must see the Emu panel so it knows to avoid clicking behind it.
// Uses Electron's desktopCapturer API (runs in-process, inherits the app's
// Screen Recording TCC permission — no child-process permission issues).
//
// The capture is resized to max 1280px width and JPEG-compressed in-process
// so there's no shell piping of base64 data.

const { ipcRenderer } = require('electron');
const path = require('path');
const fs = require('fs');

// desktopCapturer is main-process-only in Electron 12+.
// Imported lazily inside register() which runs in main process.
let desktopCapturer = null;

const SCREENSHOTS_DIR = path.join(__dirname, '..', '..', 'backend', 'emulation_screen_shots');

// Screen dimensions for denormalizing [0,1] coordinates → absolute pixels
let _screenWidth = 1920;
let _screenHeight = 1080;

// Scale factors for coordinate translation (image coords → screen coords)
let _scaleX = 1;
let _scaleY = 1;

function getScaleFactors() {
    return { scaleX: _scaleX, scaleY: _scaleY };
}

function getScreenDimensions() {
    return { screenWidth: _screenWidth, screenHeight: _screenHeight };
}

async function captureScreenshot() {
    const result = await ipcRenderer.invoke('screenshot:capture');
    if (result.success && result.imageWidth && result.screenWidth) {
        _scaleX = result.screenWidth / result.imageWidth;
        _scaleY = result.screenHeight / result.imageHeight;
        _screenWidth = result.screenWidth;
        _screenHeight = result.screenHeight;
        console.log(`[screenshot] scale factors updated: ${_scaleX.toFixed(2)}x, ${_scaleY.toFixed(2)}y | screen: ${_screenWidth}x${_screenHeight}`);
    }
    return result;
}

function register(ipcMain, { screen }) {
    // Import desktopCapturer here — this runs in the main process
    desktopCapturer = require('electron').desktopCapturer;
    console.log(`[screenshot] register: desktopCapturer available = ${!!desktopCapturer}`);
    if (!fs.existsSync(SCREENSHOTS_DIR)) fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });

    ipcMain.handle('screenshot:capture', async () => {
        try {
            if (!desktopCapturer) {
                throw new Error('desktopCapturer not available — Electron main process API missing');
            }

            const primaryDisplay = screen.getPrimaryDisplay();
            const { width: screenWidth, height: screenHeight } = primaryDisplay.size;
            const scaleFactor = primaryDisplay.scaleFactor || 1;

            console.log(`[screenshot] capturing: screen ${screenWidth}×${screenHeight}, scale ${scaleFactor}x`);

            // Capture via desktopCapturer — grabs the full screen including all windows
            const sources = await desktopCapturer.getSources({
                types: ['screen'],
                thumbnailSize: {
                    width: Math.round(screenWidth * scaleFactor),
                    height: Math.round(screenHeight * scaleFactor),
                },
            });

            if (!sources || sources.length === 0) {
                throw new Error('desktopCapturer returned no sources — check Screen Recording permission');
            }

            // Use the primary display source
            const source = sources[0];
            const nativeImage = source.thumbnail;

            if (nativeImage.isEmpty()) {
                throw new Error('desktopCapturer returned empty image — Screen Recording permission may not be granted');
            }

            // Resize to max 1280px width to keep under Claude's size limit
            const size = nativeImage.getSize();
            let finalImage = nativeImage;
            if (size.width > 1280) {
                const newHeight = Math.round((1280 / size.width) * size.height);
                finalImage = nativeImage.resize({ width: 1280, height: newHeight, quality: 'good' });
            }

            const finalSize = finalImage.getSize();

            // JPEG at 80% quality — good balance of size and clarity
            const jpegBuffer = finalImage.toJPEG(80);
            const base64 = jpegBuffer.toString('base64');

            // Save to disk for debugging
            const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
            const filename = `screenshot_${timestamp}.jpg`;
            const filepath = path.join(SCREENSHOTS_DIR, filename);
            fs.writeFileSync(filepath, jpegBuffer);

            console.log(`[screenshot] captured ${finalSize.width}×${finalSize.height} (screen: ${screenWidth}×${screenHeight}, scale: ${scaleFactor}x) → ${Math.round(base64.length / 1024)} KB`);

            return {
                success: true,
                filename,
                path: filepath,
                screenWidth,
                screenHeight,
                imageWidth: finalSize.width,
                imageHeight: finalSize.height,
                base64,
            };
        } catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            console.error('[screenshot] capture failed:', msg, err);
            return { success: false, error: msg };
        }
    });
}

module.exports = { captureScreenshot, register, getScaleFactors, getScreenDimensions };
