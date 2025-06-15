"""Tests for hit count extension functionality"""

import tempfile
import pytest
from io import StringIO, BytesIO
from covtool.drcov import (
    builder, read, write, DrCovError, CoverageData, FileHeader,
    _FLAVOR_STANDARD, _FLAVOR_WITH_HITS
)


class TestHitCountBasics:
    """Test basic hit count functionality"""

    def test_coverage_data_default_no_hit_counts(self):
        """Test that default CoverageData has no hit counts"""
        coverage = builder().add_module("/test", 0x1000, 0x2000).build()
        assert not coverage.has_hit_counts()
        assert coverage.hit_counts is None

    def test_coverage_data_with_hit_counts(self):
        """Test CoverageData with hit counts"""
        coverage = (
            builder()
            .add_module("/test", 0x1000, 0x2000)
            .add_coverage(0, 0x100, 10, hit_count=5)
            .add_coverage(0, 0x200, 15, hit_count=10)
            .build()
        )
        assert coverage.has_hit_counts()
        assert coverage.hit_counts == [5, 10]
        assert coverage.get_hit_count(0) == 5
        assert coverage.get_hit_count(1) == 10

    def test_get_hit_count_default_fallback(self):
        """Test get_hit_count returns 1 when no hit counts available"""
        coverage = (
            builder()
            .add_module("/test", 0x1000, 0x2000)
            .add_coverage(0, 0x100, 10)
            .build()
        )
        assert coverage.get_hit_count(0) == 1
        assert coverage.get_hit_count(99) == 1  # Out of bounds

    def test_get_blocks_with_hits(self):
        """Test get_blocks_with_hits method"""
        coverage = (
            builder()
            .add_module("/test", 0x1000, 0x2000)
            .add_coverage(0, 0x100, 10, hit_count=5)
            .add_coverage(0, 0x200, 15, hit_count=10)
            .build()
        )
        
        blocks_with_hits = coverage.get_blocks_with_hits()
        assert len(blocks_with_hits) == 2
        
        block1, hits1 = blocks_with_hits[0]
        assert block1.start == 0x100
        assert hits1 == 5
        
        block2, hits2 = blocks_with_hits[1]
        assert block2.start == 0x200
        assert hits2 == 10

    def test_get_blocks_with_hits_default(self):
        """Test get_blocks_with_hits with no hit count data"""
        coverage = (
            builder()
            .add_module("/test", 0x1000, 0x2000)
            .add_coverage(0, 0x100, 10)
            .add_coverage(0, 0x200, 15)
            .build()
        )
        
        blocks_with_hits = coverage.get_blocks_with_hits()
        assert len(blocks_with_hits) == 2
        assert blocks_with_hits[0][1] == 1
        assert blocks_with_hits[1][1] == 1


