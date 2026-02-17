# NeoForged Advanced Server Script Documentation

## Overview

`neoforgedAdvanced.sh` is a comprehensive Minecraft NeoForged server management script that automates:
- Server startup with crash recovery
- Client mod synchronization via SMB (network share)
- World backups (incremental with hard links)
- Player session monitoring
- Server console interaction

The script uses **tmux** for process management and maintains comprehensive logs in `live.log`.

---

## Architecture

### Core Components

```
neoforgedAdvanced.sh
├── Logging System (timestamps, event types)
├── Hash-based Mod Sync (detects changes via SHA1)
├── Tmux Session Manager (isolated server process)
├── SMB Mount Handler (network share mounting)
├── Backup System (incremental + retention)
├── Connection Monitor (client detection)
└── Player Listener (event detection)
```

---

## Configuration

Located at the top of the script (lines 4-20):

```bash
SESSION="MC"                    # Tmux session name
BASE="/home/services"           # Root working directory
SERVER="$BASE"                  # Server directory
SRC="$BASE/mods/clientonly"     # Client-only mods to sync
LOG="$BASE/live.log"            # Main log file
CACHE="$BASE/mounts"            # Temp mount point for SMB shares
HASHFILE="$SRC/.hash"           # Hash of current mod state
SMBUSER="mc"                    # SMB authentication username
SMBPASS="123"                   # SMB authentication password
BACKUP_DIR="$BASE/backups"      # World backup location
WORLD_DIR="$BASE/world"         # Server world directory
```

### Key Paths
- **Mods**: `/home/services/mods/`
- **World Save**: `/home/services/world/`
- **JVM Args**: `/home/services/user_jvm_args.txt`
- **Libraries**: `/home/services/libraries/net/neoforged/neoforge/21.11.38-beta/`

---

## Command Reference

### `./neoforgedAdvanced.sh start`
**Starts the server with all background processes**

Launches in parallel:
1. `start_server()` - Main server process with crash detection
2. `backup_scheduler()` - Daily backup at 4 AM
3. `ss_monitor()` - Socket state monitor (detects new connections)
4. `listener()` - Tails logs for events

**Log Output**:
```
[SERVER_START] Starting Minecraft server (crash count: 0)
[SS_MONITOR] Starting socket state monitor on port 1234
[SERVER_RUNNING] Server process started
```

### `./neoforgedAdvanced.sh stop`
**Sends stop command to running server**

Issues `stop` to tmux console, triggers clean shutdown.

**Log Output**:
```
[COMMAND] Stop command sent
[SERVER_SHUTDOWN] Clean shutdown detected
```

### `./neoforgedAdvanced.sh console`
**Attach to interactive tmux session**

```bash
./neoforgedAdvanced.sh console
# Now in tmux - type Minecraft commands directly
# Exit with Ctrl+B then D
```

### `./neoforgedAdvanced.sh backup`
**Trigger manual world backup**

```bash
./neoforgedAdvanced.sh backup
```

**Backup Process**:
1. Announces "Starting world backup..." to players
2. Disables autosave (`save-off`)
3. Flushes world data (`save-all flush`)
4. Waits 5 seconds
5. Creates incremental backup using rsync with hard links
6. Re-enables autosave (`save-on`)

### `./neoforgedAdvanced.sh say <message>`
**Broadcast message to all players**

```bash
./neoforgedAdvanced.sh say "Server will restart in 5 minutes!"
```

### `./neoforgedAdvanced.sh cmd <command>`
**Send raw Minecraft console command**

```bash
./neoforgedAdvanced.sh cmd "give @a diamond 64"
./neoforgedAdvanced.sh cmd "tp @a 0 100 0"
```

---

## How It Works

### 1. Server Startup & Crash Detection

**File**: `neoforgedAdvanced.sh:274-322`

```bash
start_server()
```

- Starts Java with NeoForge in a tmux session
- Monitors process for crashes (detects if "Stopping server" is NOT in logs)
- Auto-restarts up to 5 times
- Logs all output to `live.log` via tmux pipe-pane

