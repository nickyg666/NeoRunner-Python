#!/bin/bash
# Minecraft Mod Installer (Linux / macOS)
SERVER_IP="192.168.0.19"
PORT="8000"
echo "============================================"
echo "   Minecraft Mod Installer"
echo "   Server: $SERVER_IP:$PORT"
echo "============================================"
[[ "$OSTYPE" == "darwin"* ]] && MC_DIR="$HOME/Library/Application Support/minecraft" || MC_DIR="$HOME/.minecraft"
MODS="$MC_DIR/mods"
OLD="$MC_DIR/oldmods"
ZIP="/tmp/mods_latest.zip"
MANIFEST="/tmp/mods_manifest.json"
mkdir -p "$OLD" "$MODS"

# Fetch manifest and clean old mods
echo "Fetching mod list from server..."
manifest_ok=false
if curl -L -s -o "$MANIFEST" "http://$SERVER_IP:$PORT/download/mods_manifest.json" 2>/dev/null; then
    # Validate manifest is valid JSON with "mods" array
    if grep -q '"mods"' "$MANIFEST" 2>/dev/null && grep -q '\[' "$MANIFEST" 2>/dev/null; then
        manifest_ok=true
    fi
fi

if $manifest_ok; then
    # Move mods not in manifest (exact filename match)
    moved=0
    for f in "$MODS"/*.jar; do
        [[ -f "$f" ]] || continue
        fname=$(basename "$f")
        if ! grep -q "\"$fname\"" "$MANIFEST" 2>/dev/null; then
            if mv "$f" "$OLD/" 2>/dev/null; then
                echo "  Moved: $fname"
                moved=$((moved + 1))
            else
                echo "  FAILED to move: $fname (check permissions)"
            fi
        fi
    done
    [[ $moved -gt 0 ]] && echo "Moved $moved old mods to oldmods/"
else
    echo "WARNING: Could not fetch valid manifest, moving all old mods"
    for f in "$MODS"/*.jar; do
        [[ -f "$f" ]] || continue
        fname=$(basename "$f")
        if mv "$f" "$OLD/" 2>/dev/null; then
            echo "  Moved: $fname"
        else
            echo "  FAILED to move: $fname"
        fi
    done
fi

echo "Downloading mods..."
curl -L -o "$ZIP" "http://$SERVER_IP:$PORT/download/mods_latest.zip" || { echo "ERROR: Download failed!"; exit 1; }
unzip -o -q "$ZIP" -d "$MODS"
rm -f "$ZIP" "$MANIFEST"
COUNT=$(ls -1 "$MODS"/*.jar 2>/dev/null | wc -l)
echo ""
echo "SUCCESS: $COUNT mods installed!"
echo "Close Minecraft and relaunch to use them."
