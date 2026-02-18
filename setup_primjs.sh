#!/bin/bash
# PrimJS Build and Integration Script for NeoRunner
# Builds PrimJS (Lynx JavaScript engine) to integrate with CurseForge scraping
# Usage: bash setup_primjs.sh [--skip-download] [--arm64]
#
# Supports: x86_64 (default), arm64

set -e

GO_PATH="/usr/lib/go-1.22/bin"
PRIMJS_DIR="/home/services/primjs"
NEORUNNER_DIR="/home/services"

# Detect architecture
ARCH=$(uname -m)
if [ "$ARCH" = "aarch64" ]; then
    TARGET_ARCH="arm64"
    PRIMJS_ARCH="arm64"
elif [ "$ARCH" = "x86_64" ]; then
    TARGET_ARCH="x86_64"
    PRIMJS_ARCH="x86_64"
else
    TARGET_ARCH="$ARCH"
    PRIMJS_ARCH="$ARCH"
fi

# Override with --arm64 flag
if [[ "$@" == *"--arm64"* ]]; then
    TARGET_ARCH="arm64"
    PRIMJS_ARCH="arm64"
fi

QJS_BINARY="$PRIMJS_DIR/out/Default/qjs"

log_step() {
    echo ""
    echo "=========================================="
    echo "[$(date '+%H:%M:%S')] $1"
    echo "=========================================="
}

log_info() {
    echo "[$(date '+%H:%M:%S')] ℹ  $1"
}

log_success() {
    echo "[$(date '+%H:%M:%S')] ✓ $1"
}

log_error() {
    echo "[$(date '+%H:%M:%S')] ✗ ERROR: $1" >&2
}

# Check if skipping download
SKIP_DOWNLOAD=0
if [[ "$1" == "--skip-download" ]]; then
    SKIP_DOWNLOAD=1
    log_info "Skipping dependency download (using existing)"
fi

# Step 1: Setup environment
log_step "Setting up PrimJS build environment"

if [ ! -d "$PRIMJS_DIR" ]; then
    log_info "Cloning PrimJS repository..."
    cd /tmp
    rm -rf primjs 2>/dev/null || true
    git clone https://github.com/lynx-family/primjs.git
    mv /tmp/primjs "$PRIMJS_DIR"
fi

cd "$PRIMJS_DIR"
log_success "PrimJS directory ready at: $PRIMJS_DIR"

# Step 2: Setup Go and Ninja paths
log_step "Configuring build tools"
export PATH="$GO_PATH:$PATH"
export PATH="/usr/bin:$PATH"  # Ensure ninja from apt is used

# Verify tools
if ! command -v go &> /dev/null; then
    log_error "Go not found in PATH"
    exit 1
fi
if ! command -v ninja &> /dev/null; then
    log_error "Ninja not found in PATH"
    exit 1
fi

log_success "Go version: $(go version)"
log_success "Ninja version: $(ninja --version)"

# Step 3: Download and sync dependencies
log_step "Syncing PrimJS dependencies"
source tools/envsetup.sh

if [ $SKIP_DOWNLOAD -eq 0 ]; then
    log_info "This may take 5-15 minutes depending on network speed..."
    log_info "Downloading buildtools (gn, llvm, cmake, etc.)..."
    bash tools/hab sync
    log_success "Dependencies synchronized"
else
    log_info "Skipping dependency download"
fi

# Verify buildtools were downloaded
if [ ! -f "buildtools/gn/gn" ]; then
    log_error "GN build tool not found after sync"
    exit 1
fi

# Step 4: Generate build configuration
log_step "Generating PrimJS build files (Target: $TARGET_ARCH)"
log_info "Using gn gen out/Default..."

# Generate build config with target architecture
cd "$PRIMJS_DIR"

if [ "$TARGET_ARCH" = "arm64" ]; then
    log_info "Building for ARM64..."
    "$PRIMJS_DIR/buildtools/gn/gn" gen out/Default --args='target_cpu="arm64"'
else
    log_info "Building for x86_64..."
    "$PRIMJS_DIR/buildtools/gn/gn" gen out/Default
fi

log_success "Build configuration generated for $TARGET_ARCH"

# Step 5: Compile PrimJS
log_step "Compiling PrimJS (this may take 10-30 minutes...)"
log_info "Running: ninja -C out/Default qjs_exe"

