@echo off
REM install-mods.bat - NeoRunner Client Mod Sync Script
setlocal enabledelayedexpansion

set "SERVER_HOST=localhost"
set "SERVER_PORT=8000"

if "%SERVER_HOST%"=="" set "SERVER_HOST=localhost"
if "%SERVER_PORT%"=="" set "SERVER_PORT=8000"

echo ==========================================
echo    NeoRunner Mod Sync
echo    Server: %SERVER_HOST%:%SERVER_PORT%
echo ==========================================
echo.

set "MINECRAFT=%APPDATA%\.minecraft"
set "MODS_DIR=%MINECRAFT%\mods"
set "OLD_DIR=%MINECRAFT%\oldmods"

if not exist "%MODS_DIR%" mkdir "%MODS_DIR%"
if not exist "%OLD_DIR%" mkdir "%OLD_DIR%"

echo [1/4] Fetching server manifest...
curl.exe -s "http://%SERVER_HOST%:%SERVER_PORT%/download/manifest" -o "%TEMP%\neorunner_manifest.json"
if errorlevel 1 (
    echo ERROR: Failed to fetch manifest
    pause
    exit /b 1
)

echo [2/4] Building local mods list...
set "LOCAL_COUNT=0"
for /f %%f in ('dir /b "%MODS_DIR%\*.jar" 2^>nul') do set /a LOCAL_COUNT+=1
echo    Local mods: %LOCAL_COUNT%

echo [3/4] Syncing mods (compare, move extras, download missing)...
set "DOWNLOADED=0"
set "SKIPPED=0"
set "MOVED=0"

REM Build list of server mods - count lines with "path" in JSON
set "SERVER_COUNT=0"
for /f %%a in ('findstr /C:""path"" "%TEMP%\neorunner_manifest.json"') do set /a SERVER_COUNT+=1
echo    Server mods: %SERVER_COUNT%

REM Check each local mod - move extras to oldmods
for %%f in ("%MODS_DIR%\*.jar") do (
    findstr /i "%%~nxf" "%TEMP%\neorunner_manifest.json" >nul 2>&1
    if errorlevel 1 (
        echo    [EXTRA] %%~nf.jar -^> oldmods
        move "%%f" "%OLD_DIR%\" >nul 2>&1
        set /a MOVED+=1
    ) else (
        set /a SKIPPED+=1
    )
)

set /a MISSING=%SERVER_COUNT%-%SKIPPED%
if %MISSING% LSS 0 set "MISSING=0"
echo    Missing: %MISSING%

if %MISSING% GTR 0 (
    echo    Downloading %MISSING% missing mods...
    curl.exe -sL "http://%SERVER_HOST%:%SERVER_PORT%/download/all" -o "%TEMP%\neorunner_mods.zip"
    if errorlevel 1 (
        echo    ERROR: Failed to download mods
    ) else (
        REM Extract using tar (built into Windows 10 1803+)
        tar -xf "%TEMP%\neorunner_mods.zip" -C "%MODS_DIR%" 2>nul
        if errorlevel 1 (
            echo    ERROR: Failed to extract zip
        ) else (
            set /a DOWNLOADED=%MISSING%
            echo    Downloaded %MISSING% mods
        )
        del "%TEMP%\neorunner_mods.zip" 2>nul
    )
) else (
    echo    All mods up to date!
)

echo [4/4] Cleaning up...
del "%TEMP%\neorunner_manifest.json" 2>nul

echo.
echo ==========================================
echo    Sync Complete
echo    Skipped:  %SKIPPED%
echo    Moved:    %MOVED%
echo    Downloaded: %DOWNLOADED%
echo ==========================================
pause
