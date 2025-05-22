"""analysis functions and utilities for coverage data"""

from typing import List
from pathlib import Path
from collections import defaultdict, Counter

import typer

from .core import CoverageSet
from .drcov import DrcovFormat


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