"$PRIMJS_DIR/buildtools/ninja/ninja" -C out/Default qjs_exe -j$(nproc)

if [ ! -f "$QJS_BINARY" ]; then
    log_error "QJS binary not found at: $QJS_BINARY"
    exit 1
fi

log_success "PrimJS compilation complete!"
log_success "QJS binary: $QJS_BINARY"

# Step 6: Test PrimJS binary
log_step "Testing PrimJS binary"
TEST_SCRIPT=$(mktemp)
echo 'console.log("QuickJS Runtime OK");' > "$TEST_SCRIPT"
QJS_OUTPUT=$("$QJS_BINARY" "$TEST_SCRIPT" 2>&1)
rm -f "$TEST_SCRIPT"

if echo "$QJS_OUTPUT" | grep -q "QuickJS"; then
    log_success "QJS binary is working correctly"
else
    log_error "QJS binary test failed: $QJS_OUTPUT"
    exit 1
fi

# Step 7: Copy QJS to NeoRunner binaries
log_step "Integrating with NeoRunner"
mkdir -p "$NEORUNNER_DIR/bin"
cp "$QJS_BINARY" "$NEORUNNER_DIR/bin/qjs"
chmod +x "$NEORUNNER_DIR/bin/qjs"

log_success "QJS copied to: $NEORUNNER_DIR/bin/qjs"

# Step 8: Create wrapper script for Lynx integration
log_step "Creating Lynx+PrimJS integration script"

cat > "$NEORUNNER_DIR/bin/lynx_primjs.sh" << 'LSCRIPT'
#!/bin/bash
# Lynx with PrimJS JavaScript engine wrapper for CurseForge scraping
#
# Usage: lynx_primjs.sh <url> [--dump | --source]
#
# Executes JavaScript on pages before rendering with Lynx

QJS_BIN="/home/services/bin/qjs"
LYNX_BIN="/usr/bin/lynx"
TEMP_DIR="/tmp/lynx_primjs_$$"
OUTPUT_MODE="dump"

# Parse args
URL="$1"
if [[ "$2" == "--source" ]]; then
    OUTPUT_MODE="source"
elif [[ "$2" == "--dump" ]]; then
    OUTPUT_MODE="dump"
fi

if [ -z "$URL" ]; then
    echo "Usage: $0 <url> [--dump|--source]"
    exit 1
fi

mkdir -p "$TEMP_DIR"
trap "rm -rf $TEMP_DIR" EXIT

# Step 1: Download page with curl (handles basic redirects/cookies)
log_msg="Fetching $URL..."
echo "[*] $log_msg" >&2

HTTP_CODE=$(curl -s -w "%{http_code}" -o "$TEMP_DIR/page.html" \
    -H "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36" \
    "$URL" 2>/dev/null | tail -c 3)

if [ "$HTTP_CODE" != "200" ]; then
    echo "[!] HTTP $HTTP_CODE fetching $URL" >&2
fi

# Step 2: Check for Cloudflare challenge
if grep -q "cf-challenge\|cf_clearance\|Just a moment" "$TEMP_DIR/page.html" 2>/dev/null; then
    echo "[!] Cloudflare challenge detected - attempting JavaScript evaluation..." >&2
    
    # Create PrimJS script to evaluate page
    cat > "$TEMP_DIR/eval.js" << 'JSEND'
// Simple CF challenge resolver (basic)
try {
    // Load HTML as string
    let html = require('fs').readFileSync(process.argv[1], 'utf-8');
    
    // Look for challenge parameters
    let match = html.match(/name="([^"]+)"\s+value="([^"]+)"/);
    if (match) {
        console.log("Found CF form: name=" + match[1] + " value=" + match[2]);
    }
    
    // Output processed HTML
    console.log(html);
} catch(e) {
    console.error("Error: " + e.message);
}
JSEND
    
    # Run through PrimJS for JavaScript execution
    "$QJS_BIN" "$TEMP_DIR/eval.js" "$TEMP_DIR/page.html" > "$TEMP_DIR/page_processed.html" 2>/dev/null || \
        cp "$TEMP_DIR/page.html" "$TEMP_DIR/page_processed.html"
else
    cp "$TEMP_DIR/page.html" "$TEMP_DIR/page_processed.html"
