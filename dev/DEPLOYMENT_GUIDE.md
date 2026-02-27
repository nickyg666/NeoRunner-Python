# NeoRunner - Deployment & Reproduction Guide

## Complete Setup for Multiple Machines

This guide provides step-by-step instructions for deploying NeoRunner to any Linux system from scratch.

## Phase 1: Infrastructure Setup

### 1.1 System Requirements Check

**Before starting, verify:**
- Linux OS (Ubuntu 20.04+, Debian 11+, CentOS 8+, or similar)
- Root or sudo access
- 2GB+ RAM (4GB+ recommended)
- 10GB+ free disk space
- Internet connection

**Check your system:**
```bash
# Check OS
cat /etc/os-release

# Check RAM
free -h

# Check disk
df -h /home

# Check Java
java -version
```

### 1.2 System Dependencies Installation

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y \
  python3 python3-venv python3-dev \
  openjdk-21-jre-headless \
  tmux curl rsync unzip zip git \
  build-essential

# Or use the automated setup script
bash setup.sh
```

## Phase 2: Repository & Code Setup

### 2.1 Clone or Download Code

**Option A: Git Clone (Recommended)**
```bash
cd /home/services
git clone https://github.com/your-username/neorunner.git .
```

**Option B: Manual Copy**
```bash
cd /home/services

# Copy these essential files:
# - run.py
# - ferium_manager.py
# - dashboard.py (optional)
# - dashboard.html
# - setup.sh
# - NEORUNNER_README.md
# - DEPLOYMENT_GUIDE.md

scp user@source:/home/services/{run.py,ferium_manager.py,*.html,*.sh,*.md} .
```

### 2.2 Run Automated Setup

```bash
cd /home/services
bash setup.sh
```

**What this does:**
1. ✓ Checks all system dependencies
2. ✓ Creates Python 3.10+ virtual environment
3. ✓ Installs all Python packages:
   - selenium (for CurseForge scraping)
   - requests, beautifulsoup4, lxml (web scraping)
   - flask (admin dashboard)
   - apscheduler (background tasks)
4. ✓ Downloads Ferium mod manager binary
5. ✓ Creates required directories
6. ✓ Shows systemd setup instructions

## Phase 3: Interactive Wizard

### 3.1 First Run - Configuration Wizard

```bash
cd /home/services
./neorunner_env/bin/python3 run.py run
```

**The wizard will ask:**

**A. RCON Configuration**
```
RCON password [changeme]: your-secure-password
RCON port [25575]: 25575  (or any free port)
```
- RCON is used for server commands and player monitoring
- Change the password immediately for security

**B. HTTP Mod Server**
```
HTTP mod port [8000]: 8000  (or any free port)
```
- Port 8000: Regular HTTP server for mod downloads
- Port 8001: Admin dashboard (auto-selected)

**C. Minecraft Configuration**
```
Minecraft version [1.21.11]: 1.21.11
Modloader (fabric/forge/neoforge) [neoforge]: neoforge
Server JAR path [only for fabric/forge]: 
```

**D. Ferium Setup**
```
Ferium profile name [neoserver]: neoserver
```

**E. CurseForge Integration**
```
CurseForge method [1=API key, 2=Selenium, 3=Skip]: 3
```
- **Option 1**: Use CurseForge API (requires free API key from https://console.curseforge.com/)
- **Option 2**: Use Selenium (slower, uses Firefox browser)
- **Option 3**: Modrinth only (recommended for speed)

**F. Mod Update Frequency**
```
Update frequency [4]: 4
```
- How often to check for mod updates (1-24 hours)
- Recommended: 4, 6, or 12 hours

**G. Weekly Updates**
```
Update day (mon-sun) [mon]: mon
Update hour (0-23) [2]: 2
```
- Day/time for strict version compatibility check
- This keeps server on current MC version

### 3.2 Configuration Saved

After wizard completes:
- **config.json** - All settings saved here
- **server.properties** - Minecraft server config (RCON enabled)
- Can edit config.json directly with text editor
- Changes take effect on next server restart

## Phase 4: NeoForge Installation (For NeoForge Loader)

### 4.1 Download NeoForge

```bash
# For NeoForge 21.11.38-beta (recommended)
wget https://maven.neoforged.net/releases/net/neoforged/neoforge/21.11.38-beta/neoforge-21.11.38-beta-installer.jar

# Run installer
java -jar neoforge-21.11.38-beta-installer.jar --installServer

