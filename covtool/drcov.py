#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
A pure-Python, self-contained library for parsing and writing DrCov coverage files.

This library provides a complete implementation for reading and writing DrCov
files, supporting format version 2 with module table versions 2-4 and legacy
module tables. It is designed to be a portable and easy-to-use tool for
developers working with coverage data from DynamoRIO, Frida, or other DBI tools.

The design is heavily inspired by the C++ header-only library `drcov.hpp`.

References:
 - DrCov format analysis: https://www.ayrx.me/drcov-file-format/
 - Lighthouse plugin: https://github.com/gaasedelen/lighthouse

Example Usage:
    # Reading a file
    try:
        coverage = drcov.read("coverage.drcov")
        print(f"Read {len(coverage.basic_blocks)} basic blocks.")
    except drcov.DrCovError as e:
        print(f"Error reading file: {e}")

    # Creating coverage data
    builder = drcov.builder()
    builder.set_flavor("my_python_tool")
    builder.set_module_version(drcov.ModuleTableVersion.V2)
    builder.add_module(path="/bin/program", base=0x400000, end=0x450000)
    builder.add_module(path="/lib/libc.so", base=0x7fff00000000, end=0x7fff00100000)
    builder.add_coverage(module_id=0, offset=0x1000, size=32)
    new_coverage = builder.build()

    # Writing to a file
    drcov.write(new_coverage, "output.drcov")
