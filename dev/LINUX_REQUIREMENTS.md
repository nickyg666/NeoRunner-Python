# NeoRunner Linux System Requirements

## Ubuntu 24.04 LTS (Primary Support)

### System Package Installation

```bash
# Core dependencies
sudo apt-get update
sudo apt-get install -y \
    xvfb \
    firefox \
    firefox-geckodriver \
    python3-full \
    python3-venv

# Optional: for additional stability
sudo apt-get install -y calibre
```

### Python Environment Setup

```bash
# Create virtual environment in /home/services
cd /home/services
python3 -m venv neorunner_env

# Activate venv
source neorunner_env/bin/activate

# Install Python dependencies
pip install -r requirements.txt
```

### Verify Installation

```bash
# Check system binaries
which firefox geckodriver xvfb-run

# Verify Firefox and GeckoDriver versions
firefox --version
geckodriver --version

# Verify Python packages
python3 -c "import selenium; print(f'Selenium {selenium.__version__}')"
```

## Supported Versions

- **Firefox**: 140+ (Mozilla Firefox)
- **GeckoDriver**: 0.36.0+ (snap package)
- **Selenium**: 4.40.0+
- **xvfb**: 2:21.1.12+
- **Python**: 3.12+

## Virtual Environment Activation

Always activate before running NeoRunner:

```bash
source /home/services/neorunner_env/bin/activate
python3 run.py
```

## Troubleshooting

### GeckoDriver not found
```bash
# GeckoDriver installed via snap
# Make sure /snap/bin is in PATH
export PATH="/snap/bin:$PATH"
```

### Selenium import fails
```bash
# Ensure venv is activated
source neorunner_env/bin/activate

# Reinstall Selenium
pip install --force-reinstall selenium
```

### xvfb errors
```bash
# Test xvfb directly
xvfb-run -a echo "xvfb working"

# If fails, reinstall
sudo apt-get reinstall xvfb
```

## CurseForge Scraper Dependencies

The CurseForge scraper uses:
- **Selenium**: Browser automation framework
- **Firefox headless**: JavaScript rendering engine
- **xvfb**: Virtual display for headless operation
- **GeckoDriver**: Firefox WebDriver protocol implementation

All required components are installed by this setup.
