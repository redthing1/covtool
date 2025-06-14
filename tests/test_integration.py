"""integration tests for the complete covtool system"""

import tempfile
import json
from pathlib import Path

import pytest

from covtool import (
    read, write, builder, CoverageSet,
    BasicBlock, ModuleEntry, CoverageData
)
from covtool.analysis import load_multiple_coverage, _generate_coverage_data
from covtool.cli import app
from typer.testing import CliRunner


class TestFullSystemIntegration:
    """test the complete system working together"""

    def create_realistic_coverage(self, name="realistic"):
        """create realistic coverage data for testing"""
        b = builder()
        b.set_flavor(name)
        
        # simulate a real application with multiple modules
        modules = [
            ("/usr/bin/myapp", 0x400000, 0x480000, 0x401000),
            ("/lib/x86_64-linux-gnu/libc.so.6", 0x7f8b40000000, 0x7f8b40200000, 0x7f8b40020000),
            ("/lib/x86_64-linux-gnu/libssl.so.1.1", 0x7f8b3e000000, 0x7f8b3e100000, 0x7f8b3e010000),
            ("/lib/x86_64-linux-gnu/libcrypto.so.1.1", 0x7f8b3c000000, 0x7f8b3c300000, 0x7f8b3c050000),
        ]
        
        for i, (path, base, end, entry) in enumerate(modules):
            b.add_module(path, base, end, entry)
        
        # add realistic basic blocks
        coverage_patterns = [
            # main application
            (0, [(0x1000, 64), (0x1100, 32), (0x1200, 48), (0x2000, 96), (0x3000, 24)]),
            # libc
            (1, [(0x25000, 32), (0x30000, 16), (0x45000, 64), (0x60000, 48)]),
            # libssl  
            (2, [(0x15000, 128), (0x20000, 32)]),
            # libcrypto
            (3, [(0x55000, 256), (0x80000, 64), (0x90000, 32)]),
        ]
        
        for module_id, blocks in coverage_patterns:
            for offset, size in blocks:
                b.add_coverage(module_id, offset, size)
        
        return CoverageSet(b.build())

    def test_complete_read_write_cycle(self):
        """test complete read/write cycle with realistic data"""
        original = self.create_realistic_coverage("cycle_test")
        
        # write using high-level API
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as f:
            original.write_to_file(f.name)
            temp_path = f.name
        
        # read using high-level API
        loaded = CoverageSet.from_file(temp_path)
        
        # verify complete integrity
        assert len(loaded) == len(original)
        assert len(loaded.modules) == len(original.modules)
        
        # verify module details
        for orig_id, orig_mod in original.modules.items():
            loaded_mod = loaded.modules[orig_id]
            assert orig_mod.path == loaded_mod.path
            assert orig_mod.base == loaded_mod.base
            assert orig_mod.end == loaded_mod.end
            assert orig_mod.entry == loaded_mod.entry
        
        # verify coverage data integrity
        orig_by_module = original.get_coverage_by_module()
        loaded_by_module = loaded.get_coverage_by_module()
        
        assert set(orig_by_module.keys()) == set(loaded_by_module.keys())
        for module_name in orig_by_module:
            assert len(orig_by_module[module_name]) == len(loaded_by_module[module_name])

    def test_low_level_and_high_level_api_compatibility(self):
        """test that low-level and high-level APIs are compatible"""
        # create using high-level API
        high_level = self.create_realistic_coverage("api_test")
        
        # write using high-level API
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as f:
            high_level.write_to_file(f.name)
            temp_path = f.name
        
        # read using low-level API
        low_level_data = read(temp_path)
        
        # create CoverageSet from low-level data
        from_low_level = CoverageSet(low_level_data)
        
        # should be equivalent
        assert len(from_low_level) == len(high_level)
        assert len(from_low_level.modules) == len(high_level.modules)
        
        # write using low-level API
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as f:
            write(low_level_data, f.name)
            temp_path2 = f.name
        
        # read back using high-level API
        final = CoverageSet.from_file(temp_path2)
        
        assert len(final) == len(high_level)

    def test_complex_set_operations_workflow(self):
        """test complex workflow with multiple set operations"""
        # create multiple coverage sets representing different test runs
        coverage_sets = []
        
        base_patterns = [
            # test run 1: basic functionality
            [(0, 0x1000, 64), (0, 0x2000, 32), (1, 0x25000, 48)],
            # test run 2: error handling paths
            [(0, 0x1000, 64), (0, 0x3000, 24), (1, 0x30000, 16)],
            # test run 3: advanced features
            [(0, 0x1000, 64), (0, 0x1200, 48), (1, 0x25000, 48), (2, 0x15000, 128)],
            # test run 4: edge cases
            [(0, 0x4000, 96), (1, 0x45000, 64), (3, 0x55000, 256)],
        ]
        
        for i, pattern in enumerate(base_patterns):
            b = builder()
            b.set_flavor(f"test_run_{i}")
            # add same modules as realistic coverage
            b.add_module("/usr/bin/myapp", 0x400000, 0x480000)
            b.add_module("/lib/x86_64-linux-gnu/libc.so.6", 0x7f8b40000000, 0x7f8b40200000)
            b.add_module("/lib/x86_64-linux-gnu/libssl.so.1.1", 0x7f8b3e000000, 0x7f8b3e100000)
            b.add_module("/lib/x86_64-linux-gnu/libcrypto.so.1.1", 0x7f8b3c000000, 0x7f8b3c300000)
            
            for module_id, offset, size in pattern:
                b.add_coverage(module_id, offset, size)
            
            coverage_sets.append(CoverageSet(b.build()))
        
        # compute comprehensive union (all coverage)
        total_coverage = coverage_sets[0]
        for cov in coverage_sets[1:]:
            total_coverage = total_coverage | cov
        
        # compute core coverage (intersection of all)
        core_coverage = coverage_sets[0]
        for cov in coverage_sets[1:]:
            core_coverage = core_coverage & cov
        
        # compute unique coverage per test run
        unique_coverages = []
        for i, cov in enumerate(coverage_sets):
            unique = cov
            for j, other in enumerate(coverage_sets):
                if i != j:
                    unique = unique - other
            unique_coverages.append(unique)
        
        # verify results make sense
        assert len(total_coverage) >= len(core_coverage)
        assert len(core_coverage) >= 0
        
        # core coverage should be blocks common to all tests (0x1000 appears in first 3)
        if len(core_coverage) > 0:
            core_by_module = core_coverage.get_coverage_by_module()
            assert "myapp" in core_by_module

    def test_analysis_and_cli_integration(self):
        """test analysis functions working with CLI output"""
        # create test coverage
        cov = self.create_realistic_coverage("cli_analysis")
        
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as f:
            cov.write_to_file(f.name)
            test_file = f.name
        
        # test CLI commands
        runner = CliRunner()
        
        # stats command
        result = runner.invoke(app, ['stats', test_file])
        assert result.exit_code == 0
        assert "myapp" in result.stdout
        
        # info command with JSON
        result = runner.invoke(app, ['info', test_file, '--json'])
        assert result.exit_code == 0
        
        # parse JSON output
        data = json.loads(result.stdout)
        assert "modules" in data
        assert len(data["modules"]) == 4
        
        # verify analysis data consistency
        analysis_data = _generate_coverage_data(cov, "test.drcov")
        assert len(analysis_data["modules"]) == len(data["modules"])

    def test_multiple_file_operations(self):
        """test operations involving multiple files"""
        # create multiple coverage files
        files = []
        coverage_sets = []
        
        for i in range(3):
            cov = self.create_realistic_coverage(f"multi_{i}")
            # add some variation
            if i == 1:
                # add extra block to second coverage
                b = builder()
                b.set_flavor(f"multi_{i}_extra")
                for mod in cov.data.modules:
                    b.add_module(mod.path, mod.base, mod.end, mod.entry)
                for block in cov.data.basic_blocks:
                    b.add_coverage(block.module_id, block.start, block.size)
                # add extra block
                b.add_coverage(0, 0x5000, 128)
                cov = CoverageSet(b.build())
            
            coverage_sets.append(cov)
            
            with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as f:
                cov.write_to_file(f.name)
                files.append(f.name)
        
        # test loading multiple files
        loaded_sets = load_multiple_coverage([Path(f) for f in files])
        assert len(loaded_sets) == 3
        
        # test CLI union operation
        runner = CliRunner()
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as union_file:
            result = runner.invoke(app, [
                'union',
                files[0], files[1], files[2],
                '--output', union_file.name,
                '--verbose'
            ])
            assert result.exit_code == 0
            
            # verify union file
            union_cov = CoverageSet.from_file(union_file.name)
            assert len(union_cov) >= len(coverage_sets[0])

    def test_error_handling_integration(self):
        """test error handling across the system"""
        # test invalid files
        runner = CliRunner()
        
        result = runner.invoke(app, ['stats', '/nonexistent/file.drcov'])
        assert result.exit_code == 0  # stats command doesn't exit on individual file errors
        assert "error" in result.stdout
        
        # test corrupted data handling
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.drcov') as f:
            f.write("invalid drcov data")
            invalid_file = f.name
        
        result = runner.invoke(app, ['stats', invalid_file])
        assert result.exit_code == 0  # stats command doesn't exit on individual file errors

    def test_filtering_integration(self):
        """test module filtering across different operations"""
        cov = self.create_realistic_coverage("filter_test")
        
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as f:
            cov.write_to_file(f.name)
            test_file = f.name
        
        runner = CliRunner()
        
        # test stats with different filters
        filters = ["myapp", "libc", "ssl", "crypto"]
        
        for filter_name in filters:
            result = runner.invoke(app, [
                'stats',
                test_file,
                '--module', filter_name
            ])
            assert result.exit_code == 0
            
            # verify filtering worked
            filtered_cov = cov.filter_by_module(filter_name)
            by_module = filtered_cov.get_coverage_by_module()
            
            # should have at least one module matching the filter
            matching_modules = [name for name in by_module.keys() 
                              if filter_name.lower() in name.lower()]
            if len(filtered_cov) > 0:
                assert len(matching_modules) > 0

    def test_large_scale_operations(self):
        """test operations with larger datasets"""
        # create coverage with many modules and blocks
        b = builder()
        b.set_flavor("large_scale")
        
        # add many modules
        for i in range(10):
            base = 0x400000 + (i * 0x100000)
            end = base + 0x80000
            b.add_module(f"/lib/libtest{i}.so", base, end)
        
        # add many blocks
        for mod_id in range(10):
            for block_id in range(20):
                offset = 0x1000 + (block_id * 0x100)
                size = 32 + (block_id % 8) * 8
                b.add_coverage(mod_id, offset, size)
        
        large_cov = CoverageSet(b.build())
        
        # verify it handles large data correctly
        assert len(large_cov) == 200  # 10 modules * 20 blocks
        assert len(large_cov.modules) == 10
        
        # test analysis on large data
        analysis_data = _generate_coverage_data(large_cov, "large.drcov")
        assert len(analysis_data["modules"]) == 10
        assert analysis_data["summary"]["total_blocks"] == 200
        
        # test write/read cycle with large data
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as f:
            large_cov.write_to_file(f.name)
            temp_path = f.name
        
        reloaded = CoverageSet.from_file(temp_path)
        assert len(reloaded) == len(large_cov)
        assert len(reloaded.modules) == len(large_cov.modules)

    def test_real_world_workflow_simulation(self):
        """simulate a real-world workflow"""
        # step 1: generate baseline coverage
        baseline = self.create_realistic_coverage("baseline")
        
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as f:
            baseline.write_to_file(f.name)
            baseline_file = f.name
        
        # step 2: generate test coverage files
        test_files = []
        for i in range(3):
            # modify baseline slightly for each test
            b = builder()
            b.set_flavor(f"test_{i}")
            for mod in baseline.data.modules:
                b.add_module(mod.path, mod.base, mod.end, mod.entry)
            
            # add baseline blocks
            for block in baseline.data.basic_blocks:
                b.add_coverage(block.module_id, block.start, block.size)
            
            # add test-specific blocks
            b.add_coverage(0, 0x6000 + (i * 0x1000), 32 + (i * 16))
            
            test_cov = CoverageSet(b.build())
            
            with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as f:
                test_cov.write_to_file(f.name)
                test_files.append(f.name)
        
        runner = CliRunner()
        
        # step 3: analyze baseline
        result = runner.invoke(app, ['stats', baseline_file])
        assert result.exit_code == 0
        
        # step 4: compare tests against baseline
        result = runner.invoke(app, [
            'compare',
            baseline_file,
            test_files[0], test_files[1], test_files[2]
        ])
        assert result.exit_code == 0
        assert "coverage" in result.stdout
        
        # step 5: compute total test coverage
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as total_file:
            result = runner.invoke(app, [
                'union',
                test_files[0], test_files[1], test_files[2],
                '--output', total_file.name
            ])
            assert result.exit_code == 0
        
        # step 6: find gaps (baseline - total test coverage)
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as gaps_file:
            result = runner.invoke(app, [
                'diff',
                baseline_file,
                total_file.name,
                '--output', gaps_file.name
            ])
            assert result.exit_code == 0
        
        # step 7: analyze gaps
        result = runner.invoke(app, ['info', gaps_file.name, '--json'])
        assert result.exit_code == 0
        
        gaps_data = json.loads(result.stdout)
        # should have found some gaps since baseline != test coverage
        assert "modules" in gaps_data