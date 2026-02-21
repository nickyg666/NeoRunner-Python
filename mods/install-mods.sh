#!/bin/bash
MC="$HOME/.minecraft"
[[ "$OSTYPE" == "darwin"* ]] && MC="$HOME/Library/Application Support/minecraft"
MODS="$MC/mods"
OLD="$MC/oldmods"
ZIP="/tmp/mods_latest.zip"
URL="http://192.168.0.19:8000/download/mods_latest.zip"

echo "============================================"
echo "   Minecraft Mod Installer"
echo "   Server: 192.168.0.19:8000"
echo "============================================"

# Create directories
mkdir -p "$OLD" "$MODS" || { echo "ERROR: Cannot create directories"; exit 1; }

# Download
echo "Downloading mods..."
if ! curl -fL -o "$ZIP" "$URL"; then
    echo "ERROR: Download failed"
    rm -f "$ZIP"
    exit 1
fi

# Move conflicting mods
echo "Checking for conflicting mods..."
if command -v unzip &>/dev/null; then
    unzip -Z1 "$ZIP" 2>/dev/null | grep -iE '[.]jar$' | while read -r jar; do
        if [[ -f "$MODS/$jar" ]]; then
            echo "  Moving $jar to oldmods..."
            mv -f "$MODS/$jar" "$OLD/" 2>/dev/null || true
        fi
    done
fi

# Extract
echo "Extracting mods..."
if command -v unzip &>/dev/null; then
    unzip -o "$ZIP" -d "$MODS" 2>/dev/null
elif command -v python3 &>/dev/null; then
    python3 -c "import zipfile; zipfile.ZipFile('$ZIP').extractall('$MODS')"
else
    echo "ERROR: No unzip or python3 available"
    rm -f "$ZIP"
    exit 1
fi

# Cleanup
rm -f "$ZIP"

# Count
count=$(find "$MODS" -maxdepth 1 -name "*.jar" 2>/dev/null | wc -l)
echo "============================================"
echo "SUCCESS: $count mods installed!"
echo "============================================"
