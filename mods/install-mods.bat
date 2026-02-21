@echo off
title Minecraft Mod Installer
echo ============================================
echo    Minecraft Mod Installer
echo    Server: 192.168.0.19:8000
echo ============================================
set "MODS=%APPDATA%\.minecraft\mods"
set "OLD=%APPDATA%\.minecraft\oldmods"
set "ZIP=%TEMP%\mods_latest.zip"

REM Create directories
if not exist "%MODS%" mkdir "%MODS%"
if not exist "%OLD%" mkdir "%OLD%"

REM Download
echo Downloading mods...
curl.exe -L -o "%ZIP%" "http://192.168.0.19:8000/download/mods_latest.zip"
if errorlevel 1 (
    echo ERROR: Download failed
    pause
    exit /b 1
)

REM Move conflicting mods using PowerShell (load required assembly)
echo Checking for conflicting mods...
powershell -NoProfile -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; $z=[IO.Compression.ZipFile]::OpenRead('%ZIP%'); $z.Entries|?{$_.Name -match '.jar$'}|%%{ $n=$_.Name; $t='%MODS%\'+$n; if(Test-Path $t){ Write-Host '  Moving '+$n; Move-Item $t '%OLD%\' -Force } }; $z.Dispose()"

REM Extract
echo Extracting mods...
powershell -NoProfile -Command "Expand-Archive -Path '%ZIP%' -DestinationPath '%MODS%' -Force"
if errorlevel 1 (
    echo ERROR: Extraction failed
    pause
    exit /b 1
)

REM Cleanup
del "%ZIP%" 2>nul

REM Count
for /f %%a in ('dir /b "%MODS%\*.jar" 2^>nul ^| find /c /v ""') do set count=%%a
if not defined count set count=0
echo ============================================
echo SUCCESS: %count% mods installed!
echo ============================================
pause