**Java Startup Command**:
```bash
java @user_jvm_args.txt @libraries/net/neoforged/neoforge/21.11.38-beta/unix_args.txt nogui
```

### 2. Mod Synchronization System

**Files**: `neoforgedAdvanced.sh:41-193`

#### How It Works:
1. **Hash Generation**: Creates SHA1 hash of all files in `mods/clientonly/`
2. **SMB Mount**: Mounts player's shared folder at `/home/services/mounts/<IP>/`
3. **Comparison**: Compares server hash vs client hash
4. **Sync**: Uses `rsync` to copy new/modified mods
5. **Player Kick**: Kicks player to rejoin with new mods

#### Detailed Flow:

```
Player Connects
    ↓
ss_monitor detects connection via socket state
    ↓
Extract player IP from connection
    ↓
sync_player(player_name, ip) called
    ↓
Generate server mod hash (SHA1)
    ↓
Mount client SMB share: //<IP>/mods → /home/services/mounts/<IP>
    ↓
Read client .hash file
    ↓
Compare hashes
    ├─ If MATCH: Skip (already synced)
    └─ If DIFFER: 
        ├─ rsync mods with --delete flag
        ├─ Write new hash to client
        ├─ Kick player with message "Mods updated. Please reconnect."
        └─ Player rejoins with new mods
```

**Key Command**:
```bash
rsync -rt --delete --timeout=60 "$SRC/" "$moddir/" >>"$LOG" 2>&1
```

Flags:
- `-r`: Recursive
- `-t`: Preserve timestamps
- `--delete`: Remove mods on client that aren't on server
- `--timeout=60`: 60 second timeout

### 3. World Backup System

**Files**: `neoforgedAdvanced.sh:195-249`

#### Backup Strategy:
- **First Backup**: Full copy
- **Subsequent**: Incremental using hard links (space efficient)
- **Retention**: Keeps last 7 days only

#### How Incremental Works:
```bash
rsync -a --link-dest="$BACKUP_DIR/$latest_backup" "$WORLD_DIR/" "$BACKUP_DIR/$backup_name/"
```

**Result**:
- New backup folder created
- Unchanged files are hard-linked (0 extra space)
- Only new/modified files consume disk space
- Can revert to any backup instantly

#### Backup Process:
```
Trigger backup (manual or 4 AM daily)
    ↓
Announce to players
    ↓
Disable autosave (save-off)
    ↓
Flush all world data (save-all flush)
    ↓
Wait 5 seconds
    ↓
rsync to backup directory
    ├─ If first: Full copy
    └─ If subsequent: Incremental with hard links
    ↓
Re-enable autosave (save-on)
    ↓
Announce complete
    ↓
Delete backups older than 7 days
```

### 4. Connection Monitoring

**Files**: `neoforgedAdvanced.sh:328-368`

**Tool**: `ss_monitor()` - Uses `ss` (socket statistics) command

```bash
ss -tnp | grep "<port>" | awk '{print $5}' | cut -d: -f1
```

This extracts:
- TCP connections (`-tn`)
- With process info (`-p`)
- Filters by server port (1234 by default)
- Extracts peer IP address from column 5

**Detection Flow**:
```
ss_monitor loop (every 0.5s)
    ↓
Get all connected client IPs
    ↓
Compare to last iteration
    ├─ NEW IP? → NEW_CONNECTION event
    │   ├─ Parse player name from recent logs
    │   ├─ Log: PLAYER_JOIN
    │   └─ Call sync_player(player, ip) in background
    └─ Same IPs? → No action
```

### 5. Log Listener

**Files**: `neoforgedAdvanced.sh:370-386`

Watches `live.log` with `tail -F`:

```bash
tail -Fn0 "$LOG" | while read -r line; do
  [[ "$line" =~ "Done".* ]] && log "SERVER_READY"
  [[ "$line" =~ "lost connection" ]] && log "PLAYER_LEAVE"
done
```

