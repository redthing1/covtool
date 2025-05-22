"""drcov format parser and writer"""

import struct
from typing import List, Set, Union
from pathlib import Path

from .core import BasicBlock, Module, CoverageSet


class DrcovFormat:
    """
    handles parsing and writing of drcov files
    abstracts away format details and version differences
    """

    @staticmethod
    def read(filepath: Union[str, Path]) -> CoverageSet:
        """parse a drcov file and return a CoverageSet"""
        filepath = Path(filepath)

        with open(filepath, "rb") as f:
            data = f.read()

        # split header and basic block data
        bb_table_marker = b"BB Table:"
        header_end = data.find(bb_table_marker)
        if header_end == -1:
            raise ValueError(f"invalid drcov file: {filepath}")

        header = data[:header_end].decode("utf-8", errors="replace")
        bb_data_start = data.find(b"\n", header_end) + 1

        # parse components
        modules = DrcovFormat._parse_modules(header)
        blocks = DrcovFormat._parse_blocks(data[bb_data_start:], header)

        return CoverageSet(blocks, modules)

    @staticmethod
    def write(coverage: CoverageSet, filepath: Union[str, Path], version: int = 2):
        """write a CoverageSet to a drcov file"""
        filepath = Path(filepath)

        with open(filepath, "wb") as f:
            # write header
            f.write(f"DRCOV VERSION: {version}\n".encode())
            f.write(f"DRCOV FLAVOR: drcov\n".encode())

            # write module table
            modules = list(coverage.modules.values())
            f.write(f"Module Table: version {version}, count {len(modules)}\n".encode())
            f.write("Columns: id, base, end, entry, path\n".encode())

            for module in modules:
                line = f"{module.id}, 0x{module.base:x}, 0x{module.end:x}, 0x{module.entry:x}, {module.path}\n"
                f.write(line.encode())

            # write basic block table
            f.write(f"BB Table: {len(coverage.blocks)} bbs\n".encode())

            # write binary block data
            for block in coverage.blocks:
                f.write(struct.pack("<IHH", block.offset, block.size, block.module_id))

    @staticmethod
    def _parse_modules(header: str) -> List[Module]:
        """extract module table from header"""
        lines = header.strip().split("\n")

        # find start of module table
        table_start = None
        for i, line in enumerate(lines):
            if line.startswith("Module Table:"):
                table_start = i + 1
                break

        if table_start is None:
            return []

        # skip columns header if present
        if table_start < len(lines) and lines[table_start].startswith("Columns:"):
            table_start += 1

        modules = []
        for line in lines[table_start:]:
            line = line.strip()
            if not line or line.startswith("BB Table"):
                break

            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 5:
                continue

            try:
                module = Module(
                    id=int(parts[0]),
                    base=(
                        int(parts[1], 16)
                        if parts[1].startswith("0x")
                        else int(parts[1])
                    ),
                    end=(
                        int(parts[2], 16)
                        if parts[2].startswith("0x")
                        else int(parts[2])
                    ),
                    entry=(
                        int(parts[3], 16)
                        if parts[3].startswith("0x")
                        else int(parts[3])
                    ),
                    path=parts[4],
                )
                modules.append(module)
            except (ValueError, IndexError):
                continue

        return modules

    @staticmethod
    def _parse_blocks(bb_data: bytes, header: str) -> Set[BasicBlock]:
        """extract basic blocks from binary data section"""
        # determine if ascii or binary format
        ascii_marker = b"module id, start, size:"
        is_ascii = bb_data.startswith(ascii_marker)

        if is_ascii:
            return DrcovFormat._parse_ascii_blocks(bb_data)
        else:
            return DrcovFormat._parse_binary_blocks(bb_data)

    @staticmethod
    def _parse_binary_blocks(data: bytes) -> Set[BasicBlock]:
        """parse binary format basic blocks (8 bytes each)"""
        blocks = set()

        # each block is: uint32 offset, uint16 size, uint16 module_id
        for i in range(0, len(data) - 7, 8):
            offset, size, mod_id = struct.unpack("<IHH", data[i : i + 8])
            blocks.add(BasicBlock(offset, size, mod_id))

        return blocks

    @staticmethod
    def _parse_ascii_blocks(data: bytes) -> Set[BasicBlock]:
        """parse ascii format basic blocks"""
        blocks = set()
        text = data.decode("utf-8", errors="replace")

        for line in text.split("\n"):
            line = line.strip()
            if not line or not line.startswith("module["):
                continue

            try:
                # parse: "module[  4]: 0x0000000000001090,   8"
                mod_id = int(line[line.find("[") + 1 : line.find("]")])
                after_colon = line[line.find("]:") + 2 :].strip()
                parts = after_colon.split(",")
                offset = int(
                    parts[0].strip(), 16 if parts[0].strip().startswith("0x") else 10
                )
                size = int(parts[1].strip())

                blocks.add(BasicBlock(offset, size, mod_id))
            except (ValueError, IndexError):
                continue

        return blocks