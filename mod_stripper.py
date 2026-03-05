#!/usr/bin/env python3
"""Server-only mod stripper - removes client classes for server-safe JARs."""

import os
import shutil
import zipfile
from pathlib import Path

# Client-side packages/classes to strip
CLIENT_PATTERNS = [
    "net/minecraft/client",
    "net/minecraftforge/client",
    "net/minecraftforge/fmlclient",
    "com/mojang/blaze3d",
    "com/mojang/authlib",
    "pauloicaro/gads",
    "me/jupiter/mirror/client",
]

# Files to always strip
CLIENT_FILES = [
    "mixins.client.json",
    "client.mixins.json",
]


def is_client_class(name: str) -> bool:
    """Check if a file is a client-side class."""
    for pattern in CLIENT_PATTERNS:
        if pattern in name:
            return True
    return False


def strip_mod(input_jar: str, output_jar: str) -> bool:
    """Strip client classes from a mod JAR."""
    try:
        with zipfile.ZipFile(input_jar, 'r') as zin:
            with zipfile.ZipFile(output_jar, 'w', zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    name = item.filename
                    
                    # Skip client-specific files
                    if any(pat in name for pat in CLIENT_FILES):
                        continue
                    
                    # Skip client classes
                    if name.endswith('.class') and is_client_class(name):
                        continue
                    
                    # Skip client-only assets
                    if '/textures/gui/' in name or '/sounds/' in name:
                        continue
                    
                    # Copy everything else
                    zout.writestr(item, zin.read(name))
        
        return True
    except Exception as e:
        print(f"Error stripping {input_jar}: {e}")
        return False


def process_mods_dir(mods_dir: str):
    """Process mods directory - create server-safe versions."""
    mods_path = Path(mods_dir)
    clientonly = mods_path / "clientonly"
    clientonly.mkdir(exist_ok=True)
    
    # Mods that need server-safe versions (have client classes but needed on server, manually editing which totally breaks workflow)
    server_required = {
        "entity_model_features",
        "entity_texture_features", 
    }
    
    stripped_count = 0
    
    for mod_file in list(mods_path.glob("*.jar")):
        mod_name = mod_file.stem.lower()
        
        # Check if this mod needs stripping
        needs_strip = any(req in mod_name for req in server_required)
        
        if needs_strip:
            # Move original to clientonly
            clientonly_file = clientonly / mod_file.name
            if not clientonly_file.exists():
                print(f"Moving to clientonly: {mod_file.name}")
                shutil.move(str(mod_file), str(clientonly_file))
            
            # Create server-safe version
            server_file = mods_path / mod_file.name
            if not server_file.exists():
                print(f"Creating server-safe: {mod_file.name}")
                if strip_mod(str(clientonly_file), str(server_file)):
                    stripped_count += 1
    
    print(f"Created {stripped_count} server-safe mod versions")
    return stripped_count


if __name__ == "__main__":
    import sys
    from pathlib import Path
    mods_dir = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent / "mods")
    process_mods_dir(mods_dir)
