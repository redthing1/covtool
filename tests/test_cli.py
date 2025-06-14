"""tests for command line interface"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from covtool.cli import app
from covtool.core import CoverageSet
from covtool.drcov import builder


class TestCLICommands:
    """test CLI command functionality"""

    def create_test_files(self, count=2):
        """create temporary test coverage files"""
        files = []
        
        for i in range(count):
            b = builder()
            b.set_flavor(f"test{i}")
            b.add_module(f"/bin/prog{i}", 0x400000 + (i * 0x100000), 0x500000 + (i * 0x100000))
            b.add_coverage(0, 0x1000, 32)
            b.add_coverage(0, 0x2000, 16)
            if i % 2 == 0:  # add common block for intersection tests
                b.add_coverage(0, 0x3000, 24)
            
            cov = CoverageSet(b.build())
            
            with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as f:
                cov.write_to_file(f.name)
                files.append(f.name)
        
        return files

    def test_union_command(self):
        """test union command"""
        runner = CliRunner()
        files = self.create_test_files(2)
        
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as out_file:
            result = runner.invoke(app, [
                'union',
                files[0], files[1],
                '--output', out_file.name
            ])
        
        assert result.exit_code == 0
        assert "wrote" in result.stdout
        assert "blocks to" in result.stdout

    def test_union_command_verbose(self):
        """test union command with verbose output"""
        runner = CliRunner()
        files = self.create_test_files(2)
        
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as out_file:
            result = runner.invoke(app, [
                'union',
                files[0], files[1],
                '--output', out_file.name,
                '--verbose'
            ])
        
        assert result.exit_code == 0
        assert "union of 2 files" in result.stdout

    def test_intersect_command(self):
        """test intersect command"""
        runner = CliRunner()
        files = self.create_test_files(2)
        
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as out_file:
            result = runner.invoke(app, [
                'intersect',
                files[0], files[1],
                '--output', out_file.name
            ])
        
        assert result.exit_code == 0
        assert "wrote" in result.stdout

    def test_diff_command(self):
        """test diff command"""
        runner = CliRunner()
        files = self.create_test_files(2)
        
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as out_file:
            result = runner.invoke(app, [
                'diff',
                files[0], files[1],
                '--output', out_file.name
            ])
        
        assert result.exit_code == 0
        assert "wrote" in result.stdout

    def test_symdiff_command(self):
        """test symmetric difference command"""
        runner = CliRunner()
        files = self.create_test_files(2)
        
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as out_file:
            result = runner.invoke(app, [
                'symdiff',
                files[0], files[1],
                '--output', out_file.name
            ])
        
        assert result.exit_code == 0
        assert "wrote" in result.stdout

    def test_stats_command(self):
        """test stats command"""
        runner = CliRunner()
        files = self.create_test_files(1)
        
        result = runner.invoke(app, [
            'stats',
            files[0]
        ])
        
        assert result.exit_code == 0
        assert "basic blocks:" in result.stdout
        assert "modules:" in result.stdout

    def test_stats_command_with_module_filter(self):
        """test stats command with module filter"""
        runner = CliRunner()
        files = self.create_test_files(1)
        
        result = runner.invoke(app, [
            'stats',
            files[0],
            '--module', 'prog'
        ])
        
        assert result.exit_code == 0
        assert "basic blocks:" in result.stdout

    def test_rarity_command(self):
        """test rarity analysis command"""
        runner = CliRunner()
        files = self.create_test_files(3)
        
        result = runner.invoke(app, [
            'rarity',
            files[0], files[1], files[2],
            '--threshold', '2'
        ])
        
        assert result.exit_code == 0
        assert "rarity analysis" in result.stdout

    def test_info_command(self):
        """test info command"""
        runner = CliRunner()
        files = self.create_test_files(1)
        
        result = runner.invoke(app, [
            'info',
            files[0]
        ])
        
        assert result.exit_code == 0
        # rich output might not be captured perfectly

    def test_info_command_json(self):
        """test info command with JSON output"""
        runner = CliRunner()
        files = self.create_test_files(1)
        
        result = runner.invoke(app, [
            'info',
            files[0],
            '--json'
        ])
        
        assert result.exit_code == 0
        # should produce JSON output
        assert "{" in result.stdout
        assert "filename" in result.stdout

    def test_compare_command(self):
        """test compare command"""
        runner = CliRunner()
        files = self.create_test_files(3)
        
        result = runner.invoke(app, [
            'compare',
            files[0],  # baseline
            files[1], files[2]  # targets
        ])
        
        assert result.exit_code == 0
        assert "baseline:" in result.stdout
        assert "coverage" in result.stdout

    def test_module_filter_option(self):
        """test module filter option across commands"""
        runner = CliRunner()
        files = self.create_test_files(2)
        
        # test union with module filter
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as out_file:
            result = runner.invoke(app, [
                'union',
                files[0], files[1],
                '--output', out_file.name,
                '--module', 'prog0'
            ])
        
        assert result.exit_code == 0

    def test_error_handling(self):
        """test error handling for various scenarios"""
        runner = CliRunner()
        
        # test with non-existent file
        result = runner.invoke(app, [
            'stats',
            '/nonexistent/file.drcov'
        ])
        
        assert result.exit_code == 0  # stats command doesn't exit on individual file errors
        assert "error" in result.stdout

        # test union with missing output
        result = runner.invoke(app, [
            'union',
            '/nonexistent/file1.drcov',
            '/nonexistent/file2.drcov'
        ])
        
        # should fail due to missing --output
        assert result.exit_code != 0

    def test_no_args(self):
        """test CLI with no arguments shows help"""
        runner = CliRunner()
        result = runner.invoke(app, [])
        
        # typer should show help
        assert result.exit_code == 0
        assert "Usage:" in result.stdout

    def test_help_option(self):
        """test help option"""
        runner = CliRunner()
        result = runner.invoke(app, ['--help'])
        
        assert result.exit_code == 0
        assert "Usage:" in result.stdout
        assert "powerful drcov coverage analysis" in result.stdout

    def test_command_help(self):
        """test individual command help"""
        runner = CliRunner()
        result = runner.invoke(app, ['union', '--help'])
        
        assert result.exit_code == 0
        assert "compute union" in result.stdout

    @patch('covtool.cli.run_inspector')
    def test_inspect_command(self, mock_inspector):
        """test inspect command (mocked to avoid TUI)"""
        runner = CliRunner()
        files = self.create_test_files(1)
        
        result = runner.invoke(app, [
            'inspect',
            files[0]
        ])
        
        # should call the inspector
        mock_inspector.assert_called_once()
        assert result.exit_code == 0


class TestCLIIntegration:
    """integration tests for CLI functionality"""

    def test_full_workflow(self):
        """test a complete workflow using CLI commands"""
        runner = CliRunner()
        
        # create test files
        files = []
        for i in range(3):
            b = builder()
            b.set_flavor(f"workflow{i}")
            b.add_module("/bin/app", 0x400000, 0x500000)
            b.add_coverage(0, 0x1000 + (i * 0x1000), 32)
            b.add_coverage(0, 0x2000, 16)  # common block
            
            cov = CoverageSet(b.build())
            
            with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as f:
                cov.write_to_file(f.name)
                files.append(f.name)
        
        # step 1: get stats for each file
        for file in files:
            result = runner.invoke(app, ['stats', file])
            assert result.exit_code == 0
        
        # step 2: compute union
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as union_file:
            result = runner.invoke(app, [
                'union',
                files[0], files[1], files[2],
                '--output', union_file.name,
                '--verbose'
            ])
            assert result.exit_code == 0
            
            # step 3: get stats for union
            result = runner.invoke(app, ['stats', union_file.name])
            assert result.exit_code == 0
        
        # step 4: compute intersection of first two
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as intersect_file:
            result = runner.invoke(app, [
                'intersect',
                files[0], files[1],
                '--output', intersect_file.name
            ])
            assert result.exit_code == 0
        
        # step 5: compare all files
        result = runner.invoke(app, [
            'compare',
            files[0],  # baseline
            files[1], files[2]  # targets
        ])
        assert result.exit_code == 0

    def test_module_filtering_workflow(self):
        """test workflow with module filtering"""
        runner = CliRunner()
        
        # create coverage with multiple modules
        b = builder()
        b.set_flavor("multi_module")
        b.add_module("/bin/app", 0x400000, 0x500000)
        b.add_module("/lib/libc.so", 0x7fff00000000, 0x7fff00100000)
        b.add_coverage(0, 0x1000, 32)  # app block
        b.add_coverage(1, 0x1000, 16)  # libc block
        
        cov = CoverageSet(b.build())
        
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as f:
            cov.write_to_file(f.name)
            test_file = f.name
        
        # test filtering to app module
        result = runner.invoke(app, [
            'stats',
            test_file,
            '--module', 'app'
        ])
        assert result.exit_code == 0
        
        # test filtering to libc module  
        result = runner.invoke(app, [
            'stats',
            test_file,
            '--module', 'libc'
        ])
        assert result.exit_code == 0

    def test_error_recovery(self):
        """test CLI error recovery"""
        runner = CliRunner()
        
        # create one valid and one invalid file
        b = builder()
        b.add_module("/bin/test", 0x400000, 0x500000)
        b.add_coverage(0, 0x1000, 32)
        cov = CoverageSet(b.build())
        
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.drcov') as f:
            cov.write_to_file(f.name)
            valid_file = f.name
        
        invalid_file = "/nonexistent/file.drcov"
        
        # stats command should handle the error gracefully
        result = runner.invoke(app, [
            'stats',
            valid_file,
            invalid_file
        ])
        
        # should process the valid file and report error for invalid
        assert "error analyzing" in result.stdout
        assert "basic blocks:" in result.stdout