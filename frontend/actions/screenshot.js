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
let nativeImageModule = null;

// Cursor overlay config
const CURSOR_SCALE = 1.2;  // adjust to make cursor bigger/smaller
const CURSOR_FILL = { r: 255, g: 255, b: 255 };    // white fill
const CURSOR_OUTLINE = { r: 255, g: 20, b: 20 };   // bright red outline

// Arrow cursor shape — polygon points relative to tip (0,0), scaled later
// Classic macOS-style arrow cursor
const CURSOR_ARROW = [
    { x: 0,  y: 0 },
    { x: 0,  y: 20 },
    { x: 5,  y: 16 },
    { x: 9,  y: 24 },
    { x: 12, y: 23 },
    { x: 8,  y: 15 },
    { x: 14, y: 15 },
];

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

/**
 * Test if point (px, py) is inside a polygon using ray-casting algorithm.
 */
function pointInPolygon(px, py, polygon) {
    let inside = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
        const xi = polygon[i].x, yi = polygon[i].y;
        const xj = polygon[j].x, yj = polygon[j].y;
        if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) {
            inside = !inside;
        }
    }
    return inside;
}

/**
 * Minimum distance from point (px, py) to a line segment (ax,ay)-(bx,by).
 */
function distToSegment(px, py, ax, ay, bx, by) {
    const dx = bx - ax, dy = by - ay;
    const len2 = dx * dx + dy * dy;
    if (len2 === 0) return Math.hypot(px - ax, py - ay);
    let t = ((px - ax) * dx + (py - ay) * dy) / len2;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

/**
 * Minimum distance from a point to the polygon border (all edges).
 */
function distToPolygonEdge(px, py, polygon) {
    let minD = Infinity;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
        const d = distToSegment(px, py, polygon[j].x, polygon[j].y, polygon[i].x, polygon[i].y);
        if (d < minD) minD = d;
    }
    return minD;
}

/**
 * Draw an arrow-shaped cursor onto a raw RGBA bitmap buffer.
 * tipX, tipY = cursor tip position in image pixels.
 */
function drawCursorOverlay(bitmap, imgW, imgH, tipX, tipY) {
    // Scale and translate the arrow polygon to image coordinates
    const poly = CURSOR_ARROW.map(p => ({
        x: tipX + p.x * CURSOR_SCALE,
        y: tipY + p.y * CURSOR_SCALE,
    }));

    // Bounding box for the scan
    const minX = Math.floor(Math.min(...poly.map(p => p.x)) - 3);
    const maxX = Math.ceil(Math.max(...poly.map(p => p.x)) + 3);
    const minY = Math.floor(Math.min(...poly.map(p => p.y)) - 3);
    const maxY = Math.ceil(Math.max(...poly.map(p => p.y)) + 3);

    const OUTLINE_WIDTH = 2;

    for (let py = Math.max(0, minY); py <= Math.min(imgH - 1, maxY); py++) {
        for (let px = Math.max(0, minX); px <= Math.min(imgW - 1, maxX); px++) {
            const offset = (py * imgW + px) * 4;
            if (pointInPolygon(px, py, poly)) {
                // Inside the arrow — white fill
                bitmap[offset]     = CURSOR_FILL.r;
                bitmap[offset + 1] = CURSOR_FILL.g;
                bitmap[offset + 2] = CURSOR_FILL.b;
                bitmap[offset + 3] = 255;
            } else if (distToPolygonEdge(px, py, poly) <= OUTLINE_WIDTH) {
                // Near the edge — red outline
                bitmap[offset]     = CURSOR_OUTLINE.r;
                bitmap[offset + 1] = CURSOR_OUTLINE.g;
                bitmap[offset + 2] = CURSOR_OUTLINE.b;
                bitmap[offset + 3] = 255;
            }
        }
    }
}

/**
 * Get cursor position via cliclick and overlay it onto the nativeImage.
 * Returns a new nativeImage with the cursor drawn on.
 */
async function overlayMouseCursor(image, screenW, screenH) {
    const psProcess = require('../process/psProcess');
    try {
        const posStr = await psProcess.run('cliclick p:.');
        const match = posStr.trim().match(/^(\d+),(\d+)$/);
        if (!match) {
            console.warn(`[screenshot] could not parse cursor position: "${posStr}"`);
            return image;
        }
        const cursorX = parseInt(match[1], 10);
        const cursorY = parseInt(match[2], 10);

        const imgSize = image.getSize();
        // Map screen coords → image coords
        const imgX = Math.round((cursorX / screenW) * imgSize.width);
        const imgY = Math.round((cursorY / screenH) * imgSize.height);

        console.log(`[screenshot] cursor at screen(${cursorX},${cursorY}) → image(${imgX},${imgY})`);

        // Get raw RGBA bitmap, draw cursor, create new image
        const bitmap = image.toBitmap();
        drawCursorOverlay(bitmap, imgSize.width, imgSize.height, imgX, imgY);

        const result = nativeImageModule.createFromBitmap(bitmap, {
            width: imgSize.width,
            height: imgSize.height,
        });
        return result;
    } catch (err) {
        console.warn(`[screenshot] cursor overlay failed, skipping: ${err.message}`);
        return image;
    }
}

function register(ipcMain, { screen }) {
    // Import desktopCapturer here — this runs in the main process
    desktopCapturer = require('electron').desktopCapturer;
    nativeImageModule = require('electron').nativeImage;
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

            // Overlay a cursor indicator so the model can see pointer position
            finalImage = await overlayMouseCursor(finalImage, screenWidth, screenHeight);

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
