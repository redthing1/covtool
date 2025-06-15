"""analysis functions and utilities for coverage data"""

import json
import os
from typing import List, Dict, Any
from pathlib import Path
from collections import defaultdict, Counter

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich.tree import Tree
from rich.progress import Progress, BarColumn, TextColumn
from rich.layout import Layout
from rich.align import Align

from .core import CoverageSet
from .drcov import BasicBlock


def load_multiple_coverage(filepaths: List[Path]) -> List[CoverageSet]:
    """load multiple coverage files, handling errors gracefully"""
    results = []
    for path in filepaths:
        try:
            coverage = CoverageSet.from_file(str(path))
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


def _generate_coverage_data(
    coverage: CoverageSet, filename: str, module_filter: str = None, top_blocks: int = 5
) -> Dict[str, Any]:
    """generate comprehensive coverage data structure"""
    data = {
        "filename": filename,
        "filter": module_filter,
        "summary": {
            "total_blocks": len(coverage),
            "total_modules": len(coverage.modules),
        },
        "modules": [],
        "address_space": {},
        "block_size_distribution": [],
        "sample_blocks": {},
    }

    if coverage.data.basic_blocks:
        # block size statistics
        block_sizes = [block.size for block in coverage.data.basic_blocks]
        total_size = sum(block_sizes)
        avg_size = total_size / len(coverage.data.basic_blocks)
        min_size = min(block_sizes)
        max_size = max(block_sizes)

        data["summary"].update(
            {
                "total_coverage_size": total_size,
                "average_block_size": round(avg_size, 1),
                "min_block_size": min_size,
                "max_block_size": max_size,
            }
        )

        # address space analysis
        addresses = coverage.get_absolute_addresses()
        if addresses:
            min_addr = min(addresses)
            max_addr = max(addresses)
            addr_range = max_addr - min_addr

            data["address_space"] = {
                "min_address": f"0x{min_addr:x}",
                "max_address": f"0x{max_addr:x}",
                "range_bytes": addr_range,
                "range_mb": round(addr_range / 1024 / 1024, 1),
            }

        # block size distribution
        size_counts = Counter(block_sizes)
        for size, count in size_counts.most_common(10):
            percentage = (count / len(coverage)) * 100
            data["block_size_distribution"].append(
                {"size": size, "count": count, "percentage": round(percentage, 1)}
            )

    # module information
    by_module = coverage.get_coverage_by_module()
    if by_module:
        sorted_modules = sorted(
            by_module.items(), key=lambda x: len(x[1]), reverse=True
        )

        for module_name, blocks in sorted_modules:
            block_count = len(blocks)
            coverage_size = sum(block.size for block in blocks)
            percentage = (block_count / len(coverage)) * 100 if coverage else 0

            # get module details
            module_obj = None
            for mod in coverage.modules.values():
                if os.path.basename(mod.path) == module_name:
                    module_obj = mod
                    break

            module_data = {
                "name": module_name,
                "block_count": block_count,
                "coverage_size": coverage_size,
                "percentage": round(percentage, 1),
            }

            if module_obj:
                module_size = module_obj.end - module_obj.base
                module_data.update(
                    {
                        "path": module_obj.path,
                        "base_address": f"0x{module_obj.base:x}",
                        "end_address": f"0x{module_obj.end:x}",
                        "entry_point": f"0x{module_obj.entry:x}",
                        "module_size": module_size,
                    }
                )

            data["modules"].append(module_data)

            # top k blocks by size for every module
            top_blocks_by_size = sorted(blocks, key=lambda b: b.size, reverse=True)[:top_blocks]
            data["sample_blocks"][module_name] = []
            for block in top_blocks_by_size:
                abs_addr = module_obj.base + block.start if module_obj else None
                block_data = {"offset": f"0x{block.start:08x}", "size": block.size}
                if abs_addr:
                    block_data["absolute_address"] = f"0x{abs_addr:x}"
                data["sample_blocks"][module_name].append(block_data)

    return data


