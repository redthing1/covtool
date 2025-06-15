"""tests for analysis functionality"""

import json
import tempfile
from io import StringIO
from pathlib import Path

import pytest

from covtool.core import CoverageSet
from covtool.drcov import builder
from covtool.analysis import (
    load_multiple_coverage,
    print_coverage_stats,
    print_rarity_analysis,
    print_detailed_info_rich,
    print_detailed_info_json,
    _generate_coverage_data,
)


class TestAnalysisFunctions:
    """test analysis functions"""

    def create_test_coverage(self, name="test", num_blocks=3):
        """helper to create test coverage"""
        b = builder()
        b.set_flavor(name)
        b.add_module("/bin/program", 0x400000, 0x450000)
        b.add_module("/lib/libc.so", 0x7FFF00000000, 0x7FFF00100000)

        for i in range(num_blocks):
            module_id = i % 2
            offset = 0x1000 + (i * 0x1000)
            size = 32 + (i * 8)
            b.add_coverage(module_id, offset, size)

        return CoverageSet(b.build())

    def test_load_multiple_coverage(self):
        """test loading multiple coverage files"""
        # create test files
        cov1 = self.create_test_coverage("cov1")
        cov2 = self.create_test_coverage("cov2")

        files = []
        for i, cov in enumerate([cov1, cov2]):
            with tempfile.NamedTemporaryFile(
                mode="wb", delete=False, suffix=".drcov"
            ) as f:
                cov.write_to_file(f.name)
                files.append(Path(f.name))

        # load multiple files
        coverage_sets = load_multiple_coverage(files)

        assert len(coverage_sets) == 2
        for cov in coverage_sets:
            assert isinstance(cov, CoverageSet)
            assert len(cov) == 3

    def test_load_multiple_coverage_with_errors(self):
        """test loading multiple files with some errors"""
        # create one valid file and one invalid path
        cov1 = self.create_test_coverage("valid")

        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".drcov") as f:
            cov1.write_to_file(f.name)
            valid_file = Path(f.name)

        invalid_file = Path("/nonexistent/file.drcov")

        # should load the valid one and skip the invalid one
        coverage_sets = load_multiple_coverage([valid_file, invalid_file])

        assert len(coverage_sets) == 1
        assert len(coverage_sets[0]) == 3

    def test_print_coverage_stats(self, capsys):
        """test printing coverage statistics"""
        cov = self.create_test_coverage("stats_test")

        print_coverage_stats(cov, "test coverage")

        captured = capsys.readouterr()
        output = captured.out

        assert "test coverage:" in output
        assert "basic blocks: 3" in output
        assert "modules: 2" in output
        assert "program:" in output
        assert "libc.so:" in output

    def test_generate_coverage_data(self):
        """test generating comprehensive coverage data"""
        cov = self.create_test_coverage("data_test", 5)

        data = _generate_coverage_data(cov, "test.drcov", "program")

        # check basic structure
        assert data["filename"] == "test.drcov"
        assert data["filter"] == "program"
        assert "summary" in data
        assert "modules" in data
        assert "address_space" in data
        assert "block_size_distribution" in data

        # check summary
        summary = data["summary"]
        assert summary["total_blocks"] == 5
        assert summary["total_modules"] == 2
        assert "total_coverage_size" in summary
        assert "average_block_size" in summary

        # check modules info
        assert len(data["modules"]) == 2
        for module in data["modules"]:
            assert "name" in module
            assert "block_count" in module
            assert "coverage_size" in module
            assert "percentage" in module

    def test_print_detailed_info_json(self, capsys):
        """test JSON output of detailed info"""
        cov = self.create_test_coverage("json_test")

        print_detailed_info_json(cov, "test.drcov")

        captured = capsys.readouterr()
        output = captured.out

        # should be valid JSON
        data = json.loads(output)
        assert data["filename"] == "test.drcov"
        assert "summary" in data
        assert "modules" in data

    def test_print_rarity_analysis(self, capsys):
        """test rarity analysis printing"""
        # create coverage sets with some common and rare blocks
        cov1 = self.create_test_coverage("rare1", 3)
        cov2 = self.create_test_coverage("rare2", 3)  # same as cov1

        # create different coverage
        b3 = builder()
        b3.add_module("/bin/program", 0x400000, 0x450000)
        b3.add_coverage(0, 0x9000, 64)  # unique block
        cov3 = CoverageSet(b3.build())

        coverage_sets = [cov1, cov2, cov3]

        print_rarity_analysis(coverage_sets, threshold=1)

        captured = capsys.readouterr()
        output = captured.out

        assert "rarity analysis" in output
        assert "program" in output

    def test_empty_coverage_analysis(self):
        """test analysis functions with empty coverage"""
        from covtool.drcov import CoverageData, FileHeader, ModuleTableVersion

        empty_data = CoverageData(
            header=FileHeader(flavor="empty"),
            modules=[],
            basic_blocks=[],
            module_version=ModuleTableVersion.V2,
        )
        empty_cov = CoverageSet(empty_data)

        # should not crash
        data = _generate_coverage_data(empty_cov, "empty.drcov")
        assert data["summary"]["total_blocks"] == 0
        assert data["summary"]["total_modules"] == 0
        assert len(data["modules"]) == 0

    def test_filtered_analysis(self):
        """test analysis with module filtering"""
        cov = self.create_test_coverage("filtered_test", 4)

        # filter to just one module
        filtered = cov.filter_by_module("program")
        data = _generate_coverage_data(filtered, "test.drcov", "program")

        # should only have blocks from the program module
        program_blocks = sum(1 for m in data["modules"] if m["name"] == "program")
        assert program_blocks >= 1

        # total blocks should be less than original
        assert data["summary"]["total_blocks"] < 4


