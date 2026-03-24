# Test 1: CreateNoWindow WITHOUT stdout redirect (like Tauri does with Stdio::null)
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'E:\transcriber\dist\Transcriber\sidecar\transcriber-backend.exe'
$psi.Arguments = '--port 8765 --data-dir C:\Users\faker\AppData\Roaming\transcriber --sessions-dir C:\Users\faker\AppData\Local\transcriber-sessions'
$psi.CreateNoWindow = $true
$psi.UseShellExecute = $false
# NO redirect - like Stdio::null() in Rust
$psi.RedirectStandardOutput = $false
$psi.RedirectStandardError = $false
$psi.WorkingDirectory = 'E:\transcriber\dist\Transcriber'

$proc = [System.Diagnostics.Process]::Start($psi)
Write-Host "PID: $($proc.Id)"

for ($i = 1; $i -le 12; $i++) {
    Start-Sleep 5
    $listening = netstat -ano | Select-String "8765.*LISTENING"
    $alive = -not $proc.HasExited
    $cpu = if ($alive) { $proc.TotalProcessorTime.TotalSeconds } else { "EXITED" }
    Write-Host "${i}: alive=$alive cpu=$cpu port=$listening"
    if ($listening -or -not $alive) { break }
}

if (-not $proc.HasExited) {
    $proc.Kill()
    Write-Host "Killed"
}
