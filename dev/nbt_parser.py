"""
NBT Parser for Minecraft level.dat files.

Extracts version information from Minecraft world files.
"""

import gzip
import struct
from pathlib import Path
from typing import Any, BinaryIO


TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11


class NBTReader:
    def __init__(self, stream: BinaryIO):
        self.stream = stream

    def read_byte(self) -> int:
        data = self.stream.read(1)
        if not data:
            raise EOFError("Unexpected end of stream")
        return struct.unpack(">b", data)[0]

    def read_ubyte(self) -> int:
        data = self.stream.read(1)
        if not data:
            raise EOFError("Unexpected end of stream")
        return struct.unpack(">B", data)[0]

    def read_short(self) -> int:
        data = self.stream.read(2)
        if len(data) < 2:
            raise EOFError("Unexpected end of stream")
        return struct.unpack(">h", data)[0]

    def read_ushort(self) -> int:
        data = self.stream.read(2)
        if len(data) < 2:
            raise EOFError("Unexpected end of stream")
        return struct.unpack(">H", data)[0]

    def read_int(self) -> int:
        data = self.stream.read(4)
        if len(data) < 4:
            raise EOFError("Unexpected end of stream")
        return struct.unpack(">i", data)[0]

    def read_long(self) -> int:
        data = self.stream.read(8)
        if len(data) < 8:
            raise EOFError("Unexpected end of stream")
        return struct.unpack(">q", data)[0]

    def read_float(self) -> float:
        data = self.stream.read(4)
        if len(data) < 4:
            raise EOFError("Unexpected end of stream")
        return struct.unpack(">f", data)[0]

    def read_double(self) -> float:
        data = self.stream.read(8)
        if len(data) < 8:
            raise EOFError("Unexpected end of stream")
        return struct.unpack(">d", data)[0]

    def read_string(self) -> str:
        length = self.read_ushort()
        if length == 0:
            return ""
        data = self.stream.read(length)
        if len(data) < length:
            raise EOFError("Unexpected end of stream")
        return data.decode("utf-8")

    def read_tag(self, tag_type: int) -> Any:
        if tag_type == TAG_END:
            return None
        elif tag_type == TAG_BYTE:
            return self.read_byte()
        elif tag_type == TAG_SHORT:
            return self.read_short()
        elif tag_type == TAG_INT:
            return self.read_int()
        elif tag_type == TAG_LONG:
            return self.read_long()
        elif tag_type == TAG_FLOAT:
            return self.read_float()
        elif tag_type == TAG_DOUBLE:
            return self.read_double()
        elif tag_type == TAG_BYTE_ARRAY:
            length = self.read_int()
            return [self.read_byte() for _ in range(length)]
        elif tag_type == TAG_STRING:
            return self.read_string()
        elif tag_type == TAG_LIST:
            list_type = self.read_ubyte()
            length = self.read_int()
            return [self.read_tag(list_type) for _ in range(length)]
        elif tag_type == TAG_COMPOUND:
            return self.read_compound()
        elif tag_type == TAG_INT_ARRAY:
            length = self.read_int()
            return [self.read_int() for _ in range(length)]
        else:
            raise ValueError(f"Unknown tag type: {tag_type}")

    def read_compound(self) -> dict:
        result = {}
        while True:
            tag_type = self.read_ubyte()
            if tag_type == TAG_END:
                break
            name = self.read_string()
            value = self.read_tag(tag_type)
            result[name] = value
        return result

    def read_root(self) -> dict:
        tag_type = self.read_ubyte()
        if tag_type != TAG_COMPOUND:
            raise ValueError(f"Expected compound tag at root, got {tag_type}")
        _ = self.read_string()
        return self.read_compound()


def get_world_version(level_dat_path: str) -> dict:
    """
    Extract MC version from level.dat.

    Args:
        level_dat_path: Path to the level.dat file

    Returns:
        {
            "version": "1.21.11",  # or None if not found
            "snapshot": False,
            "raw_version": int or None  # internal version number if available
        }
    """
    result = {
        "version": None,
        "snapshot": False,
        "raw_version": None,
    }

    path = Path(level_dat_path)
    if not path.exists():
        return result

    try:
        with gzip.open(path, "rb") as f:
            reader = NBTReader(f)
            nbt_data = reader.read_root()

        data = nbt_data.get("Data", {})
        if not isinstance(data, dict):
            return result

        version_data = data.get("Version", {})
        if isinstance(version_data, dict):
            name = version_data.get("Name")
            if isinstance(name, str):
                result["version"] = name

            snapshot = version_data.get("Snapshot")
            if isinstance(snapshot, bool):
                result["snapshot"] = snapshot
            elif isinstance(snapshot, int):
                result["snapshot"] = snapshot != 0

            raw_version = version_data.get("Id")
            if isinstance(raw_version, int):
                result["raw_version"] = raw_version

        if result["version"] is None:
            version = data.get("Version")
            if isinstance(version, int):
                result["raw_version"] = version
            elif isinstance(version, str):
                result["version"] = version

        return result

    except (gzip.BadGzipFile, struct.error, EOFError, ValueError, UnicodeDecodeError, OSError):
        return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        result = get_world_version(sys.argv[1])
        print(f"Version: {result['version']}")
        print(f"Snapshot: {result['snapshot']}")
        print(f"Raw Version: {result['raw_version']}")
    else:
        print("Usage: python nbt_parser.py <path_to_level.dat>")
