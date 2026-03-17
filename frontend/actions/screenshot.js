// Action: Screenshot (default — includes panel + cursor)
// Uses platform-native screenshot tools: screencapture on macOS, scrot on Linux.
// Cursor is included in the capture by default.
const { ipcRenderer } = require('electron');
const path = require('path');
const fs = require('fs');
const psProcess = require('../process/psProcess');

const isMac = process.platform === 'darwin';

const SCREENSHOTS_DIR = path.join(__dirname, '..', '..', 'backend', 'emulation_screen_shots');

// Scale factors for coordinate translation (image coords → screen coords)
// Updated after each screenshot capture
let _scaleX = 1;
let _scaleY = 1;

// Screen dimensions for denormalizing [0,1] coordinates → absolute pixels
let _screenWidth = 1920;
let _screenHeight = 1080;

function getScaleFactors() {
    return { scaleX: _scaleX, scaleY: _scaleY };
}

function getScreenDimensions() {
    return { screenWidth: _screenWidth, screenHeight: _screenHeight };
}

async function captureScreenshot() {
    const result = await ipcRenderer.invoke('screenshot:capture');
    // Update scale factors and screen dimensions from the captured image
    if (result.success && result.imageWidth && result.screenWidth) {
        _scaleX = result.screenWidth / result.imageWidth;
        _scaleY = result.screenHeight / result.imageHeight;
        _screenWidth = result.screenWidth;
        _screenHeight = result.screenHeight;
        console.log(`[screenshot] scale factors updated: ${_scaleX.toFixed(2)}x, ${_scaleY.toFixed(2)}y | screen: ${_screenWidth}x${_screenHeight}`);
    }
    return result;
}

/**
 * Build the shell command that captures the screen, optionally resizes,
 * saves as JPEG, and returns base64.
 *
 * macOS: uses screencapture (built-in) + sips for resize
 * Linux: uses scrot + ImageMagick convert for resize
 *
 * JPEG quality 80 + resize keeps output under Claude's 5MB limit.
 */
function buildCaptureCommand(filepath) {
    const jpgPath = filepath.replace(/\.png$/, '.jpg');

    if (isMac) {
        // macOS: screencapture captures full screen with cursor (-C flag)
        // sips converts/resizes, base64 encodes the result
        return [
            `screencapture -C -x -t jpg "${jpgPath}"`,
            // Get image dimensions
            `_w=$(sips -g pixelWidth "${jpgPath}" | tail -1 | awk '{print $2}')`,
            `_h=$(sips -g pixelHeight "${jpgPath}" | tail -1 | awk '{print $2}')`,
            // Resize to max 1280px width if needed
            `if [ "$_w" -gt 1280 ]; then sips --resampleWidth 1280 "${jpgPath}" >/dev/null 2>&1; _w=$(sips -g pixelWidth "${jpgPath}" | tail -1 | awk '{print $2}'); _h=$(sips -g pixelHeight "${jpgPath}" | tail -1 | awk '{print $2}'); fi`,
            // Output format: "width,height|base64data"
            `printf "%s,%s|" "$_w" "$_h"`,
            `base64 < "${jpgPath}" | tr -d '\\n'`,
        ].join('; ');
    } else {
        // Linux: scrot captures full screen, ImageMagick converts to jpg + resize
        return [
            `scrot -o "${filepath}"`,
            // Convert to JPEG and resize to max 1280px width
            `convert "${filepath}" -resize '1280x>' -quality 60 "${jpgPath}"`,
            // Get image dimensions
            `_dims=$(identify -format '%w,%h' "${jpgPath}")`,
            // Output format: "width,height|base64data"
            `printf "%s|" "$_dims"`,
            `base64 < "${jpgPath}" | tr -d '\\n'`,
        ].join('; ');
    }
}

function register(ipcMain, { screen }) {
    if (!fs.existsSync(SCREENSHOTS_DIR)) fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });

    ipcMain.handle('screenshot:capture', async () => {
        try {
            const { width: screenWidth, height: screenHeight } = screen.getPrimaryDisplay().size;
            const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
            const filename = `screenshot_${timestamp}.png`;
            const filepath = path.join(SCREENSHOTS_DIR, filename);

            const output = await psProcess.run(buildCaptureCommand(filepath));

            // Parse output format: "imageWidth,imageHeight|base64data"
            const pipeIdx = output.indexOf('|');
            if (pipeIdx === -1) {
                throw new Error('Invalid screenshot output format');
            }
            const dims = output.slice(0, pipeIdx).split(',');
            const imageWidth = parseInt(dims[0], 10);
            const imageHeight = parseInt(dims[1], 10);
            const base64 = output.slice(pipeIdx + 1).trim();

            console.log(`[screenshot] saved ${filepath} (image: ${imageWidth}×${imageHeight}, screen: ${screenWidth}×${screenHeight})`);
            return {
                success: true,
                filename,
                path: filepath,
                screenWidth,
                screenHeight,
                imageWidth,
                imageHeight,
                base64,
            };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { captureScreenshot, register, getScaleFactors, getScreenDimensions };
