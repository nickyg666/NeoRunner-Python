"""
NBT Parser for reading Minecraft world data.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Dict, Any, Optional, Union
from io import BytesIO


def read_nbt_string(data: BytesIO) -> str:
    """Read a UTF-8 string from NBT data."""
    length = struct.unpack(">H", data.read(2))[0]
    if length == 0:
        return ""
    return data.read(length).decode('utf-8')


def read_nbt_int(data: BytesIO) -> int:
    """Read a 32-bit signed integer."""
    return struct.unpack(">i", data.read(4))[0]


def read_nbt_byte(data: BytesIO) -> int:
    """Read a single signed byte."""
    return struct.unpack(">b", data.read(1))[0]


def read_nbt_short(data: BytesIO) -> int:
    """Read a 16-bit signed short."""
    return struct.unpack(">h", data.read(2))[0]


def read_nbt_long(data: BytesIO) -> int:
    """Read a 64-bit signed long."""
    return struct.unpack(">q", data.read(8))[0]


def read_nbt_float(data: BytesIO) -> float:
    """Read a 32-bit float."""
    return struct.unpack(">f", data.read(4))[0]


def read_nbt_double(data: BytesIO) -> float:
    """Read a 64-bit double."""
    return struct.unpack(">d", data.read(8))[0]


def read_nbt_byte_array(data: BytesIO) -> bytes:
    """Read a byte array."""
    length = read_nbt_int(data)
    return data.read(length)


def read_nbt_int_array(data: BytesIO) -> list:
    """Read an int array."""
    length = read_nbt_int(data)
    return [read_nbt_int(data) for _ in range(length)]


def read_nbt_long_array(data: BytesIO) -> list:
    """Read a long array."""
    length = read_nbt_int(data)
    return [read_nbt_long(data) for _ in range(length)]


def read_nbt_list(data: BytesIO) -> list:
    """Read a list tag."""
    tag_type = read_nbt_byte(data)
    length = read_nbt_int(data)
    
    items = []
    for _ in range(length):
        if tag_type == 1:  # Byte
            items.append(read_nbt_byte(data))
        elif tag_type == 2:  # Short
            items.append(read_nbt_short(data))
        elif tag_type == 3:  # Int
            items.append(read_nbt_int(data))
        elif tag_type == 4:  # Long
            items.append(read_nbt_long(data))
        elif tag_type == 5:  # Float
            items.append(read_nbt_float(data))
        elif tag_type == 6:  # Double
            items.append(read_nbt_double(data))
        elif tag_type == 8:  # String
            items.append(read_nbt_string(data))
        elif tag_type == 10:  # Compound
            items.append(read_nbt_compound(data))
        else:
            # Skip unknown types
            pass
    
    return items


def read_nbt_compound(data: BytesIO, depth: int = 0) -> Dict[str, Any]:
    """Read a compound tag."""
    if depth > 512:  # Prevent stack overflow
        return {}
    
    result = {}
    
    while True:
        try:
            tag_type = read_nbt_byte(data)
            
            if tag_type == 0:  # End tag
                break
            
            name = read_nbt_string(data)
            
            if tag_type == 1:  # Byte
                result[name] = read_nbt_byte(data)
            elif tag_type == 2:  # Short
                result[name] = read_nbt_short(data)
            elif tag_type == 3:  # Int
                result[name] = read_nbt_int(data)
            elif tag_type == 4:  # Long
                result[name] = read_nbt_long(data)
            elif tag_type == 5:  # Float
                result[name] = read_nbt_float(data)
            elif tag_type == 6:  # Double
                result[name] = read_nbt_double(data)
            elif tag_type == 7:  # Byte Array
                result[name] = read_nbt_byte_array(data)
            elif tag_type == 8:  # String
                result[name] = read_nbt_string(data)
            elif tag_type == 9:  # List
                result[name] = read_nbt_list(data)
            elif tag_type == 10:  # Compound
                result[name] = read_nbt_compound(data, depth + 1)
            elif tag_type == 11:  # Int Array
                result[name] = read_nbt_int_array(data)
            elif tag_type == 12:  # Long Array
                result[name] = read_nbt_long_array(data)
        except:
            break
    
    return result


def decompress_nbt(data: bytes) -> BytesIO:
    """Decompress NBT data if compressed."""
    # Try gzip first
    try:
        import gzip
        return BytesIO(gzip.decompress(data))
    except:
        pass
    
    # Try zlib
    try:
        import zlib
        return BytesIO(zlib.decompress(data))
    except:
        pass
    
    # Assume uncompressed
    return BytesIO(data)


def parse_nbt(data: bytes) -> Dict[str, Any]:
    """Parse NBT data and return the root compound."""
    stream = decompress_nbt(data)
    
    # Read root tag
    root_type = read_nbt_byte(stream)
    if root_type != 10:  # Must be compound
        raise ValueError(f"Expected compound tag at root, got {root_type}")
    
    root_name = read_nbt_string(stream)
    root_data = read_nbt_compound(stream)
    
    return {
        "name": root_name,
        "data": root_data
    }


def get_world_version(level_dat_path: Union[str, Path]) -> Dict[str, Any]:
    """
    Extract world version information from level.dat file.
    """
    try:
        with open(level_dat_path, 'rb') as f:
            data = f.read()
        
        nbt = parse_nbt(data)
        
        # Navigate to Data -> Version or Data -> DataVersion
        root_data = nbt.get("data", {})
        
        # Check for nested Data structure (NEO format)
        if isinstance(root_data, dict) and "Data" in root_data:
            root_data = root_data["Data"]
        
        # Modern versions store version in Data.Version
        if "Version" in root_data:
            version_data = root_data["Version"]
            if isinstance(version_data, dict):
                return {
                    "version": version_data.get("Name", "unknown"),
                    "snapshot": version_data.get("Snapshot", False),
                    "platform": version_data.get("Series", "main")
                }
        
        # Also check if version is directly in Data
        if "version" in root_data:
            data_version = root_data["version"]
            if isinstance(data_version, int):
                version_map = {
                    3953: "1.21",
                    3955: "1.21.1",
                    3959: "1.21.2",
                    4082: "1.21.3",
                    4101: "1.21.4",
                    4324: "1.21.5",
                    4325: "1.21.6",
                    4326: "1.21.7",
                    4327: "1.21.8",
                    4328: "1.21.9",
                    4329: "1.21.10",
                    4330: "1.21.11",
                }
                mc_version = version_map.get(data_version, f"unknown ({data_version})")
                return {
                    "version": mc_version,
                    "snapshot": False,
                    "platform": "main"
                }
        
        # Legacy versions use DataVersion number
        if "DataVersion" in root_data:
            data_version = root_data["DataVersion"]
            version_map = {
                3953: "1.21",
                3955: "1.21.1",
                3959: "1.21.2",
                4082: "1.21.3",
                4101: "1.21.4",
                4324: "1.21.5",
                4325: "1.21.6",
                4326: "1.21.7",
                4327: "1.21.8",
                4328: "1.21.9",
                4329: "1.21.10",
                4330: "1.21.11",
            }
            mc_version = version_map.get(data_version, f"unknown ({data_version})")
            return {
                "version": mc_version,
                "snapshot": False,
                "platform": "main"
            }
        
        return {
            "version": "unknown",
            "snapshot": False,
            "platform": "main"
        }
        
    except Exception as e:
        return {
            "version": None,
            "error": str(e),
            "snapshot": False,
            "platform": "unknown"
        }
