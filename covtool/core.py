"""core data structures for coverage analysis"""

import os
from typing import List, Dict, Set, Tuple
from dataclasses import dataclass
from collections import defaultdict, Counter


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