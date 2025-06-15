"""command line interface for covtool"""

from typing import List, Optional
from pathlib import Path

import typer

from .core import CoverageSet
from .analysis import (
    load_multiple_coverage,
    print_coverage_stats,
    print_rarity_analysis,
    print_detailed_info_rich,
    print_detailed_info_json,
)
from .inspector import run_inspector


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
    result.write_to_file(str(output))

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
    result.write_to_file(str(output))

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
        cov1 = CoverageSet.from_file(str(minuend))
        cov2 = CoverageSet.from_file(str(subtrahend))
    except Exception as e:
        typer.echo(f"error loading files: {e}", err=True)
        raise typer.Exit(1)

    # compute difference
    result = cov1 - cov2

    # apply module filter if specified
    if module:
        result = result.filter_by_module(module)

    # write result
    result.write_to_file(str(output))

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
        cov1 = CoverageSet.from_file(str(file1))
        cov2 = CoverageSet.from_file(str(file2))
    except Exception as e:
        typer.echo(f"error loading files: {e}", err=True)
        raise typer.Exit(1)

    # compute symmetric difference
    result = cov1 ^ cov2

    # apply module filter if specified
    if module:
        result = result.filter_by_module(module)

    # write result
    result.write_to_file(str(output))

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
            coverage = CoverageSet.from_file(str(filepath))

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
def info(
    file: Path = typer.Argument(..., help="drcov file to analyze"),
    module: Optional[str] = typer.Option(
        None, "--module", "-m", help="filter to specific module"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="output information as JSON"
    ),
    top_blocks: int = typer.Option(
        5, "--top-blocks", "-k", help="number of top blocks to show per module"
    ),
):
    """display detailed information about a coverage trace"""
    try:
        coverage = CoverageSet.from_file(str(file), permissive=True)
        if module:
            coverage = coverage.filter_by_module(module)

        if json_output:
            print_detailed_info_json(coverage, file.name, module, top_blocks)
        else:
            print_detailed_info_rich(coverage, file.name, module, top_blocks)
    except Exception as e:
        typer.echo(f"error analyzing {file}: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def inspect(
    file: Path = typer.Argument(..., help="drcov file to inspect"),
    module: Optional[str] = typer.Option(
        None, "--module", "-m", help="filter to specific module"
    ),
):
    """launch interactive tui inspector for coverage trace"""
    try:
        coverage = CoverageSet.from_file(str(file), permissive=True)
        if module:
            coverage = coverage.filter_by_module(module)
            filename = f"{file.name} (filtered: {module})"
        else:
            filename = file.name

        run_inspector(coverage, filename)
    except Exception as e:
        typer.echo(f"error loading {file}: {e}", err=True)
        raise typer.Exit(1)


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
        baseline_cov = CoverageSet.from_file(str(baseline))
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
            target_cov = CoverageSet.from_file(str(target_path))
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


def main():
    """entry point for poetry script"""
    app()


if __name__ == "__main__":
    main()
