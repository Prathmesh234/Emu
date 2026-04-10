$sessionsDir = "c:\Users\pratbhatt\OneDrive - Microsoft\Desktop\emulation-agent\.emu\sessions\"
$dirs = Get-ChildItem $sessionsDir -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 15
foreach ($d in $dirs) {
    $conv = Join-Path $d.FullName "conversation.json"
    if (Test-Path $conv) {
        $f = Get-Item $conv
        Write-Output "$($d.Name) | $($f.LastWriteTime) | $($f.Length) bytes"
    }
}
