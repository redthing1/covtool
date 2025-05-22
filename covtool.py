#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "typer>=0.15.0",
# ]
# ///

"""
drcov - powerful drcov coverage file analysis and manipulation tool

supports set operations, differential analysis, rarity detection, and more
outputs valid drcov files that work with bncov, lighthouse, and other tools
"""

import os
import sys
import struct
from typing import List, Dict, Set, Tuple, Optional, Union
from dataclasses import dataclass
from collections import defaultdict, Counter
from pathlib import Path

import typer


# =============================================================================
# core data structures
# =============================================================================


@dataclass(frozen=True)
class BasicBlock:
    """represents a single basic block with its coverage info"""

    offset: int  # offset from module base
    size: int  # size in bytes
    module_id: int  # id of containing module

    @property
    def key(self) -> Tuple[int, int]:
        """unique key for this block (offset, module_id)"""
        return (self.offset, self.module_id)


@dataclass
class Module:
    """represents a loaded module in the target process"""

    id: int
    base: int
    end: int
    entry: int
    path: str

    @property
    def name(self) -> str:
        """just the filename portion of the path"""
        return os.path.basename(self.path)

    def contains_address(self, addr: int) -> bool:
        """check if an absolute address falls within this module"""
        return self.base <= addr <= self.end


# =============================================================================
# coverage data abstraction
# =============================================================================


class CoverageSet:
    """
    high-level abstraction for coverage data
    handles set operations, queries, and analysis
    """

    def __init__(self, blocks: Set[BasicBlock] = None, modules: List[Module] = None):
        self.blocks = blocks or set()
        self.modules = {m.id: m for m in (modules or [])}

    def __len__(self) -> int:
        return len(self.blocks)

    def __bool__(self) -> bool:
        return bool(self.blocks)

    def __or__(self, other: "CoverageSet") -> "CoverageSet":
        """union operation: self | other"""
        # merge modules from both sets
        merged_modules = {**self.modules, **other.modules}
        return CoverageSet(self.blocks | other.blocks, list(merged_modules.values()))

    def __and__(self, other: "CoverageSet") -> "CoverageSet":
        """intersection operation: self & other"""
        merged_modules = {**self.modules, **other.modules}
        return CoverageSet(self.blocks & other.blocks, list(merged_modules.values()))

    def __sub__(self, other: "CoverageSet") -> "CoverageSet":
        """difference operation: self - other"""
        return CoverageSet(self.blocks - other.blocks, list(self.modules.values()))

    def __xor__(self, other: "CoverageSet") -> "CoverageSet":
        """symmetric difference: self ^ other"""
        merged_modules = {**self.modules, **other.modules}
        return CoverageSet(self.blocks ^ other.blocks, list(merged_modules.values()))

    def get_absolute_addresses(self) -> Set[int]:
        """convert all blocks to absolute memory addresses"""
        addresses = set()
        for block in self.blocks:
            if block.module_id in self.modules:
                module = self.modules[block.module_id]
                addresses.add(module.base + block.offset)
        return addresses

    def filter_by_module(self, module_filter: str) -> "CoverageSet":
        """return coverage filtered to modules matching the given string"""
        matching_modules = []
        for module in self.modules.values():
            if module_filter.lower() in module.path.lower():
                matching_modules.append(module)

        if not matching_modules:
            return CoverageSet()

        matching_ids = {m.id for m in matching_modules}
        filtered_blocks = {b for b in self.blocks if b.module_id in matching_ids}
        return CoverageSet(filtered_blocks, matching_modules)

    def get_coverage_by_module(self) -> Dict[str, Set[BasicBlock]]:
        """organize coverage by module name"""
        by_module = defaultdict(set)
        for block in self.blocks:
            if block.module_id in self.modules:
                module_name = self.modules[block.module_id].name
                by_module[module_name].add(block)
        return dict(by_module)

    def get_rarity_info(self, all_sets: List["CoverageSet"]) -> Dict[BasicBlock, int]:
        """
        for each block, count how many coverage sets contain it
        useful for finding rare execution paths
        """
        block_counts = Counter()

        for coverage_set in all_sets:
            seen_in_this_set = set()
            for block in coverage_set.blocks:
                if block.key not in seen_in_this_set:
                    block_counts[block] += 1
                    seen_in_this_set.add(block.key)

        return dict(block_counts)


# =============================================================================
# drcov format parser/writer
# =============================================================================


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


# =============================================================================
# analysis functions
# =============================================================================


def load_multiple_coverage(filepaths: List[Path]) -> List[CoverageSet]:
    """load multiple coverage files, handling errors gracefully"""
    results = []
    for path in filepaths:
        try:
            coverage = DrcovFormat.read(path)
            results.append(coverage)
        except Exception as e:
            typer.echo(f"error loading {path}: {e}", err=True)
    return results


