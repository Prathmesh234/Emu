// Action: Screenshot (default — includes panel + cursor)
// Uses PowerShell CopyFromScreen + cursor compositing so the system cursor
// is visible in captures (desktopCapturer excludes it on Windows).
const { ipcRenderer } = require('electron');
const path = require('path');
const fs = require('fs');
const psProcess = require('../process/psProcess');

const SCREENSHOTS_DIR = path.join(__dirname, '..', '..', 'backend', 'emulation_screen_shots');

async function captureScreenshot() {
    return await ipcRenderer.invoke('screenshot:capture');
}

/**
 * Build the PowerShell command that captures the primary screen at true
 * physical resolution (via GetDeviceCaps), draws a cursor-shaped arrow
 * overlay, saves to `filepath`, and returns base64 via stdout.
 */
function buildCaptureCommand(filepath) {
    const psPath = filepath.replace(/\\/g, '\\\\');
    return [
        `Add-Type -AssemblyName System.Drawing`,
        // Get true physical pixel dimensions via GDI (DPI-safe)
        `$hdc = [W.GDI]::GetDC([IntPtr]::Zero)`,
        `$w = [W.GDI]::GetDeviceCaps($hdc, 118)`,   // DESKTOPHORZRES
        `$h = [W.GDI]::GetDeviceCaps($hdc, 117)`,   // DESKTOPVERTRES
        `[W.GDI]::ReleaseDC([IntPtr]::Zero, $hdc)`,
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
        `$pts = @(`,
        `  (New-Object System.Drawing.PointF($px, $py)),`,                                       // tip (top-left)
        `  (New-Object System.Drawing.PointF($px,                  ($py + [int](20*$s)))),`,     // down left edge
        `  (New-Object System.Drawing.PointF(($px + [int](4*$s)),  ($py + [int](16*$s)))),`,     // notch left
        `  (New-Object System.Drawing.PointF(($px + [int](8*$s)),  ($py + [int](22*$s)))),`,     // tail bottom-left
        `  (New-Object System.Drawing.PointF(($px + [int](11*$s)), ($py + [int](19*$s)))),`,     // tail bottom-right
        `  (New-Object System.Drawing.PointF(($px + [int](7*$s)),  ($py + [int](13*$s)))),`,     // notch right
        `  (New-Object System.Drawing.PointF(($px + [int](13*$s)), ($py + [int](13*$s))))`,      // right wing
        `)`,
        `$g.FillPolygon([System.Drawing.Brushes]::White, $pts)`,
        `$pen = New-Object System.Drawing.Pen([System.Drawing.Color]::Black, [Math]::Max(2, [int](1.5*$dpiScale)))`,
        `$g.DrawPolygon($pen, $pts)`,
        `$pen.Dispose()`,
        // Save file + stream base64
        `$bmp.Save('${psPath}', [System.Drawing.Imaging.ImageFormat]::Png)`,
        `$ms = New-Object System.IO.MemoryStream`,
        `$bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)`,
        `[Convert]::ToBase64String($ms.ToArray())`,
        `$g.Dispose(); $bmp.Dispose(); $ms.Dispose()`
    ].join('; ');
}

function register(ipcMain, { screen }) {
    if (!fs.existsSync(SCREENSHOTS_DIR)) fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });

    ipcMain.handle('screenshot:capture', async () => {
        try {
            const { width, height } = screen.getPrimaryDisplay().size;
            const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
            const filename = `screenshot_${timestamp}.png`;
            const filepath = path.join(SCREENSHOTS_DIR, filename);

            const base64 = await psProcess.run(buildCaptureCommand(filepath));

            console.log(`[screenshot] saved ${filepath}`);
            return { success: true, filename, path: filepath, width, height, base64: base64.trim() };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { captureScreenshot, register };