# Verify installation
ls libraries/net/neoforged/neoforge/21.11.38-beta/
# Should contain: unix_args.txt, win_args.txt, neoforge-21.11.38-beta-universal.jar
```

### 4.2 Alternative: Fabric or Forge

**Fabric:**
```bash
# Download fabric-server.jar from https://fabricmc.net/use/server/
wget <download-url> -O fabric-server.jar
# Update config.json: "server_jar": "fabric-server.jar"
```

**Forge:**
```bash
# Download from https://files.minecraftforge.net/
wget <download-url> -O forge-server.jar
# Update config.json: "server_jar": "forge-server.jar"
```

## Phase 5: Start Server

### 5.1 Standalone Mode (For Testing)

```bash
./neorunner_env/bin/python3 run.py run
```

Expected output:
```
[BOOT] Checking prerequisites...
[BOOT] NeoForge server environment ready (using @args files)
[BOOT] Sorting mods by type (client/server/both)...
[BOOT] Starting server automation...
[HTTP_SERVER] Mod server starting on port 8000
[DASHBOARD] Starting admin dashboard on port 8001
[SERVER_START] Starting server
[SERVER_RUNNING] Server started in tmux session 'MC'
```

### 5.2 Systemd Service (For Production)

**Install Service:**
```bash
# From setup.sh output, find the systemd file location
sudo cp /tmp/neorunner.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable neorunner
```

**Manage Service:**
```bash
# Start
sudo systemctl start neorunner

# Check status
sudo systemctl status neorunner

# View logs
sudo journalctl -u neorunner -f

# Stop
sudo systemctl stop neorunner

# Restart
sudo systemctl restart neorunner
```

### 5.3 Tmux Session (Manual Control)

```bash
# Create session
tmux new-session -s minecraft -d

# Run server inside
tmux send-keys -t minecraft "cd /home/services && ./neorunner_env/bin/python3 run.py run" Enter

# Reconnect later
tmux attach -t minecraft

# Detach (Ctrl+B then D)
# Kill session
tmux kill-session -t minecraft
```

## Phase 6: Post-Startup Configuration

### 6.1 Access Points

After server starts:

| Service | URL | Purpose |
|---------|-----|---------|
| Admin Dashboard | `http://localhost:8001` | Server management & config |
| Mod Downloads | `http://localhost:8000` | Client mod distribution |
| RCON | `localhost:25575` | Server commands (via RCON client) |

### 6.2 First-Time Configuration (Optional)

**Run Mod Curator:**
```bash
./neorunner_env/bin/python3 run.py curator --limit 100
```
- Discovers and lets you select mods to add
- Or add mods manually via Ferium:
  ```bash
  ./neorunner_env/bin/python3 -c "from ferium_manager import FeriumManager; m = FeriumManager(); m.add_modrinth_mod('sodium')"
  ```

**Download Initial Mods:**
```bash
./.local/bin/ferium upgrade
```

## Phase 7: Network & Security

### 7.1 Firewall Configuration

```bash
# Allow local access only (recommended)
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from 192.168.0.0/16 to any port 8000,8001,25575
sudo ufw enable

# Or allow specific IPs
sudo ufw allow from 192.168.1.100 to any port 8001
```

### 7.2 Change RCON Password

Edit `config.json`:
```json
{
  "rcon_pass": "strong-password-here"
}
```

Then restart server:
```bash
sudo systemctl restart neorunner
```

### 7.3 Network Binding

**Local only (secure):**
- Edit `server.properties`: `server-ip=127.0.0.1`
- Dashboard auto-binds to 0.0.0.0 (local network only if behind firewall)

**Public access (risky):**
- Leave `server-ip` blank
- Use firewall/VPN to restrict access

## Phase 8: Verification & Testing

### 8.1 Server Status Check

```bash
# Check if running
tmux list-sessions | grep MC

# Check ports
lsof -i :8000  # Mod server
lsof -i :8001  # Dashboard
lsof -i :25575 # RCON

# Check configuration
cat config.json
cat server.properties | grep -E "rcon|enable-rcon"
```

### 8.2 Test Connections

```bash
# Test HTTP server
curl http://localhost:8000/

# Test Dashboard
curl http://localhost:8001/api/status

# Test RCON
echo "list" | nc -w 1 localhost 25575

# Check logs
tail -100 live.log
```

### 8.3 Mod Manager Test

```bash
# List current profile
./.local/bin/ferium profile list

# List mods
./.local/bin/ferium list -v

# Test upgrade
./.local/bin/ferium upgrade
```

## Phase 9: Backup & Restore

### 9.1 Backup Configuration

```bash
# Backup entire server
tar -czf /backups/neorunner-$(date +%Y%m%d).tar.gz \
  /home/services/config.json \
  /home/services/server.properties \
  /home/services/mods/ \
  /home/services/world/

# Backup just config
cp /home/services/config.json /backups/config.json.bak
```