def print_coverage_stats(coverage: CoverageSet, name: str = ""):
    """display basic statistics about a coverage set"""
    if name:
        typer.echo(f"{name}:")

    typer.echo(f"  basic blocks: {len(coverage)}")
    typer.echo(f"  modules: {len(coverage.modules)}")

    by_module = coverage.get_coverage_by_module()
    if by_module:
        typer.echo("  coverage by module:")
        for module_name, blocks in sorted(by_module.items()):
            typer.echo(f"    {module_name}: {len(blocks)} blocks")


def print_rarity_analysis(coverage_sets: List[CoverageSet], threshold: int):
    """analyze and display rare blocks across coverage sets"""
    if not coverage_sets:
        return

    typer.echo(f"\nrarity analysis (threshold <= {threshold}):")
    typer.echo("=" * 50)

    # get rarity info for all blocks
    all_blocks = set()
    for cov in coverage_sets:
        all_blocks.update(cov.blocks)

    if not all_blocks:
        typer.echo("no blocks found")
        return

    # count how many sets each block appears in
    block_counts = Counter()
    for block in all_blocks:
        count = sum(1 for cov in coverage_sets if block in cov.blocks)
        if count <= threshold:
            block_counts[block] = count

    if not block_counts:
        typer.echo(f"no blocks found with rarity <= {threshold}")
        return

    # organize by module
    modules = {}
    for cov in coverage_sets:
        modules.update(cov.modules)

    by_module = defaultdict(list)
    for block, count in block_counts.items():
        if block.module_id in modules:
            module_name = modules[block.module_id].name
            by_module[module_name].append((block, count))

    for module_name, block_list in sorted(by_module.items()):
        typer.echo(f"\n{module_name}:")
        for block, count in sorted(block_list, key=lambda x: x[1]):
            typer.echo(
                f"  0x{block.offset:08x} (size: {block.size}, hit by {count} trace{'s' if count != 1 else ''})"
            )


# =============================================================================
# cli commands
# =============================================================================

app = typer.Typer(
    help="powerful drcov coverage analysis and manipulation",
    no_args_is_help=True,
    context_settings=dict(help_option_names=["-h", "--help"]),
    pretty_exceptions_short=True,
    pretty_exceptions_show_locals=False,
    add_completion=False,
)


@app.command()
def union(
    files: List[Path] = typer.Argument(..., help="drcov files to union"),
    output: Path = typer.Option(..., "--output", "-o", help="output file"),
    module: Optional[str] = typer.Option(
        None, "--module", "-m", help="filter to specific module"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="verbose output"),
):
    """compute union of coverage files (logical OR)"""
    coverage_sets = load_multiple_coverage(files)
    if not coverage_sets:
        typer.echo("no valid coverage files loaded", err=True)
        raise typer.Exit(1)

    # compute union
    result = coverage_sets[0]
    for cov in coverage_sets[1:]:
        result = result | cov

    # apply module filter if specified
    if module:
        result = result.filter_by_module(module)

    # write result
    DrcovFormat.write(result, output)

    if verbose:
        typer.echo(f"union of {len(files)} files:")
        print_coverage_stats(result)

    typer.echo(f"wrote {len(result)} blocks to {output}")


@app.command()
def intersect(
    files: List[Path] = typer.Argument(..., help="drcov files to intersect"),
    output: Path = typer.Option(..., "--output", "-o", help="output file"),
    module: Optional[str] = typer.Option(
        None, "--module", "-m", help="filter to specific module"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="verbose output"),
):
    """compute intersection of coverage files (logical AND)"""
    coverage_sets = load_multiple_coverage(files)
    if not coverage_sets:
        typer.echo("no valid coverage files loaded", err=True)
        raise typer.Exit(1)

    # compute intersection
    result = coverage_sets[0]
    for cov in coverage_sets[1:]:
        result = result & cov

    # apply module filter if specified
    if module:
        result = result.filter_by_module(module)

    # write result
    DrcovFormat.write(result, output)

    if verbose:
        typer.echo(f"intersection of {len(files)} files:")
        print_coverage_stats(result)

    typer.echo(f"wrote {len(result)} blocks to {output}")


