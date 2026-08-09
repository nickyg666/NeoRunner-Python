# NeoRunner Session - Host 192.168.0.150

## Services Running
- port 8000: NeoRunner Dashboard
- port 8003: OpenCode Web UI  
- port 1234: Minecraft (NeoForge 26.1.2)
- Orchestrator: ~/bin/orchestrator (watching tasks.json)

## Working Model
- opencode/claude-opus-4-7 (bundled - no key needed)

## Free Models Not Working
- opencode/minimax-m2.5-free - needs API key validation
- opencode/hy3-preview-free - hangs/times out

## Tasks
Queue in tasks.json - processed by orchestrator

## Access
- http://192.168.0.150:8000 - Dashboard
- http://192.168.0.150:8003 - OpenCode Web
- ssh host@192.168.0.150 (password: 1)
