// Action: Screenshot (default — includes panel + cursor)
// Uses PowerShell CopyFromScreen + cursor compositing so the system cursor
// is visible in captures (desktopCapturer excludes it on Windows).
const { ipcRenderer } = require('electron');

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

        // Convert JPEG → WebP for smaller payload and faster inference
        try {
            const webpBase64 = await convertToWebP(result.base64);
            const savings = Math.round((1 - webpBase64.length / result.base64.length) * 100);
            console.log(`[screenshot] WebP conversion: ${Math.round(result.base64.length / 1024)}KB → ${Math.round(webpBase64.length / 1024)}KB (${savings}% smaller)`);
            result.base64 = webpBase64;
        } catch (err) {
            console.warn(`[screenshot] WebP conversion failed, using JPEG: ${err.message}`);
        }
    }
    return result;
}

/**
 * Convert a JPEG base64 string to WebP via Chromium's native canvas encoder.
 * Falls back gracefully — if canvas doesn't support WebP the caller keeps JPEG.
 */
function convertToWebP(jpegBase64, quality = 0.60) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => {
            const canvas = document.createElement('canvas');
            canvas.width = img.width;
            canvas.height = img.height;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0);
            const dataUrl = canvas.toDataURL('image/webp', quality);
            const base64 = dataUrl.split(',')[1];
            if (!base64) {
                reject(new Error('Canvas toDataURL returned empty'));
                return;
            }
            resolve(base64);
        };
        img.onerror = () => reject(new Error('Failed to load image for WebP conversion'));
        img.src = `data:image/jpeg;base64,${jpegBase64}`;
    });
}

/**
 * Build the PowerShell command that captures the primary screen at true
 * physical resolution (via GetDeviceCaps), draws a cursor-shaped arrow
 * overlay, resizes to max 768px width, saves as JPEG, and returns base64.
 *
 * JPEG quality 60 + resize to 768px. JS-side converts to WebP for
 * ~25-30% smaller payload and faster TTFT.
 */
function buildCaptureCommand() {
    return [
        `Add-Type -AssemblyName System.Drawing`,
        // Get true physical pixel dimensions via GDI (DPI-safe)
        `$hdc = [W.GDI]::GetDC([IntPtr]::Zero)`,
        `$w = [W.GDI]::GetDeviceCaps($hdc, 118)`,   // DESKTOPHORZRES
        `$h = [W.GDI]::GetDeviceCaps($hdc, 117)`,   // DESKTOPVERTRES
        `[void][W.GDI]::ReleaseDC([IntPtr]::Zero, $hdc)`,
        // Capture full physical screen
        `$bmp = New-Object System.Drawing.Bitmap($w, $h)`,
        `$g = [System.Drawing.Graphics]::FromImage($bmp)`,
        `$g.CopyFromScreen(0, 0, 0, 0, (New-Object System.Drawing.Size($w, $h)))`,
        // Convert logical cursor position → physical
        `$pos = [System.Windows.Forms.Cursor]::Position`,
        `$dpiScale = $w / [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width`,
        `$px = [int]($pos.X * $dpiScale)`,
        `$py = [int]($pos.Y * $dpiScale)`,
        // Draw a Windows-style arrow cursor (filled white with black border)
        `$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias`,
        `$s = 1.8 * $dpiScale`,
        // Define cursor polygon points - must be single statement to avoid semicolon breaking array syntax
        `$pts = @(` +
            `(New-Object System.Drawing.PointF($px, $py)),` +                                    // tip (top-left)
            `(New-Object System.Drawing.PointF($px, ($py + [int](20*$s)))),` +                   // down left edge
            `(New-Object System.Drawing.PointF(($px + [int](4*$s)), ($py + [int](16*$s)))),` +   // notch left
            `(New-Object System.Drawing.PointF(($px + [int](8*$s)), ($py + [int](22*$s)))),` +   // tail bottom-left
            `(New-Object System.Drawing.PointF(($px + [int](11*$s)), ($py + [int](19*$s)))),` +  // tail bottom-right
            `(New-Object System.Drawing.PointF(($px + [int](7*$s)), ($py + [int](13*$s)))),` +   // notch right
            `(New-Object System.Drawing.PointF(($px + [int](13*$s)), ($py + [int](13*$s))))` +   // right wing
        `)`,
        `$g.FillPolygon([System.Drawing.Brushes]::White, $pts)`,
        `$pen = New-Object System.Drawing.Pen([System.Drawing.Color]::Black, [Math]::Max(2, [int](1.5*$dpiScale)))`,
        `$g.DrawPolygon($pen, $pts)`,
        `$pen.Dispose()`,
        `$g.Dispose()`,
        // Resize to max 768px width — LLMs internally tile to ~768px anyway
        `$maxW = 768`,
        `$finalBmp = $bmp`,
        `if ($bmp.Width -gt $maxW) {` +
            ` $ratio = $maxW / $bmp.Width;` +
            ` $newH = [int]($bmp.Height * $ratio);` +
            ` $finalBmp = New-Object System.Drawing.Bitmap($maxW, $newH);` +
            ` $gr = [System.Drawing.Graphics]::FromImage($finalBmp);` +
            ` $gr.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic;` +
            ` $gr.DrawImage($bmp, 0, 0, $maxW, $newH);` +
            ` $gr.Dispose();` +
            ` $bmp.Dispose()` +
        ` }`,
        // Encode as JPEG quality 60 (smaller file, faster inference)
        `$codec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.MimeType -eq 'image/jpeg' }`,
        `$encParams = New-Object System.Drawing.Imaging.EncoderParameters(1)`,
        `$encParams.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter([System.Drawing.Imaging.Encoder]::Quality, 60L)`,
        `$ms = New-Object System.IO.MemoryStream`,
        `$finalBmp.Save($ms, $codec, $encParams)`,
        // Output format: "width,height|base64data" so JS can parse dimensions
        `Write-Output "$($finalBmp.Width),$($finalBmp.Height)|$([Convert]::ToBase64String($ms.ToArray()))"`,
        `$finalBmp.Dispose(); $ms.Dispose()`
    ].join('; ');
}

function register(ipcMain, { screen }) {
    const psProcess = require('../process/psProcess');
    ipcMain.handle('screenshot:capture', async () => {
        try {
            const { width: screenWidth, height: screenHeight } = screen.getPrimaryDisplay().size;

            const output = await psProcess.run(buildCaptureCommand());

            // Parse output format: "imageWidth,imageHeight|base64data"
            const pipeIdx = output.indexOf('|');
            if (pipeIdx === -1) {
                throw new Error('Invalid screenshot output format');
            }
            const dims = output.slice(0, pipeIdx).split(',');
            const imageWidth = parseInt(dims[0], 10);
            const imageHeight = parseInt(dims[1], 10);
            const base64 = output.slice(pipeIdx + 1).trim();

            return {
                success: true,
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