@app.command()
def diff(
    minuend: Path = typer.Argument(..., help="coverage to subtract from"),
    subtrahend: Path = typer.Argument(..., help="coverage to subtract"),
    output: Path = typer.Option(..., "--output", "-o", help="output file"),
    module: Optional[str] = typer.Option(
        None, "--module", "-m", help="filter to specific module"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="verbose output"),
):
    """compute difference between coverage files (minuend - subtrahend)"""
    try:
        cov1 = DrcovFormat.read(minuend)
        cov2 = DrcovFormat.read(subtrahend)
    except Exception as e:
        typer.echo(f"error loading files: {e}", err=True)
        raise typer.Exit(1)

    # compute difference
    result = cov1 - cov2

    # apply module filter if specified
    if module:
        result = result.filter_by_module(module)

    # write result
    DrcovFormat.write(result, output)

    if verbose:
        typer.echo(f"difference analysis:")
        print_coverage_stats(cov1, f"{minuend.name} (minuend)")
        print_coverage_stats(cov2, f"{subtrahend.name} (subtrahend)")
        print_coverage_stats(result, "result")

    typer.echo(f"wrote {len(result)} unique blocks to {output}")


@app.command()
def symdiff(
    file1: Path = typer.Argument(..., help="first coverage file"),
    file2: Path = typer.Argument(..., help="second coverage file"),
    output: Path = typer.Option(..., "--output", "-o", help="output file"),
    module: Optional[str] = typer.Option(
        None, "--module", "-m", help="filter to specific module"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="verbose output"),
):
    """compute symmetric difference (blocks unique to either file)"""
    try:
        cov1 = DrcovFormat.read(file1)
        cov2 = DrcovFormat.read(file2)
    except Exception as e:
        typer.echo(f"error loading files: {e}", err=True)
        raise typer.Exit(1)

    # compute symmetric difference
    result = cov1 ^ cov2

    # apply module filter if specified
    if module:
        result = result.filter_by_module(module)

    # write result
    DrcovFormat.write(result, output)

    if verbose:
        typer.echo(f"symmetric difference analysis:")
        print_coverage_stats(cov1, file1.name)
        print_coverage_stats(cov2, file2.name)
        print_coverage_stats(result, "result (unique to either)")

    typer.echo(f"wrote {len(result)} blocks to {output}")


@app.command()
def stats(
    files: List[Path] = typer.Argument(..., help="drcov files to analyze"),
    module: Optional[str] = typer.Option(
        None, "--module", "-m", help="filter to specific module"
    ),
):
    """display coverage statistics for files"""
    for filepath in files:
        try:
            coverage = DrcovFormat.read(filepath)

            if module:
                coverage = coverage.filter_by_module(module)

            print_coverage_stats(coverage, filepath.name)
            typer.echo()

        except Exception as e:
            typer.echo(f"error analyzing {filepath}: {e}", err=True)


@app.command()
def rarity(
    files: List[Path] = typer.Argument(..., help="drcov files to analyze"),
    threshold: int = typer.Option(1, "--threshold", "-t", help="rarity threshold"),
    module: Optional[str] = typer.Option(
        None, "--module", "-m", help="filter to specific module"
    ),
):
    """find rare blocks across coverage files"""
    coverage_sets = load_multiple_coverage(files)
    if not coverage_sets:
        typer.echo("no valid coverage files loaded", err=True)
        raise typer.Exit(1)

    # apply module filter if specified
    if module:
        coverage_sets = [cov.filter_by_module(module) for cov in coverage_sets]

    print_rarity_analysis(coverage_sets, threshold)


@app.command()
def compare(
    baseline: Path = typer.Argument(..., help="baseline coverage file"),
    targets: List[Path] = typer.Argument(..., help="files to compare against baseline"),
    module: Optional[str] = typer.Option(
        None, "--module", "-m", help="filter to specific module"
    ),
):
    """compare coverage files against a baseline"""
    try:
        baseline_cov = DrcovFormat.read(baseline)
        if module:
            baseline_cov = baseline_cov.filter_by_module(module)
    except Exception as e:
        typer.echo(f"error loading baseline {baseline}: {e}", err=True)
        raise typer.Exit(1)

    typer.echo(f"baseline: {baseline.name} ({len(baseline_cov)} blocks)")
    typer.echo("=" * 70)
    typer.echo(
        f"{'file':<30} {'total':<8} {'common':<8} {'unique':<8} {'missing':<8} {'coverage':<10}"
    )
    typer.echo("-" * 70)

    for target_path in targets:
        try:
            target_cov = DrcovFormat.read(target_path)
            if module:
                target_cov = target_cov.filter_by_module(module)

            common = baseline_cov & target_cov
            unique = target_cov - baseline_cov
            missing = baseline_cov - target_cov

            coverage_pct = len(common) / len(baseline_cov) if baseline_cov else 0

            typer.echo(
                f"{target_path.name:<30} {len(target_cov):<8} {len(common):<8} "
                f"{len(unique):<8} {len(missing):<8} {coverage_pct:<10.2%}"
            )

        except Exception as e:
            typer.echo(f"error loading {target_path}: {e}", err=True)


if __name__ == "__main__":
    app()
