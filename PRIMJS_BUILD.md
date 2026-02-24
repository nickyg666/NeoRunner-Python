# PrimJS + Linux Build System Setup for NeoRunner

## Overview

This document covers building **PrimJS** (a high-performance JavaScript engine for Lynx) on Linux to enable CurseForge web scraping bypassing Cloudflare challenges.

**PrimJS** is ES2019-compatible and based on QuickJS, designed for the Lynx browser framework. It provides JavaScript execution on Linux systems without needing a full browser.

## System Requirements

### Ubuntu 24.04 LTS - Verified Working

#### 1. Core Build Tools
```bash
sudo apt-get update
sudo apt-get install -y \
    golang-go \
    ninja-build \
    git \
    python3 \
    python3-dev \
    python3-pip \
    build-essential \
    gcc g++ \
    pkg-config \
    libcurl4-openssl-dev
```

**Installed Versions (Verified):**
- Go: 1.22.2
- Ninja: 1.11.1
- GCC/G++: 13.3.0
- Python: 3.12.1

#### 2. Network Tools (for scraping)
```bash
sudo apt-get install -y \
    curl \
    wget \
    lynx
```

#### 3. Virtual Display (for headless browser fallback)
```bash
sudo apt-get install -y xvfb
```

## Build Process

### Automated Setup (Recommended)

```bash
# Navigate to NeoRunner directory
cd /home/services

# Run automated PrimJS build
bash setup_primjs.sh

# Takes 15-45 minutes depending on system (downloads ~500MB, compiles ~20 min)
```

### Manual Build Process

If the automated script fails, follow these steps:

#### Step 1: Clone PrimJS
```bash
export PATH="/usr/lib/go-1.22/bin:$PATH"
cd /tmp
git clone https://github.com/lynx-family/primjs.git
cd primjs
source tools/envsetup.sh
```

#### Step 2: Download Dependencies
```bash
# Downloads buildtools (gn, ninja, llvm, cmake) - ~500MB
bash tools/hab sync

# This takes 5-15 minutes
```

#### Step 3: Generate Build Configuration
```bash
# Simple x86_64 build (recommended for faster compilation)
buildtools/gn/gn gen out/Default
```

#### Step 4: Compile
```bash
# Compile with all available cores
buildtools/ninja/ninja -C out/Default qjs_exe -j$(nproc)

# Takes 10-30 minutes depending on CPU cores
```

#### Step 5: Copy Binary
```bash
mkdir -p /home/services/bin
cp out/Default/qjs /home/services/bin/qjs
chmod +x /home/services/bin/qjs

# Verify
/home/services/bin/qjs --version
```

## Integration with NeoRunner

Once built, PrimJS is integrated for CurseForge scraping:

### 1. Python Wrapper (primary method)
```bash
/home/services/bin/primjs_scraper.py <url>
```

Handles:
- Basic Cloudflare challenge detection
- Caches responses (60 minute default)
- Returns JSON with HTML content
- Fallback on error

### 2. Direct QJS Usage
```bash
/home/services/bin/qjs script.js
```

### 3. Lynx + PrimJS Integration (advanced)
```bash
/home/services/bin/lynx_primjs.sh "https://curseforge.com/..." --dump
```

## Troubleshooting

### Build Fails: "gn not found"
```bash
# Ensure buildtools were synced
cd /path/to/primjs
bash tools/hab sync
ls -la buildtools/gn/gn  # Should exist
```

### Build Fails: "ninja: command not found"
```bash
# Use full path or add to PATH
export PATH="/path/to/primjs/buildtools/ninja:$PATH"
```

### Compilation Takes Too Long
- Normal on systems with <4 cores
- Use `-j$(nproc)` to parallelize
- Can be interrupted and resumed (rebuild just does incremental)

### QJS Binary Won't Execute
```bash
# Check if binary is actually built
file /home/services/bin/qjs

# Test execution
/home/services/bin/qjs -c 'print("Hello from QJS")'

# If segfaults: rebuild with fresh clone
rm -rf /path/to/primjs
bash setup_primjs.sh
```

## Performance Notes

- **Build Time**: 15-45 minutes (first time, includes downloading ~500MB of dependencies)
- **QJS Size**: ~3MB binary
- **Runtime Memory**: ~15-30MB per instance
- **Startup Time**: ~100-200ms

## Cloudflare Challenge Support

**PrimJS capabilities vs Cloudflare:**
- ✓ Executes basic JavaScript
- ✓ Handles simple math challenges
- ✓ Manages cookies/session tokens
- ✗ Does NOT execute complex v8 bytecode
- ✗ Does NOT handle browser fingerprinting challenges

For advanced Cloudflare challenges, fallback to Selenium + Firefox.

## Directory Structure After Build

```
/home/services/
├── bin/
│   ├── qjs                      (PrimJS binary)
│   ├── lynx_primjs.sh          (Lynx integration script)
│   └── primjs_scraper.py       (Python wrapper)
├── primjs/                      (PrimJS source repo)
│   ├── out/Default/qjs_exe
│   ├── buildtools/             (gn, ninja, llvm, cmake)
│   ├── build/                  (Chromium buildroot)
│   └── third_party/            (V8, QuickJS, dependencies)
└── cache/                       (Scraper cache)
```

## Next Steps for CurseForge Scraping

1. ✓ Build PrimJS (this document)
2. ⏳ Integrate `primjs_scraper.py` into `run.py`
3. ⏳ Create CurseForge-specific scraper using PrimJS
4. ⏳ Test against live CurseForge pages
5. ⏳ Handle Cloudflare fallback to Selenium+Firefox

## Additional Resources

- **PrimJS GitHub**: https://github.com/lynx-family/primjs
- **QuickJS Docs**: https://bellard.org/quickjs/
- **Lynx Browser**: https://lynx.invisible-island.net/
