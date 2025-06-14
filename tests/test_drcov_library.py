"""tests for the new drcov library functionality"""

import tempfile
import pytest
from io import BytesIO, StringIO

from covtool.drcov import (
    read, write, builder,
    CoverageData, BasicBlock, ModuleEntry, FileHeader,
    ModuleTableVersion, DrCovError, CoverageBuilder
)


class TestDrcovBasics:
    """test basic drcov library functionality"""

    def test_create_basic_coverage(self):
        """test creating coverage data with builder"""
        b = builder()
        b.set_flavor("test_tool")
        b.add_module("/bin/test", 0x400000, 0x500000, 0x401000)
        b.add_module("/lib/libc.so", 0x7f0000000000, 0x7f0000100000)
        b.add_coverage(0, 0x1000, 32)
        b.add_coverage(0, 0x2000, 16)
        b.add_coverage(1, 0x5000, 8)

        coverage = b.build()
        
        assert len(coverage.modules) == 2
        assert len(coverage.basic_blocks) == 3
        assert coverage.header.flavor == "test_tool"
        assert coverage.module_version == ModuleTableVersion.V2

    def test_module_methods(self):
        """test module entry methods"""
        module = ModuleEntry(0, 0x400000, 0x500000, "/bin/test")
        
        assert module.size == 0x100000
        assert module.contains_address(0x450000)
        assert not module.contains_address(0x300000)
        assert not module.contains_address(0x600000)

    def test_basic_block_methods(self):
        """test basic block methods"""
        module = ModuleEntry(0, 0x400000, 0x500000, "/bin/test")
        block = BasicBlock(0x1000, 32, 0)
        
        assert block.absolute_address(module) == 0x401000

    def test_coverage_data_methods(self):
        """test coverage data helper methods"""
        b = builder()
        b.add_module("/bin/test", 0x400000, 0x500000)
        b.add_module("/lib/libc.so", 0x7f0000000000, 0x7f0000100000)
        b.add_coverage(0, 0x1000, 32)
        b.add_coverage(0, 0x2000, 16)
        b.add_coverage(1, 0x5000, 8)
        
        coverage = b.build()
        
        # test find_module
        mod0 = coverage.find_module(0)
        assert mod0 is not None
        assert mod0.path == "/bin/test"
        
        # test find_module_by_address
        mod_at_addr = coverage.find_module_by_address(0x450000)
        assert mod_at_addr is not None
        assert mod_at_addr.id == 0
        
        # test get_coverage_stats
        stats = coverage.get_coverage_stats()
        assert stats[0] == 2  # 2 blocks in module 0
        assert stats[1] == 1  # 1 block in module 1


class TestDrcovIO:
    """test reading and writing drcov files"""

    def test_write_and_read_cycle(self):
        """test writing then reading a drcov file"""
        # create test coverage
        b = builder()
        b.set_flavor("test_io")
        b.add_module("/bin/program", 0x400000, 0x450000, 0x401000)
        b.add_module("/lib/libc.so.6", 0x7fff00000000, 0x7fff00100000)
        b.add_coverage(0, 0x1000, 32)
        b.add_coverage(0, 0x2000, 16)
        b.add_coverage(1, 0x50000, 8)
        
        original = b.build()
        
        # write to temp file
        with tempfile.NamedTemporaryFile(mode='wb', delete=False) as f:
            write(original, f.name)
            temp_path = f.name
        
        # read it back
        reloaded = read(temp_path)
        
        # verify they match
        assert len(reloaded.modules) == len(original.modules)
        assert len(reloaded.basic_blocks) == len(original.basic_blocks)
        assert reloaded.header.flavor == original.header.flavor
        assert reloaded.module_version == original.module_version
        
        # verify modules
        for orig_mod, reload_mod in zip(original.modules, reloaded.modules):
            assert orig_mod.id == reload_mod.id
            assert orig_mod.base == reload_mod.base
            assert orig_mod.end == reload_mod.end
            assert orig_mod.path == reload_mod.path
        
        # verify basic blocks
        orig_blocks = sorted(original.basic_blocks, key=lambda b: (b.module_id, b.start))
        reload_blocks = sorted(reloaded.basic_blocks, key=lambda b: (b.module_id, b.start))
        
        for orig_bb, reload_bb in zip(orig_blocks, reload_blocks):
            assert orig_bb.start == reload_bb.start
            assert orig_bb.size == reload_bb.size
            assert orig_bb.module_id == reload_bb.module_id

    def test_empty_coverage(self):
        """test handling empty coverage data"""
        b = builder()
        b.set_flavor("empty_test")
        empty_coverage = b.build()
        
        with tempfile.NamedTemporaryFile(mode='wb', delete=False) as f:
            write(empty_coverage, f.name)
            temp_path = f.name
        
        reloaded = read(temp_path)
        assert len(reloaded.modules) == 0
        assert len(reloaded.basic_blocks) == 0
        assert reloaded.header.flavor == "empty_test"

    def test_error_handling(self):
        """test various error conditions"""
        # test reading non-existent file
        with pytest.raises(FileNotFoundError):
            read("/nonexistent/file.drcov")
        
        # test invalid coverage data
        with pytest.raises(DrCovError):
            b = builder()
            b.add_coverage(999, 0x1000, 32)  # invalid module id
            b.build()