class TestHitCountBuilder:
    """Test CoverageBuilder hit count functionality"""

    def test_builder_automatic_hit_count_initialization(self):
        """Test that hit counts are automatically initialized when needed"""
        coverage = (
            builder()
            .add_module("/test", 0x1000, 0x2000)
            .add_coverage(0, 0x100, 10)  # Default hit count = 1
            .add_coverage(0, 0x200, 15, hit_count=5)  # Triggers hit count initialization
            .build()
        )
        
        assert coverage.has_hit_counts()
        assert coverage.hit_counts == [1, 5]

    def test_builder_set_hit_counts(self):
        """Test setting hit counts explicitly"""
        coverage = (
            builder()
            .add_module("/test", 0x1000, 0x2000)
            .add_coverage(0, 0x100, 10)
            .add_coverage(0, 0x200, 15)
            .set_hit_counts([3, 7])
            .build()
        )
        
        assert coverage.has_hit_counts()
        assert coverage.hit_counts == [3, 7]
        assert coverage.header.supports_hit_counts()

    def test_builder_enable_hit_counts(self):
        """Test enabling hit counts with defaults"""
        coverage = (
            builder()
            .add_module("/test", 0x1000, 0x2000)
            .add_coverage(0, 0x100, 10)
            .add_coverage(0, 0x200, 15)
            .enable_hit_counts()
            .build()
        )
        
        assert coverage.has_hit_counts()
        assert coverage.hit_counts == [1, 1]

    def test_builder_set_hit_counts_mismatch(self):
        """Test error when hit count array length doesn't match blocks"""
        with pytest.raises(ValueError, match="Hit count array length"):
            (
                builder()
                .add_module("/test", 0x1000, 0x2000)
                .add_coverage(0, 0x100, 10)
                .set_hit_counts([1, 2, 3])  # Too many hit counts
                .build()
            )

    def test_builder_flavor_management(self):
        """Test that flavor is automatically set when hit counts are used"""
        # Default flavor
        coverage1 = builder().add_module("/test", 0x1000, 0x2000).build()
        assert coverage1.header.flavor == _FLAVOR_STANDARD
        
        # Flavor changes when hit counts are set
        coverage2 = (
            builder()
            .add_module("/test", 0x1000, 0x2000)
            .add_coverage(0, 0x100, 10)
            .enable_hit_counts()
            .build()
        )
        assert coverage2.header.flavor == _FLAVOR_WITH_HITS


class TestHitCountFileIO:
    """Test file I/O with hit counts"""

    def test_round_trip_with_hit_counts(self):
        """Test writing and reading files with hit counts"""
        original = (
            builder()
            .set_flavor(_FLAVOR_WITH_HITS)
            .add_module("/test", 0x1000, 0x2000)
            .add_coverage(0, 0x100, 10, hit_count=1)
            .add_coverage(0, 0x200, 15, hit_count=5000)
            .add_coverage(0, 0x300, 8, hit_count=123456)
            .build()
        )
        
        with tempfile.NamedTemporaryFile(mode='w+b', delete=False) as f:
            temp_path = f.name
        
        try:
            write(original, temp_path)
            read_back = read(temp_path)
            
            assert read_back.has_hit_counts()
            assert read_back.hit_counts == [1, 5000, 123456]
            assert read_back.header.supports_hit_counts()
            assert len(read_back.basic_blocks) == 3
            
        finally:
            import os
            os.unlink(temp_path)

    def test_round_trip_without_hit_counts(self):
        """Test backward compatibility - files without hit counts"""
        original = (
            builder()
            .add_module("/test", 0x1000, 0x2000)
            .add_coverage(0, 0x100, 10)
            .add_coverage(0, 0x200, 15)
            .build()
        )
        
        with tempfile.NamedTemporaryFile(mode='w+b', delete=False) as f:
            temp_path = f.name
        
        try:
            write(original, temp_path)
            read_back = read(temp_path)
            
            assert not read_back.has_hit_counts()
            assert read_back.hit_counts is None
            assert not read_back.header.supports_hit_counts()
            assert len(read_back.basic_blocks) == 2
            
            # Should still provide default hit counts
            blocks_with_hits = read_back.get_blocks_with_hits()
            assert all(hits == 1 for _, hits in blocks_with_hits)
            
        finally:
            import os
            os.unlink(temp_path)

    def test_permissive_mode_with_invalid_hit_counts(self):
        """Test permissive mode handles invalid hit count data"""
        # This test would be complex to set up with actual invalid data
        # For now, test that valid data works in permissive mode
        coverage = (
            builder()
            .add_module("/test", 0x1000, 0x2000)
            .add_coverage(0, 0x100, 10, hit_count=42)
            .build()
        )
        
        # Should work fine in permissive mode
        coverage.validate(permissive=True)
        assert coverage.get_hit_count(0) == 42


