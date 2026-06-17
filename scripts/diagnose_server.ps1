param(
    [string]$BindHost = "",
    [int]$Port = 8000,
    [switch]$SkipHealth
)

Set-Location $PSScriptRoot\..

$ErrorActionPreference = "Continue"
$failed = 0

function Section($Name) {
    Write-Host ""
    Write-Host "== $Name ==" -ForegroundColor Cyan
}

function Pass($Message) {
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Warn($Message) {
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Fail($Message) {
    $script:failed += 1
    Write-Host "[NG] $Message" -ForegroundColor Red
}

function Show-CommandVersion {
    param(
        [string]$Name,
        [string[]]$CommandArgs = @("--version")
    )

    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) {
        Fail "$Name not found"
        return
    }
    try {
        $version = (& $Name @CommandArgs 2>&1 | Select-Object -First 1)
        Pass "${Name}: $version"
    } catch {
        Warn "$Name found, but version check failed: $($_.Exception.Message)"
    }
}

Section "Project"
Pass "Path: $(Get-Location)"
if (Test-Path ".venv\Scripts\python.exe") {
    Pass "Python venv: .venv\Scripts\python.exe"
} else {
    Fail "Python venv missing. Run backend setup first."
}

Section "Core Tools"
Show-CommandVersion "git"
Show-CommandVersion "python"
Show-CommandVersion -Name "tailscale" -CommandArgs @("version")
Show-CommandVersion -Name "nvidia-smi" -CommandArgs @("--query-gpu=name,driver_version,memory.total", "--format=csv,noheader")

Section "Tailscale"
if (-not $BindHost) {
    $tailscale = Get-Command tailscale -ErrorAction SilentlyContinue
    if ($tailscale) {
        $BindHost = (& tailscale ip -4 2>$null | Select-Object -First 1).Trim()
    }
}
if ($BindHost) {
    Pass "BindHost: $BindHost"
} else {
    Fail "Tailscale IPv4 not detected. Try: scripts\diagnose_server.ps1 -BindHost <Tailscale IP>"
    $BindHost = "127.0.0.1"
}

Section "Python Runtime"
if (Test-Path ".venv\Scripts\python.exe") {
$pythonCheck = @'
import importlib.util
import os

checks = [
    ("torch", "torch.cuda.is_available"),
    ("ctranslate2", "ctranslate2"),
    ("faster_whisper", "faster_whisper"),
    ("pyannote.audio", "pyannote.audio"),
    ("pyaudiowpatch", "pyaudiowpatch"),
]

for module, label in checks:
    ok = importlib.util.find_spec(module) is not None
    print(f"{label}: {'OK' if ok else 'MISSING'}")

try:
    import torch
    print(f"torch.cuda.is_available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"torch.cuda.device: {torch.cuda.get_device_name(0)}")
except Exception as exc:
    print(f"torch.cuda.error: {exc}")

for key in ("HF_TOKEN", "GEMINI_API_KEY", "DEPLOYMENT_MODE", "BACKEND_HOST"):
    value = os.environ.get(key, "")
    print(f"{key}: {'SET' if value else 'unset'}")
'@
    $pythonCheck | & ".venv\Scripts\python.exe" -
}

Section "App Env File"
$envFile = Join-Path $env:APPDATA "transcriber\.env"
if (Test-Path $envFile) {
    Pass "%APPDATA%\transcriber\.env exists"
    $envText = Get-Content -LiteralPath $envFile -Raw
    if ($envText -match "HF_TOKEN\s*=\s*\S+") {
        Pass "HF_TOKEN appears configured"
    } else {
        Warn "HF_TOKEN appears empty or missing"
    }
    if ($envText -match "GEMINI_API_KEY\s*=\s*\S+") {
        Pass "GEMINI_API_KEY appears configured"
    } else {
        Warn "GEMINI_API_KEY appears empty or missing"
    }
} else {
    Warn "%APPDATA%\transcriber\.env not found"
}

Section "Port"
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Warn "Port $Port is already listening. Existing PID(s): $($listener.OwningProcess -join ', ')"
} else {
    Pass "Port $Port is free"
}

if (-not $SkipHealth) {
    Section "Health Endpoint"
    $healthUrl = "http://$BindHost`:$Port/api/health"
    $gpuHealthUrl = "http://$BindHost`:$Port/api/health/gpu"
    foreach ($url in @($healthUrl, $gpuHealthUrl)) {
        try {
            $res = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
            Pass "$url -> HTTP $($res.StatusCode)"
        } catch {
            Warn "$url -> not reachable yet ($($_.Exception.Message))"
        }
    }
}

Section "Suggested Startup"
Write-Host "scripts\start_server.ps1 -BindHost $BindHost -Port $Port"

if ($failed -gt 0) {
    Write-Host ""
    Fail "$failed required check(s) failed"
    exit 1
}

Write-Host ""
Pass "Required checks completed"
