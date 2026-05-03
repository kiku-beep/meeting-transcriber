param(
    [string]$BindHost = "",
    [int]$Port = 8000,
    [string]$AuthToken = ""
)

Set-Location $PSScriptRoot\..

if (-not $BindHost) {
    $tailscale = Get-Command tailscale -ErrorAction SilentlyContinue
    if ($tailscale) {
        $BindHost = (& tailscale ip -4 2>$null | Select-Object -First 1).Trim()
    }
}

if (-not $BindHost) {
    $BindHost = "0.0.0.0"
    Write-Warning "Tailscale IP auto-detection failed. Binding to 0.0.0.0."
}

$env:DEPLOYMENT_MODE      = "server"
$env:BACKEND_HOST         = $BindHost
$env:KMP_DUPLICATE_LIB_OK = 'TRUE'

if ($AuthToken) {
    $env:AUTH_TOKEN = $AuthToken
} else {
    Remove-Item Env:\AUTH_TOKEN -ErrorAction SilentlyContinue
}

Write-Host "[Server] Mode: SERVER (Tailscale VPN only)"
Write-Host "[Server] Bind: $BindHost`:$Port"
Write-Host "[Server] Access: http://$BindHost`:$Port"
Write-Host ""

& "$PSScriptRoot\..\\.venv\Scripts\Activate.ps1"
python -m uvicorn backend.main:app --host $BindHost --port $Port
