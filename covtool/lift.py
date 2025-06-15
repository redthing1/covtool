"""lift simple coverage formats into drcov format"""

import re
from typing import List, Dict, Tuple, Optional, Set
from collections import Counter
from pathlib import Path

from .core import CoverageSet
from .drcov import builder, ModuleTableVersion


class LiftError(Exception):
    """error during coverage format lifting"""

    pass


class TraceFormat:
    """enumeration of supported trace formats"""

    MODULE_OFFSET = "ModuleOffsetTrace"
    ADDRESS = "AddressTrace"
    ADDRESS_HIT = "AddressHitTrace"


def parse_hex_number(hex_str: str) -> int:
    """parse hex number with or without 0x prefix"""
    if hex_str.startswith("0x") or hex_str.startswith("0X"):
        return int(hex_str, 16)
    else:
        return int(hex_str, 16)


def parse_module_definitions(module_defs: List[str]) -> Dict[str, int]:
    """
    parse module definitions from -M flags
    format: name@base_addr or name (defaults to 0)
    returns dict mapping module name to base address
    """
    modules = {}

    for module_def in module_defs:
        if "@" in module_def:
            name, addr_str = module_def.split("@", 1)
            try:
                base_addr = parse_hex_number(addr_str)
            except ValueError:
                raise LiftError(
                    f"invalid base address in module definition: {module_def}"
                )
        else:
            name = module_def
            base_addr = 0

        modules[name] = base_addr

    return modules


