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

# global state for verbose option
verbose_enabled = False


@app.callback()
def main_callback(
    verbose: bool = typer.Option(
        False, "-v", "--verbose", help="enable verbose output for all operations"
    ),
):
    """global options for covtool"""
    global verbose_enabled
    verbose_enabled = verbose


@app.command()
def union(
    files: List[Path] = typer.Argument(..., help="drcov files to union"),
    output: Path = typer.Option(..., "--output", "-o", help="output file"),
    module: Optional[str] = typer.Option(
        None, "--module", "-m", help="filter to specific module"
    ),
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

    if verbose_enabled:
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

    if verbose_enabled:
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

    if verbose_enabled:
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

    if verbose_enabled:
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


@app.command()
def lift(
    input_file: Path = typer.Argument(
        ..., help="input file with simple coverage format"
    ),
    output: Path = typer.Option(..., "--output", "-o", help="output drcov file"),
    modules: List[str] = typer.Option(
        [], "--module", "-M", help="module definitions (name@base_addr)"
    ),
):
    """lift simple coverage formats to drcov format"""
    if not modules:
        typer.echo("error: at least one module must be specified with -M", err=True)
        raise typer.Exit(1)

    try:
        from .lift import lift_coverage_file

        result_coverage = lift_coverage_file(str(input_file), modules, verbose_enabled)
        result_coverage.write_to_file(str(output))
        typer.echo(f"wrote {len(result_coverage)} blocks to {output}")
    except Exception as e:
        typer.echo(f"error lifting coverage file: {e}", err=True)
        if verbose_enabled:
            import traceback

            traceback.print_exc()
        raise typer.Exit(1)


@app.command()
def edit(
    file: Path = typer.Argument(..., help="drcov file to edit"),
    output: Path = typer.Option(..., "--output", "-o", help="output file"),
    rebase: List[str] = typer.Option(
        [],
        "--rebase",
        "-r",
        help="rebase module to new address (module->addr or module@oldaddr->newaddr)",
    ),
):
    """edit a coverage trace with various operations"""
    if not rebase:
        typer.echo("error: at least one edit operation must be specified", err=True)
        raise typer.Exit(1)

    try:
        # load the coverage file
        coverage = CoverageSet.from_file(str(file), permissive=True)
        modified = False

        # process rebase operations
        for rebase_spec in rebase:
            if "->" not in rebase_spec:
                typer.echo(
                    f"error: invalid rebase specification '{rebase_spec}' - expected 'module->addr' or 'module@oldaddr->newaddr'",
                    err=True,
                )
                continue

            parts = rebase_spec.split("->", 1)
            if len(parts) != 2:
                typer.echo(
                    f"error: invalid rebase specification '{rebase_spec}' - expected 'module->addr' or 'module@oldaddr->newaddr'",
                    err=True,
                )
                continue

            module_spec, new_addr_str = parts

            # parse new address
            try:
                new_addr = (
                    int(new_addr_str, 16)
                    if new_addr_str.startswith("0x")
                    else int(new_addr_str, 16)
                )
            except ValueError:
                typer.echo(
                    f"error: invalid address '{new_addr_str}' in rebase specification",
                    err=True,
                )
                continue

            # parse module specification (either 'module' or 'module@addr')
            if "@" in module_spec:
                module_name, old_addr_str = module_spec.split("@", 1)
                try:
                    old_addr = (
                        int(old_addr_str, 16)
                        if old_addr_str.startswith("0x")
                        else int(old_addr_str, 16)
                    )
                except ValueError:
                    typer.echo(
                        f"error: invalid address '{old_addr_str}' in module specification",
                        err=True,
                    )
                    continue

                # find module by name and current base address
                matching_modules = [
                    m
                    for m in coverage.data.modules
                    if module_name.lower() in m.path.lower() and m.base == old_addr
                ]
            else:
                module_name = module_spec
                # find all modules matching the name
                matching_modules = [
                    m
                    for m in coverage.data.modules
                    if module_name.lower() in m.path.lower()
                ]

                if len(matching_modules) > 1:
                    typer.echo(
                        f"error: multiple modules match '{module_name}' - use module@addr->newaddr syntax to disambiguate:",
                        err=True,
                    )
                    for m in matching_modules:
                        typer.echo(
                            f"  {m.path.split('/')[-1]}@0x{m.base:x}->0x{new_addr:x}",
                            err=True,
                        )
                    continue

            if not matching_modules:
                typer.echo(f"error: no module found matching '{module_spec}'", err=True)
                continue

            # rebase the module
            module = matching_modules[0]
            old_base = module.base
            size = module.end - module.base

            if verbose_enabled:
                typer.echo(
                    f"rebasing module '{module.path.split('/')[-1]}' from 0x{old_base:x} to 0x{new_addr:x}"
                )

            module.base = new_addr
            module.end = new_addr + size
            modified = True

        if modified:
            # write the modified coverage
            coverage.write_to_file(str(output))
            typer.echo(f"wrote modified coverage to {output}")
        else:
            typer.echo("no modifications made")

    except Exception as e:
        typer.echo(f"error editing coverage file: {e}", err=True)
        if verbose_enabled:
            import traceback

            traceback.print_exc()
        raise typer.Exit(1)


def main():
    """entry point for poetry script"""
    app()


if __name__ == "__main__":
    main()