def print_detailed_info_rich(
    coverage: CoverageSet, filename: str, module_filter: str = None, top_blocks: int = 5
):
    """display comprehensive information about a coverage trace using Rich"""
    console = Console()
    data = _generate_coverage_data(coverage, filename, module_filter, top_blocks)

    # header with title
    filter_text = f" (filtered to: {module_filter})" if module_filter else ""
    title = f"[bold cyan]Coverage Trace Information[/bold cyan]\n[dim]{filename}{filter_text}[/dim]"
    console.print(Panel(title, expand=False))
    console.print()

    # summary statistics
    summary_table = Table(
        title="[bold]Summary Statistics[/bold]", show_header=False, box=None
    )
    summary_table.add_column("Metric", style="bold")
    summary_table.add_column("Value", style="cyan")

    summary = data["summary"]
    summary_table.add_row("Total Basic Blocks", f"{summary['total_blocks']:,}")
    summary_table.add_row("Total Modules", f"{summary['total_modules']:,}")

    if "total_coverage_size" in summary:
        summary_table.add_row(
            "Total Coverage Size", f"{summary['total_coverage_size']:,} bytes"
        )
        summary_table.add_row(
            "Average Block Size", f"{summary['average_block_size']} bytes"
        )
        summary_table.add_row(
            "Block Size Range",
            f"{summary['min_block_size']} - {summary['max_block_size']} bytes",
        )

    console.print(summary_table)
    console.print()

    # address space info
    if data["address_space"]:
        addr_space = data["address_space"]
        addr_table = Table(
            title="[bold]Address Space[/bold]", show_header=False, box=None
        )
        addr_table.add_column("Property", style="bold")
        addr_table.add_column("Value", style="green")

        addr_table.add_row(
            "Address Range",
            f"{addr_space['min_address']} - {addr_space['max_address']}",
        )
        addr_table.add_row(
            "Span", f"{addr_space['range_bytes']:,} bytes ({addr_space['range_mb']} MB)"
        )

        console.print(addr_table)
        console.print()

    # module breakdown
    if data["modules"]:
        modules_table = Table(title="[bold]Module Breakdown[/bold]")
        modules_table.add_column("Module", style="cyan", no_wrap=True)
        modules_table.add_column("Blocks", justify="right", style="yellow")
        modules_table.add_column("Coverage", justify="right", style="green")
        modules_table.add_column("Size", justify="right", style="blue")
        modules_table.add_column("Path", style="dim", max_width=50)

        for mod in data["modules"][:10]:  # top 10 modules
            modules_table.add_row(
                mod["name"],
                f"{mod['block_count']:,}",
                f"{mod['percentage']:.1f}%",
                f"{mod['coverage_size']:,}b",
                mod.get("path", ""),
            )

        console.print(modules_table)
        console.print()

    # block size distribution
    if data["block_size_distribution"]:
        size_table = Table(title="[bold]Block Size Distribution[/bold]")
        size_table.add_column("Size", justify="right", style="cyan")
        size_table.add_column("Count", justify="right", style="yellow")
        size_table.add_column("Percentage", justify="right", style="green")
        size_table.add_column("Bar", style="blue")

        max_count = max(item["count"] for item in data["block_size_distribution"])

        for item in data["block_size_distribution"]:
            bar_width = int((item["count"] / max_count) * 20)
            bar = "█" * bar_width

            size_table.add_row(
                f"{item['size']} bytes",
                f"{item['count']:,}",
                f"{item['percentage']:.1f}%",
                f"[blue]{bar}[/blue]",
            )

        console.print(size_table)
        console.print()

    # top blocks by size for each module
    if data["sample_blocks"]:
        console.print(f"[bold]Top {top_blocks} Blocks by Size per Module[/bold]")
        console.print()

        for module_name, blocks in data["sample_blocks"].items():
            if blocks:  # Only show modules that have blocks
                tree = Tree(f"[cyan]{module_name}[/cyan]")
                for block in blocks:
                    addr_info = (
                        f" → {block['absolute_address']}"
                        if "absolute_address" in block
                        else ""
                    )
                    tree.add(f"{block['offset']} ({block['size']}b){addr_info}")
                console.print(tree)
        console.print()


def print_detailed_info_json(
    coverage: CoverageSet, filename: str, module_filter: str = None, top_blocks: int = 5
):
    """output comprehensive coverage information as JSON"""
    data = _generate_coverage_data(coverage, filename, module_filter, top_blocks)
    print(json.dumps(data, indent=2))


def print_rarity_analysis(coverage_sets: List[CoverageSet], threshold: int):
    """analyze and display rare blocks across coverage sets"""
    if not coverage_sets:
        return

    typer.echo(f"\nrarity analysis (threshold <= {threshold}):")
    typer.echo("=" * 50)

    # get rarity info for all blocks
    all_blocks = set()
    for cov in coverage_sets:
        all_blocks.update(cov.data.basic_blocks)

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
            module_name = os.path.basename(modules[block.module_id].path)
            by_module[module_name].append((block, count))

    for module_name, block_list in sorted(by_module.items()):
        typer.echo(f"\n{module_name}:")
        for block, count in sorted(block_list, key=lambda x: x[1]):
            typer.echo(
                f"  0x{block.start:08x} (size: {block.size}, hit by {count} trace{'s' if count != 1 else ''})"
            )
