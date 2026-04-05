// Action: Screenshot (default — includes panel + cursor)
// Uses PowerShell CopyFromScreen + cursor compositing so the system cursor
// is visible in captures (desktopCapturer excludes it on Windows).
const { ipcRenderer } = require('electron');
const path = require('path');
const fs = require('fs');
const psProcess = require('../process/psProcess');

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
 * Build the PowerShell command that captures the primary screen at true
 * physical resolution (via GetDeviceCaps), draws a cursor-shaped arrow
 * overlay, resizes to max 1920px width, saves as JPEG, and returns base64.
 *
 * JPEG quality 80 + resize keeps output under Claude's 5MB limit.
 */
function buildCaptureCommand(filepath) {
    const psPath = filepath.replace(/\.png$/, '.jpg').replace(/\\/g, '\\\\');
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
        // Resize to max 1280px width to keep well under 5MB API limit
        `$maxW = 1280`,
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
        // Save as JPEG quality 60 (smaller file, faster inference)
        `$codec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.MimeType -eq 'image/jpeg' }`,
        `$encParams = New-Object System.Drawing.Imaging.EncoderParameters(1)`,
        `$encParams.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter([System.Drawing.Imaging.Encoder]::Quality, 60L)`,
        `$finalBmp.Save('${psPath}', $codec, $encParams)`,
        `$ms = New-Object System.IO.MemoryStream`,
        `$finalBmp.Save($ms, $codec, $encParams)`,
        // Output format: "width,height|base64data" so JS can parse dimensions
        `Write-Output "$($finalBmp.Width),$($finalBmp.Height)|$([Convert]::ToBase64String($ms.ToArray()))"`,
        `$finalBmp.Dispose(); $ms.Dispose()`
    ].join('; ');
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
