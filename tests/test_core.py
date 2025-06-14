"""tests for coverage set core functionality"""

import tempfile
import pytest
from pathlib import Path

from covtool.core import CoverageSet
from covtool.drcov import (
    builder, BasicBlock, ModuleEntry, CoverageData, 
    FileHeader, ModuleTableVersion
)


class TestCoverageSet:
    """test coverage set functionality"""

    def create_test_coverage(self, flavor="test"):
        """helper to create test coverage data"""
        b = builder()
        b.set_flavor(flavor)
        b.add_module("/bin/program", 0x400000, 0x450000, 0x401000)
        b.add_module("/lib/libc.so", 0x7fff00000000, 0x7fff00100000)
        b.add_coverage(0, 0x1000, 32)  # program block 1
        b.add_coverage(0, 0x2000, 16)  # program block 2 
        b.add_coverage(1, 0x50000, 8)  # libc block
        return CoverageSet(b.build())

    def test_coverage_set_creation(self):
        """test creating coverage set from data"""
        cov = self.create_test_coverage()
        
        assert len(cov) == 3
        assert len(cov.modules) == 2
        assert bool(cov) is True

    def test_from_file_creation(self):
        """test creating coverage set from file"""
        # create test file
        original = self.create_test_coverage("file_test")
        
        with tempfile.NamedTemporaryFile(mode='wb', delete=False) as f:
            original.write_to_file(f.name)
            temp_path = f.name
        
        # load from file
        loaded = CoverageSet.from_file(temp_path)
        
        assert len(loaded) == len(original)
        assert len(loaded.modules) == len(original.modules)

    def test_set_operations(self):
        """test set operations between coverage sets"""
        # create two coverage sets with some overlap
        cov1 = self.create_test_coverage("cov1")
        
        b2 = builder()
        b2.set_flavor("cov2")
        b2.add_module("/bin/program", 0x400000, 0x450000)
        b2.add_module("/lib/libm.so", 0x7ffe00000000, 0x7ffe00100000)
        b2.add_coverage(0, 0x2000, 16)  # overlaps with cov1
        b2.add_coverage(0, 0x3000, 24)  # unique to cov2
        b2.add_coverage(1, 0x10000, 12) # unique module/block
        cov2 = CoverageSet(b2.build())
        
        # test union
        union = cov1 | cov2
        assert len(union) == 5  # 3 from cov1 + 3 from cov2 - 1 overlap
        
        # test intersection
        intersection = cov1 & cov2
        assert len(intersection) == 1  # only the overlapping block
        
        # test difference
        diff = cov1 - cov2
        assert len(diff) == 2  # cov1 blocks minus the overlap
        
        # test symmetric difference
        symdiff = cov1 ^ cov2
        assert len(symdiff) == 4  # all unique blocks

    def test_module_filtering(self):
        """test filtering coverage by module"""
        cov = self.create_test_coverage()
        
        # filter to program module
        program_cov = cov.filter_by_module("program")
        assert len(program_cov) == 2  # 2 blocks in program
        assert len(program_cov.modules) == 1
        
        # filter to libc module
        libc_cov = cov.filter_by_module("libc")
        assert len(libc_cov) == 1  # 1 block in libc
        assert len(libc_cov.modules) == 1
        
        # filter to non-existent module
        empty_cov = cov.filter_by_module("nonexistent")
        assert len(empty_cov) == 0
        assert len(empty_cov.modules) == 0

    def test_get_coverage_by_module(self):
        """test organizing coverage by module name"""
        cov = self.create_test_coverage()
        by_module = cov.get_coverage_by_module()
        
        assert "program" in by_module
        assert "libc.so" in by_module
        assert len(by_module["program"]) == 2
        assert len(by_module["libc.so"]) == 1

    def test_absolute_addresses(self):
        """test getting absolute addresses"""
        cov = self.create_test_coverage()
        addresses = cov.get_absolute_addresses()
        
        expected = {
            0x401000,  # program block 1: 0x400000 + 0x1000
            0x402000,  # program block 2: 0x400000 + 0x2000
            0x7fff00050000,  # libc block: 0x7fff00000000 + 0x50000
        }
        
        assert addresses == expected

    def test_rarity_analysis(self):
        """test rarity analysis across multiple coverage sets"""
        cov1 = self.create_test_coverage("rare1")
        cov2 = self.create_test_coverage("rare2")
        
        # create third coverage with different blocks
        b3 = builder()
        b3.add_module("/bin/program", 0x400000, 0x450000)
        b3.add_coverage(0, 0x5000, 64)  # unique block
        cov3 = CoverageSet(b3.build())
        
        all_sets = [cov1, cov2, cov3]
        rarity = cov1.get_rarity_info(all_sets)
        
        # blocks in cov1 and cov2 should have count 2
        # block in cov3 should have count 1
        assert len(rarity) > 0

    def test_write_to_file(self):
        """test writing coverage set to file"""
        cov = self.create_test_coverage("write_test")
        
        with tempfile.NamedTemporaryFile(mode='wb', delete=False) as f:
            cov.write_to_file(f.name)
            temp_path = f.name
        
        # verify file was written correctly
        reloaded = CoverageSet.from_file(temp_path)
        assert len(reloaded) == len(cov)
        assert len(reloaded.modules) == len(cov.modules)

    def test_properties(self):
        """test coverage set properties"""
        cov = self.create_test_coverage()
        
        # test modules property
        modules = cov.modules
        assert isinstance(modules, dict)
        assert len(modules) == 2
        assert 0 in modules
        assert 1 in modules
        
        # test blocks property
        blocks = cov.blocks
        assert isinstance(blocks, set)
        assert len(blocks) == 3

    def test_empty_coverage_set(self):
        """test empty coverage set behavior"""
        empty_data = CoverageData(
            header=FileHeader(flavor="empty"),
            modules=[],
            basic_blocks=[],
            module_version=ModuleTableVersion.V2
        )
        empty_cov = CoverageSet(empty_data)
        
        assert len(empty_cov) == 0
        assert bool(empty_cov) is False
        assert len(empty_cov.modules) == 0
        assert len(empty_cov.get_absolute_addresses()) == 0
        assert len(empty_cov.get_coverage_by_module()) == 0


