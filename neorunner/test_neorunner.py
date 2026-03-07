#!/usr/bin/env python3
"""Test runner for NeoRunner refactored package on parallel ports."""

from neorunner import (
    load_cfg,
    ServerConfig,
    PARALLEL_PORTS,
    log_event,
    is_server_running,
    classify_mod,
    sort_mods_by_type,
)
from pathlib import Path

def main():
    print("=" * 50)
    print("NeoRunner Package Test (Parallel Ports)")
    print("=" * 50)
    
    # Load original config
    cfg = load_cfg()
    print(f"\nOriginal config:")
    print(f"  http_port: {cfg.http_port}")
    print(f"  mc_port: {cfg.mc_port}")
    print(f"  loader: {cfg.loader}")
    print(f"  mc_version: {cfg.mc_version}")
    
    # Get parallel config
    parallel_cfg = cfg.with_parallel_ports()
    print(f"\nParallel config:")
    print(f"  http_port: {parallel_cfg.http_port}")
    print(f"  mc_port: {parallel_cfg.mc_port}")
    print(f"  rcon_port: {parallel_cfg.rcon_port}")
    
    # Test mod classification
    mods_dir = Path("/home/services/dev/mods")
    print(f"\nTesting mod classification on: {mods_dir}")
    
    if mods_dir.exists():
        sorted_mods = sort_mods_by_type(mods_dir, cfg)
        print(f"  clientonly: {len(sorted_mods['clientonly'])} mods")
        print(f"  server: {len(sorted_mods['server'])} mods")
        print(f"  both: {len(sorted_mods['both'])} mods")
        
        # Show first few client-only mods
        if sorted_mods['clientonly']:
            print(f"\n  First 5 client-only mods:")
            for mod in sorted_mods['clientonly'][:5]:
                print(f"    - {mod.name}")
    
    # Check server status
    print(f"\nServer status:")
    print(f"  is_running: {is_server_running()}")
    
    # Test logging
    log_event("INFO", "Test log message from refactored package")
    print(f"\nLog test - check /home/services/dev/live.log")
    
    print("\n" + "=" * 50)
    print("Test complete!")
    print("=" * 50)

if __name__ == "__main__":
    main()
