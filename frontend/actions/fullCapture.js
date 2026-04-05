// Action: Full Capture — screenshot WITHOUT the Electron panel + cursor
// Moves the window off-screen, captures via PowerShell CopyFromScreen
// (which includes the cursor), then restores the window.
const { ipcRenderer } = require('electron');
const path = require('path');
const fs = require('fs');
const psProcess = require('../process/psProcess');

const SCREENSHOTS_DIR = path.join(__dirname, '..', '..', 'backend', 'emulation_screen_shots');

async function fullCapture() {
    return await ipcRenderer.invoke('screenshot:fullCapture');
}

/** PowerShell capture command — same as screenshot.js */
function buildCaptureCommand(filepath) {
    const psPath = filepath.replace(/\\/g, '\\\\');
    return [
        `Add-Type -AssemblyName System.Drawing`,
        `$hdc = [W.GDI]::GetDC([IntPtr]::Zero)`,
        `$w = [W.GDI]::GetDeviceCaps($hdc, 118)`,
        `$h = [W.GDI]::GetDeviceCaps($hdc, 117)`,
        `[W.GDI]::ReleaseDC([IntPtr]::Zero, $hdc)`,
        `$bmp = New-Object System.Drawing.Bitmap($w, $h)`,
        `$g = [System.Drawing.Graphics]::FromImage($bmp)`,
        `$g.CopyFromScreen(0, 0, 0, 0, (New-Object System.Drawing.Size($w, $h)))`,
        `$pos = [System.Windows.Forms.Cursor]::Position`,
        `$dpiScale = $w / [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width`,
        `$px = [int]($pos.X * $dpiScale)`,
        `$py = [int]($pos.Y * $dpiScale)`,
        `$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias`,
        `$s = 1.8 * $dpiScale`,
        `$pts = @(`,
        `  (New-Object System.Drawing.PointF($px, $py)),`,
        `  (New-Object System.Drawing.PointF($px,                  ($py + [int](20*$s)))),`,
        `  (New-Object System.Drawing.PointF(($px + [int](4*$s)),  ($py + [int](16*$s)))),`,
        `  (New-Object System.Drawing.PointF(($px + [int](8*$s)),  ($py + [int](22*$s)))),`,
        `  (New-Object System.Drawing.PointF(($px + [int](11*$s)), ($py + [int](19*$s)))),`,
        `  (New-Object System.Drawing.PointF(($px + [int](7*$s)),  ($py + [int](13*$s)))),`,
        `  (New-Object System.Drawing.PointF(($px + [int](13*$s)), ($py + [int](13*$s))))`,
        `)`,
        `$g.FillPolygon([System.Drawing.Brushes]::White, $pts)`,
        `$pen = New-Object System.Drawing.Pen([System.Drawing.Color]::Black, [Math]::Max(2, [int](1.5*$dpiScale)))`,
        `$g.DrawPolygon($pen, $pts)`,
        `$pen.Dispose()`,
        `$bmp.Save('${psPath}', [System.Drawing.Imaging.ImageFormat]::Png)`,
        `$ms = New-Object System.IO.MemoryStream`,
        `$bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)`,
        `[Convert]::ToBase64String($ms.ToArray())`,
        `$g.Dispose(); $bmp.Dispose(); $ms.Dispose()`
    ].join('; ');
}

function register(ipcMain, { screen, getMainWindow }) {
    if (!fs.existsSync(SCREENSHOTS_DIR)) fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });

    ipcMain.handle('screenshot:fullCapture', async () => {
        try {
            const win = getMainWindow();
            const { width, height } = screen.getPrimaryDisplay().size;

            // Move window off-screen so it doesn't appear in the capture.
            let savedBounds = null;
            if (win) {
                savedBounds = win.getBounds();
                win.setBounds({ ...savedBounds, x: -9999 }, false);
            }

            // Tiny delay for the OS to composite the frame without our window
            await new Promise(r => setTimeout(r, 80));

            const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
            const filename = `fullcapture_${timestamp}.png`;
            const filepath = path.join(SCREENSHOTS_DIR, filename);

            let base64;
            try {
                base64 = await psProcess.run(buildCaptureCommand(filepath));
            } finally {
                // Restore window immediately after capture — even on error
                if (win && savedBounds) {
                    win.setBounds(savedBounds, false);
                    win.setAlwaysOnTop(true, 'screen-saver');
                }
            }

            console.log(`[fullCapture] saved ${filepath}`);
            return { success: true, filename, path: filepath, width, height, base64: base64.trim() };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
}

module.exports = { fullCapture, register };
