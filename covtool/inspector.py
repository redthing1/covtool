"""interactive tui inspector for coverage traces using simple terminal control"""

import sys
import os
import termios
import tty
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict, Counter

from .core import CoverageSet, BasicBlock, Module


def getch():
    """get a single character from stdin without echoing"""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.cbreak(fd)
        ch = sys.stdin.read(1)
        if ch == '\x1b':  # escape sequence
            ch += sys.stdin.read(2)
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def clear_screen():
    """clear the terminal screen"""
    os.system('clear' if os.name == 'posix' else 'cls')


def move_cursor(row, col):
    """move cursor to position"""
    print(f"\033[{row};{col}H", end="")


def hide_cursor():
    """hide the cursor"""
    print("\033[?25l", end="")


def show_cursor():
    """show the cursor"""
    print("\033[?25h", end="")


class CoverageInspector:
    """simple tui inspector for coverage traces"""
    
    def __init__(self, coverage: CoverageSet, filename: str):
        self.coverage = coverage
        self.filename = filename
        self.filtered_coverage = coverage
        self.current_filter = ""
        
        # ui state
        self.current_view = "modules"  # modules, blocks, stats
        self.selected_module = 0
        self.scroll_offset = 0
        self.module_list = []
        self.block_list = []
        
        # terminal dimensions
        self.height = 24
        self.width = 80
        self._update_dimensions()
        
        self._setup_data()
    
    def _update_dimensions(self):
        """get current terminal dimensions"""
        try:
            import shutil
            self.width, self.height = shutil.get_terminal_size()
        except:
            pass
    
    def _setup_data(self):
        """prepare data for display"""
        self._refresh_module_list()
        self._refresh_block_list()
    
    def _refresh_module_list(self):
        """refresh the module list for current filtered coverage"""
        by_module = self.filtered_coverage.get_coverage_by_module()
        self.module_list = []
        
        for module_name, blocks in sorted(by_module.items(), key=lambda x: len(x[1]), reverse=True):
            block_count = len(blocks)
            total_size = sum(block.size for block in blocks)
            self.module_list.append({
                'name': module_name,
                'blocks': blocks,
                'count': block_count,
                'size': total_size
            })
    
    def _refresh_block_list(self):
        """refresh the block list for current filtered coverage"""
        self.block_list = []
        
        for block in sorted(self.filtered_coverage.blocks, key=lambda b: (b.module_id, b.offset)):
            module = self.filtered_coverage.modules.get(block.module_id)
            module_name = module.name if module else f"module_{block.module_id}"
            abs_addr = module.base + block.offset if module else None
            
            self.block_list.append({
                'block': block,
                'module_name': module_name,
                'abs_addr': abs_addr
            })
    
    def _apply_filter(self, filter_text: str):
        """apply module filter"""
        self.current_filter = filter_text
        if filter_text.strip():
            self.filtered_coverage = self.coverage.filter_by_module(filter_text.strip())
        else:
            self.filtered_coverage = self.coverage
        
        self._refresh_module_list()
        self._refresh_block_list()
        self.selected_module = 0
        self.scroll_offset = 0
    
    def _draw_header(self):
        """draw the header"""
        filter_text = f" (filter: {self.current_filter})" if self.current_filter else ""
        title = f"Coverage Inspector - {self.filename}{filter_text}"
        
        # truncate if too long
        if len(title) > self.width - 2:
            title = title[:self.width - 5] + "..."
        
        print("+" + "=" * (self.width - 2) + "+")
        print(f"| {title:<{self.width - 4}} |")
        print("+" + "=" * (self.width - 2) + "+")
    
    def _draw_footer(self):
        """draw the footer with commands"""
        commands = "[1/m]odules [2/b]locks [3/s]tats [f]ilter [r]eset [q]uit"
        if self.current_view == "modules":
            nav_help = " j/k:navigate enter:filter"
            commands += nav_help
        
        # truncate if too long
        if len(commands) > self.width - 2:
            commands = commands[:self.width - 5] + "..."
        
        print("+" + "-" * (self.width - 2) + "+")
        print(f"| {commands:<{self.width - 4}} |")
        print("+" + "=" * (self.width - 2) + "+")
    
    def _draw_modules_view(self):
        """draw the modules view"""
        if not self.module_list:
            print("| No modules found" + " " * (self.width - 20) + "|")
            return
        
        # header
        header = f"{'Module':<30} {'Blocks':<10} {'Size':<12} {'%':<6}"
        print(f"| {header:<{self.width - 4}} |")
        print("+" + "-" * (self.width - 2) + "+")
        
        # calculate visible range
        content_height = self.height - 6  # header + footer
        visible_start = self.scroll_offset
        visible_end = min(visible_start + content_height, len(self.module_list))
        
        # adjust selected module to be visible
        if self.selected_module < visible_start:
            self.scroll_offset = self.selected_module
        elif self.selected_module >= visible_end:
            self.scroll_offset = self.selected_module - content_height + 1
            if self.scroll_offset < 0:
                self.scroll_offset = 0
        
        # redraw visible range
        visible_start = self.scroll_offset
        visible_end = min(visible_start + content_height, len(self.module_list))
        
        for i in range(visible_start, visible_end):
            mod_info = self.module_list[i]
            percentage = (mod_info['count'] / len(self.filtered_coverage)) * 100 if self.filtered_coverage else 0
            marker = ">" if i == self.selected_module else " "
            
            # truncate module name if too long
            mod_name = mod_info['name']
            if len(mod_name) > 29:
                mod_name = mod_name[:26] + "..."
            
            line = f"{marker}{mod_name:<29} {mod_info['count']:<10,} {mod_info['size']:<12,} {percentage:<5.1f}%"
            if len(line) > self.width - 4:
                line = line[:self.width - 7] + "..."
            
            print(f"| {line:<{self.width - 4}} |")
        
        # fill remaining space
        for _ in range(visible_end - visible_start, content_height):
            print("|" + " " * (self.width - 2) + "|")
    
    def _draw_blocks_view(self):
        """draw the blocks view"""
        if not self.block_list:
            print("| No blocks found" + " " * (self.width - 19) + "|")
            return
        
        # header
        header = f"{'Offset':<12} {'Size':<6} {'Module':<20} {'Absolute':<12}"
        print(f"| {header:<{self.width - 4}} |")
        print("+" + "-" * (self.width - 2) + "+")
        
        # show first blocks that fit
        content_height = self.height - 6
        display_blocks = self.block_list[:content_height]
        
        for block_info in display_blocks:
            block = block_info['block']
            abs_addr_str = f"0x{block_info['abs_addr']:x}" if block_info['abs_addr'] else "unknown"
            
            # truncate module name if too long
            mod_name = block_info['module_name']
            if len(mod_name) > 19:
                mod_name = mod_name[:16] + "..."
            
            line = f"0x{block.offset:08x} {block.size:<6} {mod_name:<20} {abs_addr_str}"
            if len(line) > self.width - 4:
                line = line[:self.width - 7] + "..."
            
            print(f"| {line:<{self.width - 4}} |")
        
        # show count if truncated
        if len(self.block_list) > content_height:
            remaining = len(self.block_list) - content_height
            line = f"... ({remaining:,} more blocks)"
            print(f"| {line:<{self.width - 4}} |")
            content_height -= 1
        
        # fill remaining space
        for _ in range(len(display_blocks), content_height):
            print("|" + " " * (self.width - 2) + "|")
    
    def _draw_stats_view(self):
        """draw the stats view"""
        cov = self.filtered_coverage
        content_height = self.height - 6
        lines_drawn = 0
        
        # basic stats
        stats = [
            f"Total blocks: {len(cov):,}",
            f"Total modules: {len(cov.modules):,}",
        ]
        
        if cov.blocks:
            total_size = sum(block.size for block in cov.blocks)
            avg_size = total_size / len(cov.blocks)
            min_size = min(block.size for block in cov.blocks)
            max_size = max(block.size for block in cov.blocks)
            
            stats.extend([
                f"Total coverage: {total_size:,} bytes",
                f"Average block size: {avg_size:.1f} bytes",
                f"Size range: {min_size} - {max_size} bytes",
            ])
            
            # address space
            addresses = cov.get_absolute_addresses()
            if addresses:
                min_addr = min(addresses)
                max_addr = max(addresses)
                addr_range = max_addr - min_addr
                
                stats.extend([
                    "",
                    f"Address range: 0x{min_addr:x} - 0x{max_addr:x}",
                    f"Span: {addr_range:,} bytes ({addr_range / 1024 / 1024:.1f} MB)",
                ])
        
        # draw stats
        for stat in stats[:content_height]:
            print(f"| {stat:<{self.width - 4}} |")
            lines_drawn += 1
        
        # fill remaining space
        for _ in range(lines_drawn, content_height):
            print("|" + " " * (self.width - 2) + "|")
    
    def _draw_screen(self):
        """draw the entire screen"""
        clear_screen()
        move_cursor(1, 1)
        
        self._draw_header()
        
        if self.current_view == "modules":
            self._draw_modules_view()
        elif self.current_view == "blocks":
            self._draw_blocks_view()
        elif self.current_view == "stats":
            self._draw_stats_view()
        
        self._draw_footer()
        sys.stdout.flush()
    
    def _get_filter_input(self):
        """get filter input from user"""
        show_cursor()
        clear_screen()
        print(f"Current filter: {self.current_filter}")
        print("Enter new filter (empty to clear): ", end="")
        sys.stdout.flush()
        
        try:
            filter_text = input().strip()
            self._apply_filter(filter_text)
        except (KeyboardInterrupt, EOFError):
            pass
        
        hide_cursor()
    
    def _handle_key(self, key: str) -> bool:
        """handle keypress, return False to quit"""
        if key in ('q', 'Q'):
            return False
        
        elif key in ('1', 'm'):
            self.current_view = "modules"
        
        elif key in ('2', 'b'):
            self.current_view = "blocks"
        
        elif key in ('3', 's'):
            self.current_view = "stats"
        
        elif key == 'f':
            self._get_filter_input()
        
        elif key == 'r':
            self._apply_filter("")
        
        elif key in ('j', '\x1b[B') and self.current_view == "modules":  # j or down arrow
            if self.module_list and self.selected_module < len(self.module_list) - 1:
                self.selected_module += 1
        
        elif key in ('k', '\x1b[A') and self.current_view == "modules":  # k or up arrow
            if self.module_list and self.selected_module > 0:
                self.selected_module -= 1
        
        elif key in ('\n', '\r') and self.current_view == "modules" and self.module_list:
            # filter to selected module
            selected_mod = self.module_list[self.selected_module]
            self._apply_filter(selected_mod['name'])
            self.current_view = "blocks"
        
        return True
    
    def run(self):
        """run the tui inspector"""
        try:
            hide_cursor()
            
            while True:
                self._update_dimensions()
                self._draw_screen()
                
                key = getch()
                if not self._handle_key(key):
                    break
                    
        except KeyboardInterrupt:
            pass
        finally:
            show_cursor()
            clear_screen()


def run_inspector(coverage: CoverageSet, filename: str) -> None:
    """run the coverage inspector tui"""
    inspector = CoverageInspector(coverage, filename)
    inspector.run()