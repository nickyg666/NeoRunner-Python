# Minecraft Mod Installer (PowerShell)
param([string]$ServerIP="192.168.0.19", [int]$Port=8000)
$ErrorActionPreference = "Stop"
$modsPath = "$env:APPDATA\.minecraft\mods"
$oldPath = "$env:APPDATA\.minecraft\oldmods"
$zipPath = "$env:TEMP\mods_latest.zip"
$url = "http://$ServerIP`:$Port/download/mods_latest.zip"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   Minecraft Mod Installer" -ForegroundColor Cyan
Write-Host "   Server: $ServerIP`:$Port" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# Create directories
try {
    New-Item -ItemType Directory -Path $modsPath -Force | Out-Null
    New-Item -ItemType Directory -Path $oldPath -Force | Out-Null
} catch {
    Write-Host "ERROR: Cannot create directories: $_" -ForegroundColor Red
    pause
    exit 1
}

# Download
Write-Host "Downloading mods..." -ForegroundColor Yellow
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
} catch {
    Write-Host "ERROR: Download failed: $_" -ForegroundColor Red
    pause
    exit 1
}

# Move conflicting mods to oldmods
Write-Host "Checking for conflicting mods..." -ForegroundColor Yellow
try {
    $zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    $jarNames = $zip.Entries | Where-Object { $_.Name -match "\.jar$" } | ForEach-Object { $_.Name }
    $zip.Dispose()
    
    foreach ($jar in $jarNames) {
        $target = Join-Path $modsPath $jar
        if (Test-Path $target) {
            Write-Host "  Moving $jar to oldmods..."
            Move-Item -Path $target -Destination $oldPath -Force
        }
    }
} catch {
    Write-Host "Warning: Could not check zip contents: $_" -ForegroundColor Yellow
}

# Extract
Write-Host "Extracting mods..." -ForegroundColor Yellow
try {
    Expand-Archive -Path $zipPath -DestinationPath $modsPath -Force
    Remove-Item $zipPath -Force
} catch {
    Write-Host "ERROR: Extraction failed: $_" -ForegroundColor Red
    pause
    exit 1
}

# Count
$count = (Get-ChildItem -Path $modsPath -Filter "*.jar" -ErrorAction SilentlyContinue | Measure-Object).Count
Write-Host "============================================" -ForegroundColor Green
Write-Host "SUCCESS: $count mods installed!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
pause
