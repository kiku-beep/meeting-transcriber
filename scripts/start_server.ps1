param(
    [string]$AuthToken = "monochrome2026"
)

Set-Location $PSScriptRoot\..

$TailscaleIP = "100.116.182.31"

$env:DEPLOYMENT_MODE      = "server"
$env:BACKEND_HOST         = $TailscaleIP
$env:AUTH_TOKEN            = $AuthToken
$env:KMP_DUPLICATE_LIB_OK = 'TRUE'

Write-Host "[Server] Mode: SERVER (Tailscale VPN only)"
Write-Host "[Server] Access: http://${TailscaleIP}:8000"
Write-Host "[Server] Access: http://workstation0.tail1505b.ts.net:8000"
Write-Host ""

& "$PSScriptRoot\..\\.venv\Scripts\Activate.ps1"
python -m uvicorn backend.main:app --host $TailscaleIP --port 8000
