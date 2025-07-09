"""high-level abstraction for coverage data analysis and manipulation"""

import os
from typing import Dict, Set, List, Optional
from collections import defaultdict, Counter
from dataclasses import dataclass

from .drcov import CoverageData, BasicBlock, ModuleEntry


class CoverageSet:
    """
    high-level abstraction for coverage data analysis
    provides set operations, filtering, and analysis methods
    """

    def __init__(self, coverage_data: CoverageData):
        self.data = coverage_data
        self._module_map = {m.id: m for m in coverage_data.modules}
        self._blocks_set = set(coverage_data.basic_blocks)

    @classmethod
    def from_file(cls, filepath: str, permissive: bool = False) -> "CoverageSet":
        """create coverage set from file"""
        from .drcov import read

        return cls(read(filepath, permissive=permissive))

    def __len__(self) -> int:
        return len(self.data.basic_blocks)

    def __bool__(self) -> bool:
        return bool(self.data.basic_blocks)

    def __or__(self, other: "CoverageSet") -> "CoverageSet":
        """union operation: self | other"""
        # combine modules from both sets
        all_modules = {**self._module_map, **other._module_map}

        # combine basic blocks
        all_blocks = list(self._blocks_set | other._blocks_set)

        return self._create_coverage_set(all_modules, all_blocks, "covtool_union")

    def __and__(self, other: "CoverageSet") -> "CoverageSet":
        """intersection operation: self & other"""
        # combine modules from both sets
        all_modules = {**self._module_map, **other._module_map}

        # intersect basic blocks
        intersected_blocks = list(self._blocks_set & other._blocks_set)

        return self._create_coverage_set(
            all_modules, intersected_blocks, "covtool_intersect"
        )

    def __sub__(self, other: "CoverageSet") -> "CoverageSet":
        """difference operation: self - other"""
        # subtract basic blocks
        diff_blocks = list(self._blocks_set - other._blocks_set)

        return self._create_coverage_set(self._module_map, diff_blocks, "covtool_diff")

    def __xor__(self, other: "CoverageSet") -> "CoverageSet":
        """symmetric difference: self ^ other"""
        # combine modules from both sets
        all_modules = {**self._module_map, **other._module_map}

        # symmetric difference of basic blocks
        symdiff_blocks = list(self._blocks_set ^ other._blocks_set)

        return self._create_coverage_set(all_modules, symdiff_blocks, "covtool_symdiff")

    def get_absolute_addresses(self) -> Set[int]:
        """convert all blocks to absolute memory addresses"""
        addresses = set()
        for block in self.data.basic_blocks:
            module = self.data.find_module(block.module_id)
            if module:
                addresses.add(module.base + block.start)
        return addresses

    def filter_by_module(self, module_filter: str) -> "CoverageSet":
        """return coverage filtered to modules matching the given string"""
        matching_modules = []
        for module in self.data.modules:
            if module_filter.lower() in module.path.lower():
                matching_modules.append(module)

        if not matching_modules:
            # return empty coverage set
            from .drcov import CoverageData, FileHeader, ModuleTableVersion

            empty_data = CoverageData(
                header=FileHeader(flavor="covtool_filtered"),
                modules=[],
                basic_blocks=[],
                module_version=ModuleTableVersion.V2,
                hit_counts=None,
            )
            return CoverageSet(empty_data)

        matching_ids = {m.id for m in matching_modules}

        # Filter blocks and preserve corresponding hit counts
        filtered_blocks = []
        filtered_hit_counts = []

        for i, block in enumerate(self.data.basic_blocks):
            if block.module_id in matching_ids:
                filtered_blocks.append(block)
                if self.data.has_hit_counts():
                    filtered_hit_counts.append(self.data.hit_counts[i])

        # create new coverage data
        from .drcov import CoverageData, FileHeader, ModuleTableVersion

        filtered_data = CoverageData(
            header=FileHeader(flavor="covtool_filtered"),
            modules=matching_modules,
            basic_blocks=filtered_blocks,
            module_version=self.data.module_version,
            hit_counts=filtered_hit_counts if filtered_hit_counts else None,
        )

        return CoverageSet(filtered_data)

    def get_coverage_by_module(self) -> Dict[str, List[BasicBlock]]:
        """organize coverage by module name"""
        by_module = defaultdict(list)
        for block in self.data.basic_blocks:
            module = self.data.find_module(block.module_id)
            if module:
                module_name = os.path.basename(module.path)
                by_module[module_name].append(block)
        return dict(by_module)

    def get_coverage_by_module_with_base(self) -> Dict[str, List[BasicBlock]]:
        """organize coverage by module name with base address to distinguish duplicates"""
        by_module = defaultdict(list)
        for block in self.data.basic_blocks:
            module = self.data.find_module(block.module_id)
            if module:
                module_name = os.path.basename(module.path)
                # Include base address in key to distinguish duplicate modules
                key = f"{module_name}@0x{module.base:x}"
                by_module[key].append(block)
        return dict(by_module)

    def get_rarity_info(self, all_sets: List["CoverageSet"]) -> Dict[BasicBlock, int]:
        """
        for each block, count how many coverage sets contain it
        useful for finding rare execution paths
        """
        block_counts = Counter()

        for coverage_set in all_sets:
            seen_in_this_set = set()
            for block in coverage_set.data.basic_blocks:
                # use a tuple key to avoid hash issues
                block_key = (block.start, block.module_id, block.size)
                if block_key not in seen_in_this_set:
                    block_counts[block] += 1
                    seen_in_this_set.add(block_key)

        return dict(block_counts)

    def write_to_file(self, filepath: str):
        """write coverage set to drcov file"""
        from .drcov import write

        write(self.data, filepath)

    @property
    def modules(self) -> Dict[int, ModuleEntry]:
        """access to module mapping"""
        return self._module_map

    @property
    def blocks(self) -> Set[BasicBlock]:
        """access to blocks set"""
        return self._blocks_set

    def _create_coverage_set(self, modules, blocks, flavor):
        """Helper to create new CoverageSet with given components"""
        from .drcov import CoverageData, FileHeader, ModuleTableVersion

        new_data = CoverageData(
            header=FileHeader(flavor=flavor),
            modules=list(modules.values()) if isinstance(modules, dict) else modules,
            basic_blocks=blocks,
            module_version=ModuleTableVersion.V2,
            hit_counts=None,  # Set operations don't preserve hit counts
        )
        return CoverageSet(new_data)
