# Minecraft Mod Installer (Windows PowerShell)
param([string]$ServerIP="192.168.0.19", [int]$Port=8000)
$modsPath = "$env:APPDATA\.minecraft\mods"
$oldmodsPath = "$env:APPDATA\.minecraft\oldmods"
$zipPath = "$env:TEMP\mods_latest.zip"
$manifestPath = "$env:TEMP\mods_manifest.json"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   Minecraft Mod Installer" -ForegroundColor Cyan
Write-Host "   Server: $ServerIP:$Port" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

New-Item -ItemType Directory -Path $oldmodsPath -Force | Out-Null
New-Item -ItemType Directory -Path $modsPath -Force | Out-Null

# Fetch manifest and clean old mods
Write-Host "Fetching mod list from server..." -ForegroundColor Yellow
try {
    $manifest = Invoke-RestMethod -Uri "http://$ServerIP`:$Port/download/mods_manifest.json" -UseBasicParsing
    $serverMods = $manifest.mods
    if (-not $serverMods) {
        throw "Invalid manifest - no mods array"
    }
    Write-Host "Server has $($serverMods.Count) mods" -ForegroundColor Gray
    
    # Move mods not in the manifest
    $movedCount = 0
    $failedCount = 0
    Get-ChildItem -Path $modsPath -Filter "*.jar" -ErrorAction SilentlyContinue | ForEach-Object {
        if ($serverMods -notcontains $_.Name) {
            try {
                Move-Item -Path $_.FullName -Destination $oldmodsPath -Force -ErrorAction Stop
                Write-Host "  Moved: $($_.Name)" -ForegroundColor DarkGray
                $movedCount++
            } catch {
                Write-Host "  FAILED to move: $($_.Name)" -ForegroundColor Red
                $failedCount++
            }
        }
    }
    if ($movedCount -gt 0) {
        Write-Host "Moved $movedCount old mods to oldmods" -ForegroundColor Yellow
    }
    if ($failedCount -gt 0) {
        Write-Host "WARNING: $failedCount mods could not be moved" -ForegroundColor Red
    }
} catch {
    Write-Host "WARNING: Could not fetch valid manifest, moving all old mods" -ForegroundColor Yellow
    Get-ChildItem -Path $modsPath -Filter "*.jar" -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            Move-Item -Path $_.FullName -Destination $oldmodsPath -Force -ErrorAction Stop
            Write-Host "  Moved: $($_.Name)" -ForegroundColor DarkGray
        } catch {
            Write-Host "  FAILED to move: $($_.Name)" -ForegroundColor Red
        }
    }
}

Write-Host "Downloading mods..." -ForegroundColor Yellow
try {
    Invoke-WebRequest -Uri "http://$ServerIP`:$Port/download/mods_latest.zip" -OutFile $zipPath -UseBasicParsing
} catch {
    Write-Host "ERROR: Download failed. Is the server running?" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Expand-Archive -Path $zipPath -DestinationPath $modsPath -Force
Remove-Item -Path $zipPath -Force
$count = (Get-ChildItem -Path $modsPath -Filter "*.jar" | Measure-Object).Count
Write-Host ""
Write-Host "SUCCESS: $count mods installed!" -ForegroundColor Green
Write-Host "Close Minecraft and relaunch to use them." -ForegroundColor Green
Read-Host "Press Enter to exit"