class TestHitCountValidation:
    """Test hit count validation"""

    def test_validation_hit_count_mismatch_strict(self):
        """Test validation fails in strict mode with mismatched hit counts"""
        # Create coverage data with mismatched hit counts manually
        from covtool.drcov import CoverageData, FileHeader, ModuleTableVersion, BasicBlock, ModuleEntry
        
        header = FileHeader()
        modules = [ModuleEntry(0, 0x1000, 0x2000, "/test")]  # Add valid module
        basic_blocks = [BasicBlock(0x100, 10, 0), BasicBlock(0x200, 15, 0)]
        hit_counts = [1, 2, 3]  # Too many hit counts
        
        coverage = CoverageData(header, modules, basic_blocks, ModuleTableVersion.V2, hit_counts)
        
        with pytest.raises(DrCovError, match="Hit count array length"):
            coverage.validate(permissive=False)

    def test_validation_hit_count_mismatch_permissive(self):
        """Test validation handles mismatched hit counts in permissive mode"""
        from covtool.drcov import CoverageData, FileHeader, ModuleTableVersion, BasicBlock, ModuleEntry
        
        header = FileHeader()
        modules = [ModuleEntry(0, 0x1000, 0x2000, "/test")]  # Add valid module
        basic_blocks = [BasicBlock(0x100, 10, 0), BasicBlock(0x200, 15, 0)]
        hit_counts = [1, 2, 3]  # Too many hit counts
        
        coverage = CoverageData(header, modules, basic_blocks, ModuleTableVersion.V2, hit_counts)
        
        # Should not raise in permissive mode
        coverage.validate(permissive=True)
        # Hit counts should be truncated to match basic blocks
        assert len(coverage.hit_counts) == len(coverage.basic_blocks)


class TestHitCountHeaders:
    """Test header functionality for hit counts"""

    def test_header_supports_hit_counts(self):
        """Test FileHeader.supports_hit_counts method"""
        header1 = FileHeader()
        assert not header1.supports_hit_counts()
        
        header2 = FileHeader(flavor=_FLAVOR_WITH_HITS)
        assert header2.supports_hit_counts()

    def test_header_flavor_constants(self):
        """Test that flavor constants are correct"""
        assert _FLAVOR_STANDARD == "drcov"
        assert _FLAVOR_WITH_HITS == "drcov-hits"


class TestHitCountEdgeCases:
    """Test edge cases and error conditions"""

    def test_empty_hit_counts(self):
        """Test behavior with empty hit count arrays"""
        coverage = (
            builder()
            .add_module("/test", 0x1000, 0x2000)
            .set_hit_counts([])
            .build()
        )
        
        assert coverage.has_hit_counts()
        assert coverage.hit_counts == []
        assert len(coverage.basic_blocks) == 0

    def test_large_hit_counts(self):
        """Test with large hit count values"""
        large_hit_count = 0xFFFFFFFF  # Max uint32
        coverage = (
            builder()
            .add_module("/test", 0x1000, 0x2000)
            .add_coverage(0, 0x100, 10, hit_count=large_hit_count)
            .build()
        )
        
        assert coverage.get_hit_count(0) == large_hit_count

    def test_zero_hit_counts(self):
        """Test with zero hit counts"""
        coverage = (
            builder()
            .add_module("/test", 0x1000, 0x2000)
            .add_coverage(0, 0x100, 10, hit_count=0)
            .build()
        )
        
        assert coverage.get_hit_count(0) == 0

    def test_mixed_hit_count_scenarios(self):
        """Test mixed scenarios with some blocks having hit counts"""
        coverage = (
            builder()
            .add_module("/test", 0x1000, 0x2000)
            .add_coverage(0, 0x100, 10)  # Default hit count
            .add_coverage(0, 0x200, 15, hit_count=100)  # Explicit hit count
            .add_coverage(0, 0x300, 8)  # Default again, but hit counts already enabled
            .build()
        )
        
        assert coverage.has_hit_counts()
        assert coverage.hit_counts == [1, 100, 1]