"""

import argparse
import dataclasses
import io
import struct
import sys
from enum import Enum
from typing import BinaryIO, Dict, List, Optional, TextIO, Tuple, Type, TypeVar, Union

# --- Constants ---
_SUPPORTED_FILE_VERSION = 2
_BB_ENTRY_SIZE = 8
_HIT_COUNT_ENTRY_SIZE = 4
_VERSION_PREFIX = "DRCOV VERSION: "
_FLAVOR_PREFIX = "DRCOV FLAVOR: "
_MODULE_TABLE_PREFIX = "Module Table: "
_BB_TABLE_PREFIX = "BB Table: "
_HIT_COUNT_TABLE_PREFIX = "Hit Count Table: "
_COLUMNS_PREFIX = "Columns: "

# Flavor constants
_FLAVOR_STANDARD = "drcov"
_FLAVOR_WITH_HITS = "drcov-hits"

# --- Public API ---


class DrCovError(Exception):
    """Custom exception for DrCov parsing or writing errors."""

    pass


class ModuleTableVersion(Enum):
    """Module table format versions."""

    LEGACY = 1
    V2 = 2
    V3 = 3
    V4 = 4


@dataclasses.dataclass
class FileHeader:
    """DrCov file header containing version and tool information."""

    version: int = _SUPPORTED_FILE_VERSION
    flavor: str = _FLAVOR_STANDARD

    def to_string(self) -> str:
        """Serializes the header to its string representation."""
        return f"{_VERSION_PREFIX}{self.version}\n" f"{_FLAVOR_PREFIX}{self.flavor}\n"

    def supports_hit_counts(self) -> bool:
        """Returns True if this header indicates hit count support."""
        return self.flavor == _FLAVOR_WITH_HITS


@dataclasses.dataclass
class ModuleEntry:
    """Represents a loaded module/library in the traced process."""

    id: int
    base: int
    end: int
    path: str
    entry: int = 0
    containing_id: Optional[int] = None
    offset: Optional[int] = None
    checksum: Optional[int] = None
    timestamp: Optional[int] = None

    @property
    def size(self) -> int:
        """Returns the size of the module in memory."""
        return self.end - self.base

    def contains_address(self, addr: int) -> bool:
        """Checks if a given absolute address is within this module."""
        return self.base <= addr < self.end


@dataclasses.dataclass(frozen=True)
class BasicBlock:
    """Represents an executed basic block."""

    start: int  # uint32: offset from module base
    size: int  # uint16: size of the basic block
    module_id: int  # uint16: ID of the module containing this block

    def absolute_address(self, module: ModuleEntry) -> int:
        """Calculates the absolute memory address of the basic block."""
        if self.module_id != module.id:
            raise ValueError("Mismatched module ID for basic block.")
        return module.base + self.start


@dataclasses.dataclass
class CoverageData:
    """Complete coverage data structure."""

    header: FileHeader
    modules: List[ModuleEntry]
    basic_blocks: List[BasicBlock]
    module_version: ModuleTableVersion
    hit_counts: Optional[List[int]] = None  # Parallel array to basic_blocks

    def find_module(self, module_id: int) -> Optional[ModuleEntry]:
        """Finds a module by its ID."""
        # Fast path for sequential IDs
        if module_id < len(self.modules) and self.modules[module_id].id == module_id:
            return self.modules[module_id]
        # Slow path for non-sequential or gapped IDs
        return next((m for m in self.modules if m.id == module_id), None)

    def find_module_by_address(self, addr: int) -> Optional[ModuleEntry]:
        """Finds the module that contains a given absolute address."""
        return next((m for m in self.modules if m.contains_address(addr)), None)

    def get_coverage_stats(self) -> Dict[int, int]:
        """Calculates the number of basic blocks executed per module."""
        stats: Dict[int, int] = {m.id: 0 for m in self.modules}
        for bb in self.basic_blocks:
            if bb.module_id in stats:
                stats[bb.module_id] += 1
        return stats

    def validate(self, permissive: bool = False) -> None:
        """
        Validates the integrity of the coverage data.
        Raises DrCovError on failure unless permissive=True.
        In permissive mode, invalid blocks are filtered out and warnings are printed.
        """
        module_ids = {m.id for m in self.modules}
        if len(module_ids) != len(self.modules):
            if permissive:
                print("Warning: Duplicate module IDs found in module table.")
            else:
                raise DrCovError("Duplicate module IDs found in module table.")

        for i, module in enumerate(self.modules):
            if module.id != i:
                # This is a strong assumption from the reference C++ implementation.
                # It simplifies lookups but might be too strict for some drcov files.
                # For compatibility with the reference lib, we'll enforce it.
                if permissive:
                    print(f"Warning: Non-sequential module ID {module.id} at index {i}")

        # Filter out invalid basic blocks in permissive mode
        invalid_blocks = []
        for bb in self.basic_blocks:
            if bb.module_id not in module_ids:
                if permissive:
                    invalid_blocks.append(bb)
                else:
                    raise DrCovError(
                        f"Basic block references invalid module ID: {bb.module_id}"
                    )
        
        if permissive and invalid_blocks:
            print(f"Warning: Filtering out {len(invalid_blocks)} basic blocks with invalid module IDs")
            valid_indices = [
                i for i, bb in enumerate(self.basic_blocks) if bb.module_id in module_ids
            ]
            self.basic_blocks = [self.basic_blocks[i] for i in valid_indices]
            if self.hit_counts:
                self.hit_counts = [self.hit_counts[i] for i in valid_indices]

        # Validate hit counts if present
        if self.hit_counts is not None:
            if len(self.hit_counts) != len(self.basic_blocks):
                if permissive:
                    print(
                        f"Warning: Hit count array length ({len(self.hit_counts)}) "
                        f"does not match basic block count ({len(self.basic_blocks)})"
                    )
                    if len(self.hit_counts) > len(self.basic_blocks):
                        self.hit_counts = self.hit_counts[: len(self.basic_blocks)]
                    else:
                        missing = len(self.basic_blocks) - len(self.hit_counts)
                        self.hit_counts.extend([1] * missing)
                else:
                    raise DrCovError(
                        f"Hit count array length ({len(self.hit_counts)}) "
                        f"does not match basic block count ({len(self.basic_blocks)})"
                    )

    def has_hit_counts(self) -> bool:
        """Returns True if hit count data is available."""
        return self.hit_counts is not None

    def get_hit_count(self, block_index: int) -> int:
        """Gets the hit count for a basic block by index. Returns 1 if no hit counts."""
        if self.hit_counts and 0 <= block_index < len(self.hit_counts):
            return self.hit_counts[block_index]
        return 1

    def get_blocks_with_hits(self) -> List[Tuple[BasicBlock, int]]:
        """Returns a list of (BasicBlock, hit_count) tuples."""
        if self.hit_counts:
            return list(zip(self.basic_blocks, self.hit_counts))
        return [(block, 1) for block in self.basic_blocks]


class CoverageBuilder:
    """Builder pattern for fluently creating CoverageData objects."""

    def __init__(self):
        self._data = CoverageData(
            header=FileHeader(),
            modules=[],
            basic_blocks=[],
            module_version=ModuleTableVersion.V2,
        )

    def set_flavor(self, flavor: str) -> "CoverageBuilder":
        """Sets the 'flavor' (tool name) in the header."""
        self._data.header.flavor = flavor
        return self

    def set_module_version(self, version: ModuleTableVersion) -> "CoverageBuilder":
        """Sets the version of the module table format."""
        self._data.module_version = version
        return self

    def add_module(
        self, path: str, base: int, end: int, entry: int = 0
    ) -> "CoverageBuilder":
        """Adds a new module, assigning the next sequential ID."""
        module_id = len(self._data.modules)
        self._data.modules.append(
            ModuleEntry(id=module_id, path=path, base=base, end=end, entry=entry)
        )
        return self

    def add_coverage(
        self, module_id: int, offset: int, size: int, hit_count: int = 1
    ) -> "CoverageBuilder":
        """Adds a new basic block to the coverage data."""
        self._data.basic_blocks.append(
            BasicBlock(start=offset, size=size, module_id=module_id)
        )

        # Initialize hit counts list if this is the first block with non-default hit count
        if self._data.hit_counts is None and hit_count != 1:
            self._data.hit_counts = [1] * (len(self._data.basic_blocks) - 1)

        if self._data.hit_counts is not None:
            self._data.hit_counts.append(hit_count)

        return self

    def add_basic_blocks(self, blocks: List[BasicBlock]) -> "CoverageBuilder":
        """Adds a list of basic blocks."""
        self._data.basic_blocks.extend(blocks)
        return self

    def clear_coverage(self) -> "CoverageBuilder":
        """Removes all basic blocks."""
        self._data.basic_blocks.clear()
        self._data.hit_counts = None
        return self

    def set_hit_counts(self, hit_counts: List[int]) -> "CoverageBuilder":
        """Sets hit counts for all basic blocks. Must match basic block count."""
        if len(hit_counts) != len(self._data.basic_blocks):
            raise ValueError(
                f"Hit count array length ({len(hit_counts)}) "
                f"must match basic block count ({len(self._data.basic_blocks)})"
            )
        self._data.hit_counts = hit_counts[:]
        # Update flavor to indicate hit count support
        self._data.header.flavor = _FLAVOR_WITH_HITS
        return self

    def enable_hit_counts(self) -> "CoverageBuilder":
        """Enables hit count tracking with default counts of 1."""
        if self._data.hit_counts is None:
            self._data.hit_counts = [1] * len(self._data.basic_blocks)
            self._data.header.flavor = _FLAVOR_WITH_HITS
        return self

    def data(self) -> CoverageData:
        """Returns the internal data object."""
        return self._data

    def build(self) -> CoverageData:
        """Validates and returns the final CoverageData object."""
        self._data.validate()
        return self._data


# --- Parser Implementation ---


class _Parser:
    @staticmethod
    def parse_stream(stream: TextIO, permissive: bool = False) -> CoverageData:
        header = _Parser._parse_header(stream)
        if header.version != _SUPPORTED_FILE_VERSION:
            raise DrCovError(
                f"Unsupported DrCov version: {header.version}. Only version 2 is supported."
            )

        modules, module_version = _Parser._parse_module_table(stream)
        
        # Read the BB table header as text first
        bb_line = stream.readline().strip()
        if not bb_line.startswith(_BB_TABLE_PREFIX):
            # No BB table or empty
            basic_blocks = []
        else:
            try:
                count_str = bb_line[len(_BB_TABLE_PREFIX):].split(' ')[0]
                count = int(count_str)
            except (ValueError, IndexError) as e:
                raise DrCovError(f"Malformed BB table count: {e}")
            
            if count == 0:
                basic_blocks = []
            else:
                # Now switch to binary mode for the binary data
                binary_stream = stream.buffer
                binary_data = binary_stream.read(count * _BB_ENTRY_SIZE)
                if len(binary_data) != count * _BB_ENTRY_SIZE:
                    raise DrCovError("Failed to read complete BB table binary data.")
                
                basic_blocks = []
                for i in range(count):
                    offset = i * _BB_ENTRY_SIZE
                    entry_data = binary_data[offset : offset + _BB_ENTRY_SIZE]
                    start, size, mod_id = struct.unpack("<IHH", entry_data)
                    basic_blocks.append(BasicBlock(start, size, mod_id))

        # Try to read hit count table if present
        hit_counts = None
        try:
            hit_counts = _Parser._parse_hit_count_table(stream, len(basic_blocks))
        except (DrCovError, EOFError):
            # No hit count table found, which is fine for backward compatibility
            pass

        data = CoverageData(header, modules, basic_blocks, module_version, hit_counts)
        data.validate(permissive=permissive)
        return data

    @staticmethod
    def _parse_header(stream: TextIO) -> FileHeader:
        try:
            version_line = stream.readline()
            if not version_line.startswith(_VERSION_PREFIX):
                raise DrCovError("Invalid or missing version header.")
            version = int(version_line[len(_VERSION_PREFIX) :].strip())

            flavor_line = stream.readline()
            if not flavor_line.startswith(_FLAVOR_PREFIX):
                raise DrCovError("Invalid or missing flavor header.")
            flavor = flavor_line[len(_FLAVOR_PREFIX) :].strip()

            # Consume the blank line after the header (if present)
            pos = stream.tell()
            blank_line = stream.readline()
            if blank_line.strip():  # If it's not blank, rewind
                stream.seek(pos)

            return FileHeader(version, flavor)
        except (ValueError, IndexError) as e:
            raise DrCovError(f"Failed to parse header: {e}")

    @staticmethod
    def _parse_module_table(
        stream: TextIO,
    ) -> Tuple[List[ModuleEntry], ModuleTableVersion]:
        line = stream.readline().strip()
        if not line.startswith(_MODULE_TABLE_PREFIX):
            raise DrCovError("Invalid or missing module table header.")

        content = line[len(_MODULE_TABLE_PREFIX) :]
        if "version" in content:
            parts = [p.strip() for p in content.split(",")]
            version_str = parts[0].split(" ")[1]
            count_str = parts[1].split(" ")[1]
            version = ModuleTableVersion(int(version_str))
            count = int(count_str)
            columns_line = stream.readline().strip()
            if not columns_line.startswith(_COLUMNS_PREFIX):
                raise DrCovError("Invalid or missing columns header.")
            columns = [
                c.strip() for c in columns_line[len(_COLUMNS_PREFIX) :].split(",")
            ]
        else:  # Legacy format
            version = ModuleTableVersion.LEGACY
            count = int(content)
            columns = ["id", "base", "end", "entry", "path"]

        modules: List[ModuleEntry] = []
        for i in range(count):
            entry_line = stream.readline().strip()
            if not entry_line:
                raise DrCovError(
                    f"Module table entry count mismatch. Expected {count}, got {i}."
                )

            values = [
                v.strip() for v in entry_line.split(",", maxsplit=len(columns) - 1)
            ]
            if len(values) != len(columns):
                raise DrCovError(
                    f"Module entry column count mismatch on line: {entry_line}"
                )

            col_map = dict(zip(columns, values))
            try:
                entry = ModuleEntry(
                    id=int(col_map["id"]),
                    base=int(col_map.get("base") or col_map.get("start", "0"), 16),
                    end=int(col_map["end"], 16),
                    path=col_map["path"],
                    entry=int(col_map.get("entry", "0"), 16),
                    containing_id=(
                        int(col_map["containing_id"])
                        if "containing_id" in col_map
                        else None
                    ),
                    offset=int(col_map["offset"], 16) if "offset" in col_map else None,
                    checksum=(
                        int(col_map["checksum"], 16) if "checksum" in col_map else None
                    ),
                    timestamp=(
                        int(col_map["timestamp"], 16)
                        if "timestamp" in col_map
                        else None
                    ),
                )
                modules.append(entry)
            except (ValueError, KeyError) as e:
                raise DrCovError(f"Malformed module entry '{entry_line}': {e}")

        # Consume the blank line after the module table
        stream.readline()

        return modules, version

    @staticmethod
    def _parse_hit_count_table(stream: Union[TextIO, str], expected_count: int) -> List[int]:
        """Parse hit count table. Returns list of hit counts or raises DrCovError if not found."""
        try:
            # Handle both TextIO streams and string content
            if isinstance(stream, str):
                lines = stream.split('\n')
                if not lines or not lines[0].strip():
                    raise DrCovError("No hit count table found")
                hit_line = lines[0].strip()
                remaining_content = '\n'.join(lines[1:]) if len(lines) > 1 else ""
            else:
                hit_line = stream.readline().strip()
                if not hit_line:
                    raise DrCovError("No hit count table found")
                remaining_content = stream.read()
            
            if not hit_line.startswith(_HIT_COUNT_TABLE_PREFIX):
                raise DrCovError("Invalid hit count table header")
            
            # Parse header: "Hit Count Table: version 1, count <N>"
            header_parts = hit_line[len(_HIT_COUNT_TABLE_PREFIX):].strip().split(',')
            if len(header_parts) != 2:
                raise DrCovError("Malformed hit count table header")
            
            version_part = header_parts[0].strip()
            count_part = header_parts[1].strip()
            
            if not version_part.startswith("version "):
                raise DrCovError("Missing version in hit count table header")
            
            version = int(version_part[8:])  # Skip "version "
            if version != 1:
                raise DrCovError(f"Unsupported hit count table version: {version}")
            
            if not count_part.startswith("count "):
                raise DrCovError("Missing count in hit count table header")
            
            count = int(count_part[6:])  # Skip "count "
            if count != expected_count:
                raise DrCovError(
                    f"Hit count table count ({count}) does not match basic block count ({expected_count})"
                )
            
            if count == 0:
                return []
            
            # Read binary hit count data - handle different stream types
            if isinstance(stream, str) or not hasattr(stream, 'buffer'):
                # For string content or StringIO, we need the binary data as bytes
                binary_data = remaining_content.encode('latin1')[:count * _HIT_COUNT_ENTRY_SIZE]
            else:
                # For real file streams with buffer
                binary_stream = stream.buffer
                binary_data = binary_stream.read(count * _HIT_COUNT_ENTRY_SIZE)
                
            if len(binary_data) != count * _HIT_COUNT_ENTRY_SIZE:
                raise DrCovError("Failed to read complete hit count table binary data")
            
            hit_counts = []
            for i in range(count):
                offset = i * _HIT_COUNT_ENTRY_SIZE
                entry_data = binary_data[offset : offset + _HIT_COUNT_ENTRY_SIZE]
                hit_count = struct.unpack("<I", entry_data)[0]
                hit_counts.append(hit_count)
            
            return hit_counts
        
        except (ValueError, struct.error) as e:
            raise DrCovError(f"Error parsing hit count table: {e}")

    @staticmethod
    def _parse_hit_count_table_from_binary(data: bytes, expected_count: int) -> List[int]:
        """Parse hit count table from raw binary data with text header."""
        try:
            text_part = data.decode("utf-8", errors="ignore")
            lines = text_part.split("\n")

            # Find the header line
            header_line = None
            header_end_pos = 0
            for i, line in enumerate(lines):
                if line.strip().startswith(_HIT_COUNT_TABLE_PREFIX):
                    header_line = line.strip()
                    header_end_pos = len("\n".join(lines[: i + 1]).encode("utf-8")) + 1
                    break

            if not header_line:
                raise DrCovError("Hit count table header not found")

            # Parse header: "Hit Count Table: version 1, count <N>"
            header_suffix = header_line[len(_HIT_COUNT_TABLE_PREFIX) :].strip()
            parts = header_suffix.split(",")
            if len(parts) != 2 or not parts[1].strip().startswith("count "):
                raise DrCovError("Malformed hit count table header")

            count = int(parts[1].strip()[6:])  # Skip "count "
            if count != expected_count:
                raise DrCovError(
                    f"Hit count table count ({count}) does not match "
                    f"basic block count ({expected_count})"
                )

            if count == 0:
                return []

            # Extract binary data
            binary_start = header_end_pos
            binary_end = binary_start + count * _HIT_COUNT_ENTRY_SIZE
            binary_data = data[binary_start:binary_end]

            if len(binary_data) != count * _HIT_COUNT_ENTRY_SIZE:
                raise DrCovError("Failed to read complete hit count table binary data")

            hit_counts = []
            for i in range(count):
                offset = i * _HIT_COUNT_ENTRY_SIZE
                entry_data = binary_data[offset : offset + _HIT_COUNT_ENTRY_SIZE]
                hit_count = struct.unpack("<I", entry_data)[0]
                hit_counts.append(hit_count)

            return hit_counts

        except (ValueError, struct.error, UnicodeDecodeError) as e:
            raise DrCovError(f"Error parsing hit count table from binary: {e}")

    @staticmethod
    def parse_text_only(stream: TextIO, permissive: bool = False) -> CoverageData:
        """Parse a drcov file that has no BB table."""
        header = _Parser._parse_header(stream)
        if header.version != _SUPPORTED_FILE_VERSION:
            raise DrCovError(
                f"Unsupported DrCov version: {header.version}. Only version 2 is supported."
            )

        modules, module_version = _Parser._parse_module_table(stream)
        basic_blocks = []  # No BB table

        data = CoverageData(header, modules, basic_blocks, module_version, None)
        data.validate(permissive=permissive)
        return data

    @staticmethod
    def parse_with_binary(text_stream: TextIO, bb_stream: BinaryIO, permissive: bool = False) -> CoverageData:
        """Parse a drcov file by splitting text and binary parts."""
        header = _Parser._parse_header(text_stream)
        if header.version != _SUPPORTED_FILE_VERSION:
            raise DrCovError(
                f"Unsupported DrCov version: {header.version}. Only version 2 is supported."
            )

        modules, module_version = _Parser._parse_module_table(text_stream)
        
        # Parse BB table from binary stream
        line_bytes = bb_stream.readline()
        if not line_bytes:
            basic_blocks = []
        else:
            line = line_bytes.decode("utf-8", errors="ignore").strip()
            if not line.startswith(_BB_TABLE_PREFIX):
                raise DrCovError("Invalid or missing BB table header.")

            try:
                count_str = line[len(_BB_TABLE_PREFIX):].split(' ')[0]
                count = int(count_str)
            except (ValueError, IndexError) as e:
                raise DrCovError(f"Malformed BB table count: {e}")

            if count == 0:
                basic_blocks = []
            else:
                binary_data = bb_stream.read(count * _BB_ENTRY_SIZE)
                if len(binary_data) != count * _BB_ENTRY_SIZE:
                    raise DrCovError("Failed to read complete BB table binary data.")

                basic_blocks = []
                for i in range(count):
                    offset = i * _BB_ENTRY_SIZE
                    entry_data = binary_data[offset : offset + _BB_ENTRY_SIZE]
                    start, size, mod_id = struct.unpack("<IHH", entry_data)
                    basic_blocks.append(BasicBlock(start, size, mod_id))

        # Try to read hit count table from the remaining binary stream
        hit_counts = None
        try:
            # Check if there's more data in the binary stream
            remaining_data = bb_stream.read()
            if remaining_data:
                # Look for hit count table header in the remaining data
                try:
                    text_part = remaining_data.decode("utf-8", errors="ignore")
                    if _HIT_COUNT_TABLE_PREFIX in text_part:
                        # Parse the hit count table from binary data
                        hit_counts = _Parser._parse_hit_count_table_from_binary(
                            remaining_data, len(basic_blocks)
                        )
                except UnicodeDecodeError:
                    pass
        except Exception:
            # No hit count table found, which is fine for backward compatibility
            pass

        data = CoverageData(header, modules, basic_blocks, module_version, hit_counts)
        data.validate(permissive=permissive)
        return data



# --- Writer Implementation ---


class _Writer:
    @staticmethod
    def write_stream(data: CoverageData, stream: Union[TextIO, BinaryIO]):
        data.validate()

        # Determine if we need to write text or bytes
        is_binary_stream = isinstance(stream, io.BufferedIOBase)

        def write_str(s: str):
            if is_binary_stream:
                stream.write(s.encode("utf-8"))
            else:
                stream.write(s)

        write_str(data.header.to_string())
        write_str("\n")

        _Writer._write_module_table(data, write_str)
        write_str("\n")

        # For BB table, we must write to a binary stream
        if not is_binary_stream:
            # If original stream is text, get its underlying buffer
            if hasattr(stream, "buffer"):
                binary_stream = stream.buffer
            else:
                raise DrCovError(
                    "Cannot write binary BB table to a non-binary text stream without a buffer."
                )
        else:
            binary_stream = stream

        _Writer._write_bb_table(data.basic_blocks, binary_stream)
        
        # Write hit count table if present
        if data.hit_counts is not None:
            _Writer._write_hit_count_table(data.hit_counts, binary_stream)

    @staticmethod
    def _get_columns_string(data: CoverageData) -> str:
        has_windows_fields = any(
            m.checksum is not None or m.timestamp is not None for m in data.modules
        )

        if data.module_version == ModuleTableVersion.V2:
            return (
                "id, base, end, entry, checksum, timestamp, path"
                if has_windows_fields
                else "id, base, end, entry, path"
            )
        if data.module_version == ModuleTableVersion.V3:
            return (
                "id, containing_id, start, end, entry, checksum, timestamp, path"
                if has_windows_fields
                else "id, containing_id, start, end, entry, path"
            )
        if data.module_version == ModuleTableVersion.V4:
            return (
                "id, containing_id, start, end, entry, offset, checksum, timestamp, path"
                if has_windows_fields
                else "id, containing_id, start, end, entry, offset, path"
            )

        # Legacy or default
        return "id, base, end, entry, path"

    @staticmethod
    def _write_module_table(data: CoverageData, write_str: callable):
        if data.module_version == ModuleTableVersion.LEGACY:
            write_str(f"{_MODULE_TABLE_PREFIX}{len(data.modules)}\n")
            columns = ["id", "base", "end", "entry", "path"]
        else:
            write_str(
                f"{_MODULE_TABLE_PREFIX}version {data.module_version.value}, count {len(data.modules)}\n"
            )
            columns_str = _Writer._get_columns_string(data)
            write_str(f"{_COLUMNS_PREFIX}{columns_str}\n")
            columns = [c.strip() for c in columns_str.split(",")]

        for mod in data.modules:
            parts = []
            for col in columns:
                if col == "id":
                    parts.append(str(mod.id))
                elif col in ("base", "start"):
                    parts.append(f"0x{mod.base:x}")
                elif col == "end":
                    parts.append(f"0x{mod.end:x}")
                elif col == "entry":
                    parts.append(f"0x{mod.entry:x}")
                elif col == "path":
                    parts.append(mod.path)
                elif col == "containing_id":
                    parts.append(str(mod.containing_id or -1))
                elif col == "offset":
                    parts.append(f"0x{mod.offset or 0:x}")
                elif col == "checksum":
                    parts.append(f"0x{mod.checksum or 0:x}")
                elif col == "timestamp":
                    parts.append(f"0x{mod.timestamp or 0:x}")
            write_str(", ".join(parts) + "\n")

    @staticmethod
    def _write_bb_table(blocks: List[BasicBlock], stream: BinaryIO):
        header = f"{_BB_TABLE_PREFIX}{len(blocks)} bbs\n"
        stream.write(header.encode("utf-8"))

        if not blocks:
            return

        packed_data = b"".join(
            struct.pack("<IHH", bb.start, bb.size, bb.module_id) for bb in blocks
        )
        stream.write(packed_data)

    @staticmethod
    def _write_hit_count_table(hit_counts: List[int], stream: BinaryIO):
        """Write hit count table to stream."""
        header = f"{_HIT_COUNT_TABLE_PREFIX}version 1, count {len(hit_counts)}\n"
        stream.write(header.encode("utf-8"))

        if not hit_counts:
            return

        packed_data = b"".join(struct.pack("<I", count) for count in hit_counts)
        stream.write(packed_data)


# --- Public API Functions ---

T = TypeVar("T")


def read(filepath_or_stream: Union[str, TextIO], permissive: bool = False) -> CoverageData:
    """
    Reads and parses a DrCov file from a path or a text stream.

    Args:
        filepath_or_stream: Path to the .drcov file or a stream opened in text mode.
        permissive: If True, warnings are printed for invalid data but parsing continues.

    Returns:
        A CoverageData object.

    Raises:
        DrCovError: If parsing fails.
        FileNotFoundError: If the file path does not exist.
    """
    if isinstance(filepath_or_stream, str):
        # Read the entire file as binary, then parse
        with open(filepath_or_stream, "rb") as f:
            binary_data = f.read()
        
        # Find the split point between text and binary parts
        bb_table_start = binary_data.find(b"BB Table:")
        if bb_table_start == -1:
            # No BB table, parse as text only
            text_data = binary_data.decode("utf-8", errors="ignore")
            from io import StringIO
            return _Parser.parse_text_only(StringIO(text_data), permissive=permissive)
        else:
            # Split at BB table
            text_part = binary_data[:bb_table_start].decode("utf-8", errors="ignore")
            bb_part = binary_data[bb_table_start:]
            
            from io import StringIO, BytesIO
            text_stream = StringIO(text_part)
            bb_stream = BytesIO(bb_part)
            
            return _Parser.parse_with_binary(text_stream, bb_stream, permissive=permissive)
    else:
        return _Parser.parse_stream(filepath_or_stream, permissive=permissive)


def write(data: CoverageData, filepath_or_stream: Union[str, BinaryIO]):
    """
    Writes coverage data to a .drcov file.

    Args:
        data: The CoverageData object to write.
        filepath_or_stream: Path to the output file or a stream opened in binary mode.

    Raises:
        DrCovError: If writing fails.
    """
    if isinstance(filepath_or_stream, str):
        with open(filepath_or_stream, "wb") as f:
            _Writer.write_stream(data, f)
    else:
        _Writer.write_stream(data, filepath_or_stream)


def builder() -> CoverageBuilder:
    """Returns a new CoverageBuilder instance for creating CoverageData."""
    return CoverageBuilder()


# --- Command-Line Tool ---


def _run_analyzer(args: argparse.Namespace):
    """The main logic for the command-line tool."""
    print(f"Analyzing DrCov file: {args.file}\n")

    try:
        coverage_data = read(args.file)
    except FileNotFoundError:
        print(f"Error: File not found at '{args.file}'", file=sys.stderr)
        sys.exit(1)
    except DrCovError as e:
        print(f"Error parsing DrCov file: {e}", file=sys.stderr)
        sys.exit(1)

    # --- Print Header and Summary ---
    print("=== DrCov File Analysis ===")
    print(f"File:                 {args.file}")
    print(f"Version:              {coverage_data.header.version}")
    print(f"Flavor:               {coverage_data.header.flavor}")
    print(f"Module Table Version: {coverage_data.module_version.value}\n")

    print("=== Summary ===")
    print(f"Total Modules:        {len(coverage_data.modules)}")
    print(f"Total Basic Blocks:   {len(coverage_data.basic_blocks)}")

    total_coverage_bytes = sum(bb.size for bb in coverage_data.basic_blocks)
    print(f"Total Coverage:       {total_coverage_bytes} bytes\n")

    # --- Print Module Coverage Summary ---
    stats = coverage_data.get_coverage_stats()
    print("=== Module Coverage ===")
    print(f"{'ID':<4} {'Blocks':<8} {'Size':<12} {'Base Address':<20} {'Name'}")
    print("-" * 80)

    for module in coverage_data.modules:
        block_count = stats.get(module.id, 0)
        module_bytes = sum(
            bb.size for bb in coverage_data.basic_blocks if bb.module_id == module.id
        )

        print(
            f"{module.id:<4} "
            f"{block_count:<8} "
            f"{f'{module_bytes} bytes':<12} "
            f"{f'0x{module.base:x}':<20} "
            f"{module.path}"
        )
    print("")

    # --- Detailed Basic Block View ---
    if args.detailed:
        print("=== Detailed Basic Blocks ===")
        print(
            f"{'Module':<8} {'Offset':<14} {'Size':<8} {'Absolute Address':<18} {'Module Name'}"
        )
        print("-" * 80)

        for bb in coverage_data.basic_blocks:
            module = coverage_data.find_module(bb.module_id)
            if module:
                abs_addr = bb.absolute_address(module)
                print(
                    f"{bb.module_id:<8} "
                    f"{f'0x{bb.start:x}':<14} "
                    f"{bb.size:<8} "
                    f"{f'0x{abs_addr:x}':<18} "
                    f"{module.path}"
                )
        print("")

    # --- Module-Specific Analysis ---
    if args.module:
        print(f"=== Module-Specific Analysis: '{args.module}' ===")
        found = False
        for module in coverage_data.modules:
            if args.module.lower() in module.path.lower():
                found = True
                block_count = stats.get(module.id, 0)
                module_bytes = sum(
                    bb.size
                    for bb in coverage_data.basic_blocks
                    if bb.module_id == module.id
                )

                print(f"Module ID:      {module.id}")
                print(f"Name:           {module.path}")
                print(f"Base:           0x{module.base:x}")
                print(f"End:            0x{module.end:x}")
                print(f"Size:           {module.size} bytes")
                print(f"Covered Blocks: {block_count}")
                print(f"Covered Bytes:  {module_bytes}\n")

        if not found:
            print(f"No modules found matching filter: '{args.module}'")


def main():
    """Entry point for the command-line script."""
    parser = argparse.ArgumentParser(
        description="Analyze DrCov code coverage files.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Example:
  # Perform a summary analysis of a drcov file
  python drcov.py coverage.log

  # Show detailed basic block information
  python drcov.py coverage.log --detailed

  # Filter analysis to modules containing 'program' in their path
  python drcov.py coverage.log --module program
""",
    )
    parser.add_argument("file", help="Path to the .drcov file to analyze.")
    parser.add_argument(
        "-d",
        "--detailed",
        action="store_true",
        help="Show detailed information for every executed basic block.",
    )
    parser.add_argument(
        "-m",
        "--module",
        type=str,
        help="Filter analysis for a specific module by a substring of its path (case-insensitive).",
    )

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()
    _run_analyzer(args)


if __name__ == "__main__":
    main()