class TestModuleTableVersions:
    """test different module table versions"""

    def test_v2_format(self):
        """test module table version 2"""
        b = builder()
        b.set_module_version(ModuleTableVersion.V2)
        b.add_module("/bin/test", 0x400000, 0x500000)
        coverage = b.build()
        
        assert coverage.module_version == ModuleTableVersion.V2

    def test_legacy_format(self):
        """test legacy module table format"""
        b = builder()
        b.set_module_version(ModuleTableVersion.LEGACY)
        b.add_module("/bin/test", 0x400000, 0x500000)
        coverage = b.build()
        
        assert coverage.module_version == ModuleTableVersion.LEGACY


class TestCoverageBuilder:
    """test coverage builder functionality"""

    def test_builder_methods(self):
        """test builder method chaining"""
        coverage = (builder()
                   .set_flavor("chain_test")
                   .set_module_version(ModuleTableVersion.V3)
                   .add_module("/bin/prog", 0x400000, 0x500000)
                   .add_coverage(0, 0x1000, 32)
                   .build())
        
        assert coverage.header.flavor == "chain_test"
        assert coverage.module_version == ModuleTableVersion.V3
        assert len(coverage.modules) == 1
        assert len(coverage.basic_blocks) == 1

    def test_add_basic_blocks_bulk(self):
        """test adding multiple basic blocks at once"""
        blocks = [
            BasicBlock(0x1000, 32, 0),
            BasicBlock(0x2000, 16, 0),
            BasicBlock(0x3000, 8, 0),
        ]
        
        coverage = (builder()
                   .add_module("/bin/test", 0x400000, 0x500000)
                   .add_basic_blocks(blocks)
                   .build())
        
        assert len(coverage.basic_blocks) == 3

    def test_clear_coverage(self):
        """test clearing coverage data"""
        b = builder()
        b.add_module("/bin/test", 0x400000, 0x500000)
        b.add_coverage(0, 0x1000, 32)
        b.add_coverage(0, 0x2000, 16)
        
        assert len(b.data().basic_blocks) == 2
        
        b.clear_coverage()
        assert len(b.data().basic_blocks) == 0


class TestDataclassProperties:
    """test dataclass properties and methods"""

    def test_file_header_to_string(self):
        """test file header serialization"""
        header = FileHeader(version=2, flavor="test")
        header_str = header.to_string()
        
        assert "DRCOV VERSION: 2" in header_str
        assert "DRCOV FLAVOR: test" in header_str

    def test_module_entry_properties(self):
        """test module entry computed properties"""
        module = ModuleEntry(
            id=0,
            base=0x400000,
            end=0x500000,
            path="/bin/test",
            entry=0x401000,
            checksum=0x12345678,
            timestamp=0x87654321
        )
        
        assert module.size == 0x100000
        assert module.contains_address(0x450000)
        assert not module.contains_address(0x600000)

    def test_basic_block_absolute_address(self):
        """test basic block absolute address calculation"""
        module = ModuleEntry(0, 0x400000, 0x500000, "/bin/test")
        block = BasicBlock(0x1500, 64, 0)
        
        assert block.absolute_address(module) == 0x401500
        
        # test mismatched module id
        wrong_module = ModuleEntry(1, 0x600000, 0x700000, "/bin/other")
        with pytest.raises(ValueError):
            block.absolute_address(wrong_module)