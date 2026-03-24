<#
.SYNOPSIS
    Package Transcriber for distribution.
.DESCRIPTION
    Assembles the final distribution folder:
      dist/Transcriber/
        Transcriber.exe       <- Tauri app
        sidecar/              <- PyInstaller backend
        .env.template         <- API key template
    User data is stored in %APPDATA%/transcriber/ (survives updates)
#>

$ProjectRoot = $PSScriptRoot
$TauriExe = Join-Path $ProjectRoot "tauri-app\src-tauri\target\release\transcriber.exe"
$SidecarDir = Join-Path $ProjectRoot "dist\transcriber-backend"
$DeployDir = Join-Path $ProjectRoot "dist\Transcriber"

Write-Host "=== Transcriber Deployment ===" -ForegroundColor Cyan

# Validate prerequisites
if (-not (Test-Path $TauriExe)) {
    Write-Host "ERROR: Tauri exe not found: $TauriExe" -ForegroundColor Red
    Write-Host "Run: cd tauri-app && npx tauri build" -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path (Join-Path $SidecarDir "transcriber-backend.exe"))) {
    Write-Host "ERROR: Sidecar not found: $SidecarDir" -ForegroundColor Red
    Write-Host "Run: .\build_sidecar.ps1" -ForegroundColor Yellow
    exit 1
}

# Clean deploy dir
if (Test-Path $DeployDir) {
    Remove-Item -Recurse -Force $DeployDir
}
New-Item -ItemType Directory -Path $DeployDir -Force | Out-Null

# Copy Tauri exe
Write-Host "[1/4] Copying Transcriber.exe..." -ForegroundColor Yellow
Copy-Item $TauriExe (Join-Path $DeployDir "Transcriber.exe")

# Copy WebView2Loader.dll if exists
$Wv2Loader = Join-Path $ProjectRoot "tauri-app\src-tauri\target\release\WebView2Loader.dll"
if (Test-Path $Wv2Loader) {
    Copy-Item $Wv2Loader $DeployDir
}

# Copy sidecar (delete first to prevent nested copy when dest already exists)
Write-Host "[2/4] Copying sidecar (~5GB)..." -ForegroundColor Yellow
$SidecarDest = Join-Path $DeployDir "sidecar"
if (Test-Path $SidecarDest) {
    Remove-Item -Recurse -Force $SidecarDest
}
Copy-Item -Recurse $SidecarDir $SidecarDest

# Data directory is now in %APPDATA%/transcriber (auto-created on first run)
# Old exe-relative data is auto-migrated on first launch

# Create .env template
Write-Host "[3/3] Creating .env template..." -ForegroundColor Yellow
@"
# Transcriber Configuration
# Rename this file to .env and fill in your API keys

# Google Gemini API key (for meeting summary generation)
# Get one at: https://aistudio.google.com/apikey
GEMINI_API_KEY=

# HuggingFace token (for pyannote speaker ID model download)
# Get one at: https://huggingface.co/settings/tokens
HF_TOKEN=

# Whisper model (default: kotoba-v2.0)
# Options: tiny, base, small, medium, large-v3, kotoba-v2.0
WHISPER_MODEL=kotoba-v2.0
"@ | Set-Content (Join-Path $DeployDir ".env.template") -Encoding UTF8

# Summary
$TotalSize = (Get-ChildItem $DeployDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host "`n=== Deployment Complete ===" -ForegroundColor Cyan
Write-Host "Location: $DeployDir" -ForegroundColor Green
Write-Host "Total size: $([math]::Round($TotalSize, 0)) MB" -ForegroundColor Green
Write-Host "`nTo distribute: ZIP the $DeployDir folder"
Write-Host "User setup: Rename .env.template to .env and add API keys"
