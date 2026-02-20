@echo off
title Minecraft Mod Installer
color 0B
echo ============================================
echo    Minecraft Mod Installer
echo    Server: 192.168.0.19:8000
echo ============================================
echo.

set "SERVER=192.168.0.19"
set "PORT=8000"
set "MC=%APPDATA%\.minecraft"
set "MODS=%MC%\mods"
set "OLD=%MC%\oldmods"
set "ZIP=%TEMP%\mods_latest.zip"
set "MANIFEST=%TEMP%\mods_manifest.json"

:: Create dirs
if not exist "%MODS%" mkdir "%MODS%"
if not exist "%OLD%" mkdir "%OLD%"

:: Download manifest first
echo Fetching mod list from server...
curl.exe -L -s -o "%MANIFEST%" "http://%SERVER%:%PORT%/download/mods_manifest.json"
if errorlevel 1 (
    echo WARNING: Could not fetch manifest, moving all old mods
    goto :moveall
)

:: Validate manifest contains JSON (basic check)
findstr /C:"mods" "%MANIFEST%" >nul 2>&1
if errorlevel 1 (
    echo WARNING: Invalid manifest, moving all old mods
    goto :moveall
)

:: Parse manifest and move mods not in the list
echo Cleaning old mods not in server pack...
set moved=0
for %%f in ("%MODS%\*.jar") do (
    findstr /C:"%%~nxf" "%MANIFEST%" >nul 2>&1
    if errorlevel 1 (
        move /Y "%%f" "%OLD%\" >nul 2>&1
        if not errorlevel 1 (
            echo   Moved: %%~nxf
            set /a moved+=1
        ) else (
            echo   FAILED to move: %%~nxf
        )
    )
)
if %moved% gtr 0 echo Moved %moved% old mods to oldmods
goto :download

:moveall
for %%f in ("%MODS%\*.jar") do (
    move /Y "%%f" "%OLD%\" >nul 2>&1
    if not errorlevel 1 (
        echo   Moved: %%~nxf
    ) else (
        echo   FAILED to move: %%~nxf
    )
)

:download
:: Download mod pack
echo.
echo Downloading mods from server...
curl.exe -L -o "%ZIP%" "http://%SERVER%:%PORT%/download/mods_latest.zip"
if errorlevel 1 (
    color 0C
    echo.
    echo ERROR: Download failed. Make sure the server is running.
    echo URL: http://%SERVER%:%PORT%/download/mods_latest.zip
    pause
    exit /b 1
)

:: Extract (tar.exe ships with Windows 10+)
echo Extracting mods...
tar.exe -xf "%ZIP%" -C "%MODS%"
if errorlevel 1 (
    echo tar failed, trying PowerShell fallback...
    powershell -Command "Expand-Archive -Path '%ZIP%' -DestinationPath '%MODS%' -Force"
)
del "%ZIP%" 2>nul
del "%MANIFEST%" 2>nul

:: Count installed mods
set count=0
for %%f in ("%MODS%\*.jar") do set /a count+=1

echo.
color 0A
echo ============================================
echo    SUCCESS: %count% mods installed!
echo    Close Minecraft and relaunch to use them.
echo ============================================
echo.
pause