class TestRichOutput:
    """test rich console output"""

    def create_large_coverage(self):
        """create coverage with many modules and blocks for rich display testing"""
        b = builder()
        b.set_flavor("rich_test")

        # add multiple modules
        modules = [
            ("/bin/program", 0x400000, 0x450000),
            ("/lib/libc.so.6", 0x7FFF00000000, 0x7FFF00100000),
            ("/lib/libm.so.6", 0x7FFE00000000, 0x7FFE00100000),
            ("/usr/lib/libssl.so", 0x7FFD00000000, 0x7FFD00100000),
        ]

        for i, (path, base, end) in enumerate(modules):
            b.add_module(path, base, end)

            # add several blocks per module
            for j in range(3):
                offset = 0x1000 + (j * 0x1000)
                size = 32 + (j * 16)
                b.add_coverage(i, offset, size)

        return CoverageSet(b.build())

    def test_print_detailed_info_rich_comprehensive(self, capsys):
        """test rich output with comprehensive data"""
        cov = self.create_large_coverage()

        # should not crash and should produce rich output
        print_detailed_info_rich(cov, "large_test.drcov")

        captured = capsys.readouterr()
        # output goes to rich console, so we might not capture it all
        # but this verifies the function doesn't crash

    def test_address_space_analysis(self):
        """test address space analysis in coverage data"""
        cov = self.create_large_coverage()
        data = _generate_coverage_data(cov, "addr_test.drcov")

        addr_space = data["address_space"]
        assert "min_address" in addr_space
        assert "max_address" in addr_space
        assert "range_bytes" in addr_space
        assert "range_mb" in addr_space

    def test_block_size_distribution(self):
        """test block size distribution analysis"""
        cov = self.create_large_coverage()
        data = _generate_coverage_data(cov, "size_test.drcov")

        distribution = data["block_size_distribution"]
        assert len(distribution) > 0

        for item in distribution:
            assert "size" in item
            assert "count" in item
            assert "percentage" in item

    def test_sample_blocks(self):
        """test sample blocks in analysis data"""
        cov = self.create_large_coverage()
        # provide a module filter to trigger sample_blocks generation
        data = _generate_coverage_data(cov, "sample_test.drcov", "program")

        sample_blocks = data["sample_blocks"]
        assert len(sample_blocks) > 0

        for module_name, blocks in sample_blocks.items():
            assert len(blocks) > 0
            for block in blocks:
                assert "offset" in block
                assert "size" in block