### 9.2 Restore to New Machine

```bash
# On new machine, after running setup.sh:
tar -xzf /backups/neorunner-YYYYMMDD.tar.gz -C /home/services

# Or just restore config:
cp /backups/config.json.bak /home/services/config.json

# Restart server
sudo systemctl restart neorunner
```

## Phase 10: Monitoring & Maintenance

### 10.1 Monitor Disk Usage

```bash
# Check mods folder size
du -sh /home/services/mods

# Check backups
du -sh /home/services/backups

# Clean old backups (keep 7 days)
find /home/services/backups -type d -mtime +7 -exec rm -rf {} \;
```

### 10.2 Monitor Update Jobs

```bash
# Check scheduler status
# (View in logs or via dashboard)
tail -50 live.log | grep FERIUM_TASK

# Check next update time
grep "next.*hours" live.log
```

### 10.3 Logs Location

```bash
# Server logs
/home/services/live.log

# Systemd logs (if running as service)
sudo journalctl -u neorunner -n 500

# Minecraft server console
tmux capture-pane -t minecraft -p
```

## Troubleshooting

### Issue: "Python module not found"

```bash
# Reactivate venv
source /home/services/neorunner_env/bin/activate

# Reinstall deps
pip install flask apscheduler selenium requests beautifulsoup4 lxml

# Run again
./neorunner_env/bin/python3 run.py run
```

### Issue: "Ferium command not found"

```bash
# Check if binary exists
ls -la /home/services/.local/bin/ferium

# Reinstall
bash setup.sh  # Will re-download Ferium

# Verify
/home/services/.local/bin/ferium --version
```

### Issue: "Port already in use"

```bash
# Find what's using port 8000
lsof -i :8000
kill -9 <PID>

# Or change port in config.json
```

### Issue: "RCON not connecting"

```bash
# Verify RCON is enabled
grep "enable-rcon" server.properties

# Check if server is running
tmux list-sessions

# Test directly
echo "list" | nc -w 1 localhost 25575
```

## Advanced: Deployment to Multiple Machines

### Method 1: Docker (Future)

```dockerfile
FROM ubuntu:22.04
WORKDIR /home/services
COPY setup.sh .
RUN bash setup.sh
COPY --chown=services:services . .
EXPOSE 8000 8001 25575
CMD ["./neorunner_env/bin/python3", "run.py", "run"]
```

Build and run:
```bash
docker build -t neorunner .
docker run -d \
  -p 8000:8000 \
  -p 8001:8001 \
  -p 25575:25575 \
  -v neorunner-data:/home/services \
  neorunner
```

### Method 2: Ansible Playbook (Future)

```yaml
---
- hosts: minecraft_servers
  become: yes
  tasks:
    - name: Clone NeoRunner
      git:
        repo: https://github.com/your-repo/neorunner.git
        dest: /home/services
        
    - name: Run setup
      shell: bash setup.sh
      args:
        chdir: /home/services
        
    - name: Start service
      systemd:
        name: neorunner
        state: started
        enabled: yes
```

### Method 3: Terraform + Cloud (Future)

Template for AWS/Azure/DigitalOcean with automated deployment.

## Checklist: Reproduction Steps

- [ ] System meets requirements (2GB RAM, 10GB disk, Java 21)
- [ ] Clone repository or copy files to /home/services
- [ ] Run `bash setup.sh` successfully
- [ ] Activate venv: `source neorunner_env/bin/activate`
- [ ] Run wizard: `python3 run.py run`
- [ ] Complete all wizard prompts
- [ ] Server starts (check logs)
- [ ] Access dashboard: `http://localhost:8001`
- [ ] Access mods: `http://localhost:8000`
- [ ] Test RCON: `echo "list" | nc localhost 25575`
- [ ] Configure as systemd service (optional)
- [ ] Test mod upgrade: `./.local/bin/ferium upgrade`
- [ ] Verify backups created: `ls -la backups/`

## Success Indicators

After full setup, you should see:
```
✓ Server running in tmux session 'MC'
✓ Dashboard accessible at http://localhost:8001
✓ Mod server accessible at http://localhost:8000
✓ Mods directory populated
✓ Backups directory with daily backups
✓ live.log showing server activity
✓ config.json with your settings
✓ RCON working (test with: echo "list" | nc localhost 25575)
✓ Ferium profile active and upgrading mods on schedule
```

---

**Last Updated**: 2026-02-18
**Version**: 1.0.0-complete

For issues or questions, check the main README and log files.
