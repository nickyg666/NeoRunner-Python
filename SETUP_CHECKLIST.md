# Pre-Build Verification Checklist

Run these commands to verify everything is ready before running `setup_primjs.sh`:

## ✅ Required System Tools

```bash
# Go compiler
/usr/lib/go-1.22/bin/go version
# Expected: go version go1.22.2 linux/amd64

# Ninja build system  
ninja --version
# Expected: 1.11 or higher

# Git
git --version
# Expected: git version 2.x.x

# Curl
curl --version
# Expected: curl 7.x.x or higher

# Build essentials
gcc --version | head -1
# Expected: gcc (Ubuntu 13.3.0...) or similar

# Python
python3 --version
# Expected: Python 3.12.x or 3.11.x

# Lynx (for wrapper)
lynx --version | head -1
# Expected: Lynx Version 2.9.x
```

## ✅ Python Virtual Environment

```bash
# Check venv exists
ls -d /home/services/neorunner_env
# Should exist

# Verify Selenium installed in venv
source /home/services/neorunner_env/bin/activate
python3 -c "import selenium; print(f'Selenium {selenium.__version__}')"
# Expected: Selenium 4.40.0 or higher

# Verify you're in the venv
which python3
# Should show: /home/services/neorunner_env/bin/python3
```

## ✅ Build Scripts Present

```bash
# Setup script exists and is executable
ls -lh /home/services/setup_primjs.sh
# Should show: -rwxrwxr-x

# Documentation exists
ls -1 /home/services/{PRIMJS_BUILD.md,PRIMJS_INTEGRATION_STATUS.md,requirements.txt,BUILD_SUMMARY.txt}
# All 4 files should list
```

## ✅ Network Connectivity

```bash
# Can reach GitHub
curl -I https://github.com/lynx-family/primjs.git 2>&1 | head -1
# Should show: HTTP/1.1 200 or 301 (redirect OK)

# Can reach release assets
curl -I https://github.com/lynx-family/buildtools/releases/download/gn-cc28efe6/buildtools-gn-linux-x86_64.tar.gz 2>&1 | head -1
# Should show: HTTP/1.1 200 or 302 (redirect OK)
```

## ✅ Disk Space

```bash
# Check free space (need ~2GB for build)
df -h /home/services | tail -1
# Available column should show 2GB+ free

# Check /tmp space (where dependencies download)
df -h /tmp | tail -1
# Available column should show 500MB+ free
```

## 🚀 Ready to Build?

If all checks above pass, you're ready!

```bash
cd /home/services
bash setup_primjs.sh

# Monitor progress in another terminal:
watch -n 1 'ps aux | grep -E "(gn|ninja|gcc)" | grep -v grep'
```

## Troubleshooting Pre-Build Issues

### Go not found
```bash
export PATH="/usr/lib/go-1.22/bin:$PATH"
go version
```

### Ninja not found
```bash
which ninja
# If empty, reinstall:
sudo apt-get install -y ninja-build
```

### Git cannot clone
- Check network: `ping github.com`
- Try SSH if HTTPS fails: `git clone git@github.com:lynx-family/primjs.git`
- Wait if rate-limited (GitHub: 60 req/hour unauthenticated)

### Low disk space
```bash
# Clean package cache
sudo apt-get clean

# Check what's taking space
du -sh /home/services/* | sort -h

# Safe to remove old log files
rm -f /home/services/logs/*.log
```

### Venv broken
```bash
rm -rf /home/services/neorunner_env
python3 -m venv /home/services/neorunner_env
source /home/services/neorunner_env/bin/activate
pip install -r /home/services/requirements.txt
```

---

**Status**: Ready to build ✅

**Next**: Run `bash /home/services/setup_primjs.sh`