Detects:
- `"Done"` → Server is fully loaded
- `"lost connection"` or `"left the game"` → Player disconnect

---

## Logging System

### Log Format

```
2026-02-13 18:53:05 | [EVENT_TYPE] Message
```

### Event Types

| Event | Meaning |
|-------|---------|
| `SERVER_START` | Server startup initiated |
| `SERVER_RUNNING` | Server process created |
| `SERVER_STOPPED` | Server process exited |
| `SERVER_CRASH` | Crash detected, restarting |
| `SERVER_SHUTDOWN` | Clean shutdown (stop command) |
| `MOUNT` | SMB share mounted successfully |
| `MOUNT_FAIL` | SMB mount failed |
| `SYNC_SKIP` | Mods already up-to-date |
| `SYNC_START` | Beginning mod sync |
| `SYNC_COMPLETE` | Mods synced successfully |
| `SYNC_FAIL` | Mod sync failed |
| `NEW_CONNECTION` | Client IP connected |
| `PLAYER_JOIN` | Player name identified |
| `PLAYER_LEAVE` | Player disconnected |
| `BACKUP_START` | World backup started |
| `BACKUP_COMPLETE` | World backup finished |
| `BACKUP_FAIL` | Backup failed |
| `SS_MONITOR` | Connection monitor status |

---

## Tmux Session Management

### Creating the Session
The script auto-creates a tmux session named `MC`:

```bash
tmux new-session -d -s MC "cd /home/services && java ... nogui"
```

### Interacting with the Session

**Send commands** (internal function):
```bash
send "say Hello players!"  # Broadcasts message
send "stop"                 # Stops server
send "save-all"             # Saves world
```

**View console**:
```bash
./neoforgedAdvanced.sh console
# or
tmux attach -t MC
```

**List sessions**:
```bash
tmux list-sessions
```

### Why Tmux?
- **Persistent**: Server runs even if SSH connection drops
- **Scriptable**: Can send commands from anywhere
- **Observable**: Can attach/detach to view console
- **Clean Separation**: Isolated from shell environment

---

## SMB Mount Details

### Configuration
```bash
sudo mount -t cifs "//$ip/mods" "$mnt" \
  -o username=mc,password=123,soft,serverino,vers=3.0,iocharset=utf8
```

### Mount Options
- `soft`: Timeouts instead of hanging forever
- `serverino`: Use server inode numbers
- `vers=3.0`: SMB version 3.0
- `iocharset=utf8`: UTF-8 encoding

### Cleanup
On script exit, all mounted shares are unmounted:
```bash
trap cleanup EXIT INT TERM
```

This prevents stale mount points.

---

## Performance Tuning

### Sync Detection (Hash-based)
Instead of comparing all files each time, script maintains a SHA1 hash:

```bash
gen_hash() {
  find "$SRC" -type f -exec sha1sum {} \; | sort | sha1sum | cut -d' ' -f1
}
```

**Benefits**:
- Single hash comparison (fast)
- Detects any mod change instantly
- Works across disconnects

### Incremental Backups
Uses hard links to avoid duplicating unchanged files:

```
Backup 1: 2GB
Backup 2: 50MB (only new/modified)
Backup 3: 100MB (only new/modified)
Total disk used: ~2.15GB
```

Without hard links, would need ~6GB.

### Connection Polling
Monitors connections every 0.5 seconds:

```bash
sleep 0.5
```

Low enough to catch quick connections, high enough to not spam.

---

## Error Handling & Recovery

### Server Crashes
- Detects crash if "Stopping server" not in last 20 log lines
- Auto-restarts up to 5 times
- Stops if max crashes reached
- Logs each crash event

### Mount Failures
- 10-second timeout on mount attempts
- Falls back gracefully with error message
- Kicks player with explanation
- Continues monitoring for retry

### Sync Failures
- Prevents duplicate syncs with associative array
- Catches rsync errors
- Logs failure event
- Player notified via kick message

