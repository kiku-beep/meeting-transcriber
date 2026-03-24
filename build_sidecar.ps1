<#
.SYNOPSIS
    Build the Transcriber backend sidecar using PyInstaller.
.DESCRIPTION
    1. Runs PyInstaller with the .spec file to create transcriber-backend.exe
    2. Copies the output to tauri-app/src-tauri/sidecar/
    3. With -Deploy: also deploys to dist/Transcriber/sidecar/ (kills running app first)
.PARAMETER Deploy
    Also deploy to dist/Transcriber/sidecar/ (production location).
    Automatically stops running Transcriber processes before copying.
#>
param(
    [switch]$Deploy
)

$ProjectRoot = $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$SpecFile = Join-Path $ProjectRoot "transcriber-backend.spec"
$DistDir = Join-Path $ProjectRoot "dist\transcriber-backend"
$SidecarDest = Join-Path $ProjectRoot "tauri-app\src-tauri\sidecar"
$ProdSidecar = Join-Path $ProjectRoot "dist\Transcriber\sidecar"

$steps = if ($Deploy) { 4 } else { 3 }

Write-Host "=== Transcriber Sidecar Build ===" -ForegroundColor Cyan

# Step 1: Install PyInstaller if needed
Write-Host "`n[1/$steps] Checking PyInstaller..." -ForegroundColor Yellow
$ErrorActionPreference = "SilentlyContinue"
& $VenvPython -m pip install pyinstaller --quiet 2>$null
$ErrorActionPreference = "Continue"
Write-Host "  PyInstaller ready."

# Step 2: Run PyInstaller with spec file
Write-Host "`n[2/$steps] Running PyInstaller with spec file..." -ForegroundColor Yellow

& $VenvPython -m PyInstaller --noconfirm $SpecFile

if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller failed!" -ForegroundColor Red
    exit 1
}

Write-Host "  PyInstaller build complete: $DistDir" -ForegroundColor Green

# Step 3: Copy to tauri sidecar directory (for tauri build)
Write-Host "`n[3/$steps] Copying to tauri sidecar dir..." -ForegroundColor Yellow
if (Test-Path $SidecarDest) {
    Remove-Item -Recurse -Force $SidecarDest
}
Copy-Item -Recurse $DistDir $SidecarDest

$ExePath = Join-Path $SidecarDest "transcriber-backend.exe"
if (Test-Path $ExePath) {
    $Size = (Get-ChildItem $SidecarDest -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
    Write-Host "  Sidecar ready: $ExePath" -ForegroundColor Green
    Write-Host "  Total size: $([math]::Round($Size, 0)) MB" -ForegroundColor Green
} else {
    Write-Host "  ERROR: $ExePath not found!" -ForegroundColor Red
    exit 1
}

# Step 4 (optional): Deploy to production location
if ($Deploy) {
    Write-Host "`n[4/$steps] Deploying to production..." -ForegroundColor Yellow

    # Check production dir exists
    $ProdDir = Join-Path $ProjectRoot "dist\Transcriber"
    if (-not (Test-Path $ProdDir)) {
        Write-Host "  WARNING: $ProdDir does not exist. Run deploy.ps1 first for initial setup." -ForegroundColor Yellow
        Write-Host "  Skipping production deploy." -ForegroundColor Yellow
    } else {
        # Kill running processes
        Write-Host "  Stopping Transcriber processes..." -ForegroundColor Gray
        $killed = $false
        foreach ($name in @("Transcriber", "transcriber-backend")) {
            $procs = Get-Process -Name $name -ErrorAction SilentlyContinue
            if ($procs) {
                $procs | Stop-Process -Force
                $killed = $true
                Write-Host "    Stopped: $name" -ForegroundColor Gray
            }
        }
        if ($killed) {
            Start-Sleep -Seconds 2
        }

        # Replace sidecar only (preserves .env, Transcriber.exe, etc.)
        Write-Host "  Replacing sidecar..." -ForegroundColor Gray
        if (Test-Path $ProdSidecar) {
            Remove-Item -Recurse -Force $ProdSidecar
        }
        Copy-Item -Recurse $DistDir $ProdSidecar

        $ProdExe = Join-Path $ProdSidecar "transcriber-backend.exe"
        if (Test-Path $ProdExe) {
            Write-Host "  Deployed: $ProdSidecar" -ForegroundColor Green
        } else {
            Write-Host "  ERROR: Deploy failed - exe not found" -ForegroundColor Red
            exit 1
        }

        # Restart app
        $AppExe = Join-Path $ProdDir "Transcriber.exe"
        if (Test-Path $AppExe) {
            Write-Host "  Restarting Transcriber..." -ForegroundColor Gray
            Start-Process $AppExe
            Write-Host "  App restarted." -ForegroundColor Green
        }
    }
}

Write-Host "`n=== Build Complete ===" -ForegroundColor Cyan
if (-not $Deploy) {
    Write-Host "Tip: Use -Deploy to also deploy to dist/Transcriber/sidecar/"
}