class TestCoverageSetIntegration:
    """integration tests for coverage set operations"""

    def test_complex_set_operations(self):
        """test complex combinations of set operations"""
        # create three different coverage sets
        b1 = builder()
        b1.add_module("/bin/app", 0x400000, 0x500000)
        b1.add_coverage(0, 0x1000, 32)
        b1.add_coverage(0, 0x2000, 16)
        cov1 = CoverageSet(b1.build())
        
        b2 = builder()
        b2.add_module("/bin/app", 0x400000, 0x500000)
        b2.add_coverage(0, 0x2000, 16)  # overlap with cov1
        b2.add_coverage(0, 0x3000, 24)
        cov2 = CoverageSet(b2.build())
        
        b3 = builder()
        b3.add_module("/bin/app", 0x400000, 0x500000)
        b3.add_coverage(0, 0x4000, 8)
        cov3 = CoverageSet(b3.build())
        
        # test (cov1 | cov2) & cov3
        union_then_intersect = (cov1 | cov2) & cov3
        assert len(union_then_intersect) == 0  # no overlap with cov3
        
        # test (cov1 & cov2) | cov3  
        intersect_then_union = (cov1 & cov2) | cov3
        assert len(intersect_then_union) == 2  # 1 from intersection + 1 from cov3

    def test_filtered_set_operations(self):
        """test set operations on filtered coverage sets"""
        # create coverage with multiple modules
        b1 = builder()
        b1.add_module("/bin/app", 0x400000, 0x500000)
        b1.add_module("/lib/libc.so", 0x7fff00000000, 0x7fff00100000)
        b1.add_coverage(0, 0x1000, 32)  # app block
        b1.add_coverage(1, 0x1000, 16)  # libc block
        cov1 = CoverageSet(b1.build())
        
        b2 = builder()
        b2.add_module("/bin/app", 0x400000, 0x500000)
        b2.add_module("/lib/libc.so", 0x7fff00000000, 0x7fff00100000)
        b2.add_coverage(0, 0x2000, 24)  # different app block
        b2.add_coverage(1, 0x1000, 16)  # same libc block
        cov2 = CoverageSet(b2.build())
        
        # filter to libc only, then do intersection
        libc1 = cov1.filter_by_module("libc")
        libc2 = cov2.filter_by_module("libc")
        libc_intersection = libc1 & libc2
        
        assert len(libc_intersection) == 1  # the common libc block

    def test_chain_operations(self):
        """test chaining multiple operations"""
        cov = CoverageSet.from_file  # would need actual file
        
        # create test coverage instead
        b = builder()
        b.add_module("/bin/program", 0x400000, 0x500000)
        b.add_module("/lib/libc.so", 0x7fff00000000, 0x7fff00100000)
        b.add_coverage(0, 0x1000, 32)
        b.add_coverage(0, 0x2000, 16) 
        b.add_coverage(1, 0x50000, 8)
        cov = CoverageSet(b.build())
        
        # chain filter -> get coverage by module -> check results
        filtered = cov.filter_by_module("program")
        by_module = filtered.get_coverage_by_module()
        
        assert "program" in by_module
        assert "libc.so" not in by_module
        assert len(by_module["program"]) == 2