### Lost Log Connection
- `tail -F` automatically follows file rotations
- If listener dies, connection monitor still works
- Events still logged to file

---

## Troubleshooting

### Server won't start
Check `live.log` for Java errors:
```bash
tail -50 /home/services/live.log | grep ERROR
```

Verify JVM args file exists:
```bash
ls -la /home/services/user_jvm_args.txt
```

### Mods not syncing
Check SMB connectivity:
```bash
smbclient -U mc //192.168.x.x/mods -c ls
```

Verify hash file permissions:
```bash
ls -la /home/services/mods/clientonly/.hash
```

### Backups failing
Check world directory exists:
```bash
ls -la /home/services/world/
```

Verify backup directory writable:
```bash
touch /home/services/backups/test && rm /home/services/backups/test
```

### Player not detected
Check connection is actually established:
```bash
ss -tnp | grep 1234
```

Verify log contains player name:
```bash
grep "UUID of player" /home/services/live.log | tail -5
```

---

## Advanced Usage

### Killing the entire stack
```bash
# Kill all background processes
pkill -P $(pgrep -f "neoforgedAdvanced.sh start")

# Or kill tmux session
tmux kill-session -t MC
```

### Real-time monitoring
```bash
# Watch all events as they happen
tail -f /home/services/live.log | grep "\[PLAYER_\|\[SYNC_\|\[BACKUP_"
```

### Check mod hash
```bash
cat /home/services/mods/clientonly/.hash
```

### Manual rsync test
```bash
rsync -rt --delete --timeout=60 \
  /home/services/mods/clientonly/ \
  /home/services/mounts/192.168.1.100/ \
  -v  # Verbose to see what's happening
```

---

## Security Notes

**⚠️ Warning**: SMB credentials are in plain text in script.

### Better Approach:
1. Use SMB credentials file: `~/.smbcredentials`
2. Reference in mount: `-o credentials=/root/.smbcredentials`
3. Lock down file: `chmod 600 ~/.smbcredentials`

### Current Setup
```bash
-o username=mc,password=123
```

This is fine for LAN-only networks but not for internet-facing servers.

---

## Log Analysis Examples

### Find all player joins
```bash
grep "PLAYER_JOIN" /home/services/live.log
```

### Find sync issues
```bash
grep "SYNC_\|MOUNT_" /home/services/live.log
```

### Count crashes in last 24h
```bash
grep "SERVER_CRASH" /home/services/live.log | wc -l
```

### Timeline of events
```bash
tail -100 /home/services/live.log
```

---

## Related Files

```
/home/services/
├── neoforgedAdvanced.sh          # Main script
├── neoforgedAdvanced.sh.bak      # Backup of script
├── live.log                        # Main event log
├── user_jvm_args.txt              # JVM configuration
├── server.properties              # Minecraft server config
├── mods/
│   ├── clientonly/                # Synced to players
│   └── .hash                       # Current mod hash
├── world/                          # Active world save
├── backups/                        # Backup snapshots
│   ├── world_20260213_140000/
│   ├── world_20260213_150000/
│   └── world_20260213_160000/
├── mounts/                         # Temporary SMB mounts
│   ├── 192.168.1.100/
│   └── 192.168.1.101/
└── libraries/
    └── net/neoforged/neoforge/...  # Minecraft + NeoForge
```

---

## Performance Stats (Typical)

- **Server Startup**: 30-60 seconds (mod loading)
- **Mod Sync**: 5-15 seconds (first sync), <1 second (if unchanged)
- **Full Backup**: 2-5 minutes (depends on world size)
- **Incremental Backup**: 30 seconds - 2 minutes
- **Player Detection**: <1 second (0.5s polling)
- **Connection Monitor CPU**: <1% idle

---

## Future Improvements

- [ ] Encrypted SMB credentials
- [ ] Automatic mod validation/integrity checking
- [ ] Web dashboard for logs/status
- [ ] Discord webhook notifications
- [ ] Scheduled maintenance windows
- [ ] Player whitelist/ban list management
- [ ] Automated health checks