def detect_format(input_file: str) -> TraceFormat:
    """
    auto-detect the input format by examining the first few valid lines
    returns TraceFormat.MODULE_OFFSET, TraceFormat.ADDRESS, or TraceFormat.ADDRESS_HIT
    """
    module_offset_pattern = re.compile(
        r"^[a-zA-Z_][a-zA-Z0-9_]*\+[0-9a-fA-F]+$", re.IGNORECASE
    )
    address_pattern = re.compile(r"^(0x)?[0-9a-fA-F]+$", re.IGNORECASE)
    address_hit_pattern = re.compile(r"^(0x)?[0-9a-fA-F]+\s+\d+$", re.IGNORECASE)

    with open(input_file, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            if module_offset_pattern.match(line):
                return TraceFormat.MODULE_OFFSET
            elif address_hit_pattern.match(line):
                return TraceFormat.ADDRESS_HIT
            elif address_pattern.match(line):
                return TraceFormat.ADDRESS

            # stop after checking first 10 non-empty lines
            if line_num >= 10:
                break

    raise LiftError("unable to detect input format - no valid entries found")


def parse_module_offset_trace(
    input_file: str, modules: Dict[str, int]
) -> Tuple[List[Tuple[int, str]], Counter]:
    """
    parse module+offset format (e.g., "boombox+3a06")
    returns list of (absolute_address, module_name) and hit counter
    """
    addresses = []
    hit_counter = Counter()
    module_offset_pattern = re.compile(
        r"^([a-zA-Z_][a-zA-Z0-9_]*)\+([0-9a-fA-F]+)$", re.IGNORECASE
    )

    with open(input_file, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            match = module_offset_pattern.match(line)
            if not match:
                # check if it looks like module+offset but has invalid format
                if "+" in line and any(c.isalnum() for c in line):
                    # looks like intended module+offset but malformed
                    parts = line.split("+", 1)
                    if len(parts) == 2 and not re.match(
                        r"^[0-9a-fA-F]+$", parts[1], re.IGNORECASE
                    ):
                        raise LiftError(
                            f"invalid hex offset '{parts[1]}' at line {line_num}"
                        )
                continue

            module_name, offset_str = match.groups()

            if module_name not in modules:
                raise LiftError(
                    f"unknown module '{module_name}' at line {line_num}, define it with -M {module_name}@base_addr"
                )

            try:
                offset = parse_hex_number(offset_str)
            except ValueError:
                raise LiftError(f"invalid hex offset '{offset_str}' at line {line_num}")

            base_addr = modules[module_name]
            absolute_addr = base_addr + offset

            addresses.append((absolute_addr, module_name))
            hit_counter[absolute_addr] += 1

    return addresses, hit_counter


def parse_address_trace(
    input_file: str, modules: Dict[str, int]
) -> Tuple[List[Tuple[int, str]], Counter]:
    """
    parse address format (e.g., "0x14000419c")
    returns list of (absolute_address, module_name) and hit counter
    """
    if len(modules) != 1:
        raise LiftError("address format requires exactly one module definition")

    # get the single module name and base
    module_name = list(modules.keys())[0]
    base_addr = modules[module_name]

    addresses = []
    hit_counter = Counter()
    address_pattern = re.compile(r"^(0x)?[0-9a-fA-F]+$", re.IGNORECASE)

    with open(input_file, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            if not address_pattern.match(line):
                # check if it looks like hex address but has invalid format
                if line.startswith("0x") and len(line) > 2:
                    hex_part = line[2:]
                    if not re.match(r"^[0-9a-fA-F]+$", hex_part, re.IGNORECASE):
                        raise LiftError(
                            f"invalid hex address '{line}' at line {line_num}"
                        )
                elif re.match(
                    r"^[0-9a-fA-F]*[g-zG-Z]", line
                ):  # contains invalid hex chars
                    raise LiftError(f"invalid hex address '{line}' at line {line_num}")
                continue

            try:
                addr = parse_hex_number(line)
            except ValueError:
                raise LiftError(f"invalid hex address '{line}' at line {line_num}")

            addresses.append((addr, module_name))
            hit_counter[addr] += 1

    return addresses, hit_counter


def parse_address_hit_trace(
    input_file: str, modules: Dict[str, int]
) -> Tuple[List[Tuple[int, str]], Counter]:
    """
    parse address+hit format (e.g., "037fb7c0 24")
    returns list of (absolute_address, module_name) and hit counter
    """
    if len(modules) != 1:
        raise LiftError("address format requires exactly one module definition")

    # get the single module name and base
    module_name = list(modules.keys())[0]
    base_addr = modules[module_name]

    addresses = []
    hit_counter = Counter()
    address_hit_pattern = re.compile(r"^(0x)?([0-9a-fA-F]+)\s+(\d+)$", re.IGNORECASE)

    with open(input_file, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            match = address_hit_pattern.match(line)
            if not match:
                # check for malformed address+hit lines
                parts = line.split()
                if len(parts) == 2:
                    addr_part, hit_part = parts
                    if not re.match(r"^(0x)?[0-9a-fA-F]+$", addr_part, re.IGNORECASE):
                        raise LiftError(
                            f"invalid hex address '{addr_part}' at line {line_num}"
                        )
                    if not hit_part.isdigit():
                        raise LiftError(
                            f"invalid hit count '{hit_part}' at line {line_num}"
                        )
                continue

            prefix, addr_str, hit_str = match.groups()

            try:
                addr = parse_hex_number(addr_str if not prefix else prefix + addr_str)
                hit_count = int(hit_str)
            except ValueError as e:
                raise LiftError(f"invalid address or hit count at line {line_num}: {e}")

            addresses.append((addr, module_name))
            hit_counter[addr] = hit_count

    return addresses, hit_counter


def build_drcov_from_addresses(
    addresses: List[Tuple[int, str]], hit_counter: Counter, modules: Dict[str, int]
) -> CoverageSet:
    """
    build drcov format from list of absolute addresses
    assumes each address represents a basic block of size 1
    """
    # create drcov builder
    b = builder()
    b.set_flavor("covtool_lift")
    b.set_module_version(ModuleTableVersion.V2)

    # add modules to builder - we need to estimate end addresses
    module_to_id = {}

    # first pass: find maximum offset for each module to estimate sizes
    max_offsets = {}
    for addr, module_name in addresses:
        base_addr = modules[module_name]
        offset = addr - base_addr
        if offset >= 0:  # only consider valid offsets
            max_offsets[module_name] = max(max_offsets.get(module_name, 0), offset)

    for i, (module_name, base_addr) in enumerate(modules.items()):
        # estimate end address based on actual usage or default to 1MB
        max_offset = max_offsets.get(module_name, 0)
        estimated_size = max(
            0x100000, max_offset + 0x1000
        )  # at least 1MB or max_offset + 4KB
        end_addr = base_addr + estimated_size
        b.add_module(module_name, base_addr, end_addr, base_addr)
        module_to_id[module_name] = i

    # process unique addresses only
    unique_addresses = set(addr for addr, _ in addresses)

    for addr in unique_addresses:
        # find the module for this address (use first occurrence from addresses list)
        module_name = next(mod for a, mod in addresses if a == addr)

        module_id = module_to_id[module_name]
        base_addr = modules[module_name]
        offset = addr - base_addr

        if offset < 0:
            raise LiftError(
                f"address 0x{addr:x} is below module base 0x{base_addr:x} for module {module_name}"
            )

        hit_count = hit_counter[addr]
        b.add_coverage(
            module_id, offset, 1, hit_count
        )  # assume size=1 for basic blocks

    # enable hit counts if any hits > 1
    if any(count > 1 for count in hit_counter.values()):
        b.enable_hit_counts()

    coverage_data = b.build()
    return CoverageSet(coverage_data)


def lift_coverage_file(
    input_file: str, module_defs: List[str], verbose: bool = False
) -> CoverageSet:
    """
    main function to lift a simple coverage format to drcov
    """
    # validate input file exists
    if not Path(input_file).exists():
        raise LiftError(f"input file does not exist: {input_file}")

    # check for empty module list
    if not module_defs:
        raise LiftError("at least one module must be specified with -M")

    # parse module definitions
    try:
        modules = parse_module_definitions(module_defs)
    except LiftError as e:
        raise LiftError(f"error parsing module definitions: {e}")

    if verbose:
        print(f"parsed modules: {modules}")

    # detect format
    try:
        format_type = detect_format(input_file)
    except LiftError as e:
        raise LiftError(f"format detection failed: {e}")

    if verbose:
        print(f"detected format: {format_type}")

    # parse based on format
    if format_type == TraceFormat.MODULE_OFFSET:
        addresses, hit_counter = parse_module_offset_trace(input_file, modules)
    elif format_type == TraceFormat.ADDRESS:
        addresses, hit_counter = parse_address_trace(input_file, modules)
    elif format_type == TraceFormat.ADDRESS_HIT:
        addresses, hit_counter = parse_address_hit_trace(input_file, modules)
    else:
        raise LiftError(f"unsupported format: {format_type}")

    if not addresses:
        raise LiftError("no valid coverage entries found in input file")

    if verbose:
        unique_addrs = len(set(addr for addr, _ in addresses))
        total_hits = sum(hit_counter.values())
        print(
            f"parsed {len(addresses)} entries, {unique_addrs} unique addresses, {total_hits} total hits"
        )

    # build drcov format
    try:
        coverage_set = build_drcov_from_addresses(addresses, hit_counter, modules)
    except LiftError as e:
        raise LiftError(f"error building drcov format: {e}")

    return coverage_set
