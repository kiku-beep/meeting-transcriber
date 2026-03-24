$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'C:\Users\faker\AppData\Local\Transcriber\sidecar\transcriber-backend.exe'
$psi.Arguments = '--port 8765 --data-dir C:\Users\faker\AppData\Roaming\transcriber --sessions-dir C:\Users\faker\AppData\Local\transcriber-sessions'
$psi.CreateNoWindow = $true
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$proc = [System.Diagnostics.Process]::Start($psi)
Write-Host "PID: $($proc.Id)"
Start-Sleep 25

# Check port
$listening = netstat -ano | Select-String '8765'
Write-Host "Port 8765: $listening"

# Check if alive
if (-not $proc.HasExited) {
    Write-Host "Process still running, CPU=$($proc.TotalProcessorTime)"
    $proc.Kill()
    Write-Host "Killed"
    $stdout = $proc.StandardOutput.ReadToEnd()
    $stderr = $proc.StandardError.ReadToEnd()
    if ($stderr.Length -gt 0) {
        Write-Host "=== STDERR (last 2000 chars) ==="
        Write-Host $stderr.Substring([math]::Max(0, $stderr.Length - 2000))
    }
    if ($stdout.Length -gt 0) {
        Write-Host "=== STDOUT (last 2000 chars) ==="
        Write-Host $stdout.Substring([math]::Max(0, $stdout.Length - 2000))
    }
} else {
    Write-Host "Process exited with code: $($proc.ExitCode)"
    Write-Host "=== STDERR ==="
    Write-Host $proc.StandardError.ReadToEnd()
}