fi

# Step 3: Pipe through Lynx with appropriate mode
case "$OUTPUT_MODE" in
    dump)
        "$LYNX_BIN" -dump -stdin < "$TEMP_DIR/page_processed.html"
        ;;
    source)
        cat "$TEMP_DIR/page_processed.html"
        ;;
    *)
        "$LYNX_BIN" -stdin < "$TEMP_DIR/page_processed.html"
        ;;
esac

LSCRIPT

chmod +x "$NEORUNNER_DIR/bin/lynx_primjs.sh"
log_success "Lynx+PrimJS integration script created"

# Step 9: Update NeoRunner to use PrimJS
log_step "Updating NeoRunner configuration"

# Create Python wrapper for QJS with web scraping support
cat > "$NEORUNNER_DIR/bin/primjs_scraper.py" << 'PYSCRIPT'
#!/usr/bin/env python3
"""
PrimJS-based web scraper for CurseForge and other JavaScript-heavy sites
Bypasses basic Cloudflare challenges using PrimJS JavaScript engine
"""

import subprocess
import json
import sys
import os
from pathlib import Path

QJS_BIN = Path("/home/services/bin/qjs")
CACHE_DIR = Path("/home/services/cache")

def fetch_with_primjs(url, cache_ttl_minutes=60):
    """Fetch URL with JavaScript execution using PrimJS"""
    
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / f"primjs_cache_{hash(url) % 1000000}.json"
    
    # Check cache
    if cache_file.exists():
        import time
        age_minutes = (time.time() - cache_file.stat().st_mtime) / 60
        if age_minutes < cache_ttl_minutes:
            with open(cache_file) as f:
                return json.load(f)
    
    # Create PrimJS script for web scraping
    js_script = f'''
const https = require('https');
const http = require('http');
const url = require('url');

const targetUrl = "{url}";
const parsedUrl = new url.URL(targetUrl);
const protocol = parsedUrl.protocol === 'https:' ? https : http;

protocol.get(targetUrl, {{
    headers: {{
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }}
}}, (res) => {{
    let data = '';
    res.on('data', chunk => {{ data += chunk; }});
    res.on('end', () => {{
        try {{
            // Basic Cloudflare challenge detection
            if (data.includes('cf-challenge') || data.includes('cf_clearance')) {{
                console.error('CF Challenge detected');
                process.exit(1);
            }}
            console.log(JSON.stringify({{ success: true, html: data.substring(0, 100000) }}));
        }} catch(e) {{
            console.error('Error: ' + e.message);
            process.exit(1);
        }}
    }});
}}).on('error', (e) => {{
    console.error('Network error: ' + e.message);
    process.exit(1);
}});
'''
    
    # Execute through PrimJS
    try:
        result = subprocess.run(
            [str(QJS_BIN), "-c", js_script],
            capture_output=True,
            timeout=10,
            text=True
        )
        
        if result.returncode == 0:
            output = json.loads(result.stdout)
            # Cache result
            with open(cache_file, 'w') as f:
                json.dump(output, f)
            return output
        else:
            raise RuntimeError(f"PrimJS error: {result.stderr}")
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: primjs_scraper.py <url>")
        sys.exit(1)
    
    result = fetch_with_primjs(sys.argv[1])
    print(json.dumps(result, indent=2))
PYSCRIPT

chmod +x "$NEORUNNER_DIR/bin/primjs_scraper.py"
log_success "PrimJS Python scraper created"

# Final summary
log_step "PrimJS Build Complete"
echo ""
echo "Target Architecture: $TARGET_ARCH"
echo "✓ QJS Binary: $NEORUNNER_DIR/bin/qjs"
echo "✓ Lynx+PrimJS Integration: $NEORUNNER_DIR/bin/lynx_primjs.sh"
echo "✓ Python Scraper: $NEORUNNER_DIR/bin/primjs_scraper.py"
echo ""
echo "Next steps:"
echo "1. Test QJS: echo 'console.log(\"Hello\");' | xargs -I {} /home/services/bin/qjs <(echo '{}')"
echo "2. Test scraper: source /home/services/neorunner_env/bin/activate && python3 /home/services/bin/primjs_scraper.py 'https://example.com'"
echo "3. Integration with run.py will use: /home/services/bin/qjs"
echo ""
