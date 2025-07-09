"""Main CoverageInspector class and utilities"""

import os
import urwid
from collections import defaultdict

from ..core import CoverageSet
from .dialogs import (
    FilterDialog,
    SearchDialog,
    HitCountDialog,
    HitCountRangeDialog,
    SizeFilterDialog,
    HelpDialog,
)
from .views import ViewCreator


class CoverageInspector:
    """TUI inspector for coverage traces using urwid"""

    # Layout constants
    MODULE_WIDTH_WITH_HITS = 45
    MODULE_WIDTH_NO_HITS = 50
    BLOCK_MODULE_WIDTH = 35
    MAX_BLOCKS_DISPLAY = 10000

    # Size formatting thresholds
    SIZE_MB_THRESHOLD = 1024 * 1024
    SIZE_KB_THRESHOLD = 1024
    HIT_COUNT_K_THRESHOLD = 1000
    HIT_COUNT_FORMAT_THRESHOLD = 10000

    # Dialog dimensions
    DIALOG_WIDTH = 65
    DIALOG_WIDTH_WIDE = 70
    HELP_DIALOG_HEIGHT = 16
    FILTER_DIALOG_HEIGHT = 12
    RANGE_FILTER_DIALOG_HEIGHT = 16
    SEARCH_DIALOG_HEIGHT = 16

    # Column headers and formatting
    COLUMN_SEPARATOR = " | "
    MAX_MODULE_NAME_DISPLAY = 32
    TRUNCATION_SUFFIX = "..."

    # Pagination and display limits
    DEFAULT_PAGE_SIZE = 24
    MAX_ITEMS_WARNING_THRESHOLD = 10000

    # Terminal size assumptions for navigation
    DEFAULT_TERMINAL_WIDTH = 80
    DEFAULT_TERMINAL_HEIGHT = 24

    # List view constants
    HEADER_ROWS = 2  # Header + divider
    ADDRESS_FIELD_WIDTH = 16
    SIZE_FIELD_WIDTH = 6
    HITS_FIELD_WIDTH = 8
    OFFSET_FIELD_WIDTH = 12

    def __init__(self, coverage: CoverageSet, filename: str):
        self.coverage = coverage
        self.filename = filename
        self.filtered_coverage = coverage
        self.current_filter = ""

        # UI state
        self.current_view = "modules"  # modules, blocks, stats
        self.module_list = []
        self.block_list = []
        self.scroll_offset = 0

        # Block view sorting and filtering
        self.block_sort_mode = "address"  # "address" or "hits"
        self.hitcount_filter = None  # exact hit count filter (None = show all)
        self.hitcount_range_filter = None  # range filter (None = show all)
        self.size_filter = None  # block size filter (None = show all)
        self.search_term = ""  # search term for filtering blocks/modules

        # UI components
        self.main_loop = None
        self.content_area = None
        self.main_widget = None
        self.module_listbox = None

        # View creator
        self.view_creator = ViewCreator(self)

        self._setup_data()

    def _format_size(self, size):
        """Format size with appropriate units"""
        if size >= self.SIZE_MB_THRESHOLD:
            return f"{size / self.SIZE_MB_THRESHOLD:.1f} MB"
        elif size >= self.SIZE_KB_THRESHOLD:
            return f"{size / self.SIZE_KB_THRESHOLD:.1f} KB"
        else:
            return f"{size} B"

    def _format_hit_count(self, hits):
        """Format hit count with K suffix for large numbers"""
        if hits >= self.HIT_COUNT_FORMAT_THRESHOLD:
            return f"{hits/1000:.1f}K"
        elif hits >= self.HIT_COUNT_K_THRESHOLD:
            return f"{hits:,}"
        else:
            return str(hits)

    def _truncate_module_name(self, name, has_hits=None):
        """Truncate module name based on current layout"""
        if has_hits is None:
            has_hits = self.filtered_coverage.data.has_hit_counts()

        if has_hits:
            max_len = self.MODULE_WIDTH_WITH_HITS
            truncate_len = max_len - len(self.TRUNCATION_SUFFIX)
        else:
            max_len = self.MODULE_WIDTH_NO_HITS
            truncate_len = max_len - len(self.TRUNCATION_SUFFIX)

        return (
            name[:truncate_len] + self.TRUNCATION_SUFFIX
            if len(name) > max_len
            else name
        )

    def _parse_range_filter(self, filter_str):
        """Parse range filter string into (min_val, max_val, operator)
        Supports: '10-100', '>50', '<5', '>=10', '<=100', '==50'
        Returns: (min_val, max_val, op) or None if invalid
        """
        if not filter_str or not filter_str.strip():
            return None

        filter_str = filter_str.strip()

        # Range format: "10-100"
        if "-" in filter_str and not filter_str.startswith("-"):
            parts = filter_str.split("-", 1)
            try:
                min_val = int(parts[0].strip())
                max_val = int(parts[1].strip())
                return (min_val, max_val, "range")
            except ValueError:
                return None

        # Comparison operators
        for op in [">=", "<=", "==", ">", "<"]:
            if filter_str.startswith(op):
                try:
                    val = int(filter_str[len(op) :].strip())
                    return (val, val, op)
                except ValueError:
                    return None

        # Plain number (exact match)
        try:
            val = int(filter_str)
            return (val, val, "==")
        except ValueError:
            return None

    def _matches_range_filter(self, value, range_filter):
        """Check if value matches the range filter"""
        if range_filter is None:
            return True

        min_val, max_val, op = range_filter

        if op == "range":
            return min_val <= value <= max_val
        elif op == ">=":
            return value >= min_val
        elif op == "<=":
            return value <= min_val
        elif op == ">":
            return value > min_val
        elif op == "<":
            return value < min_val
        elif op == "==":
            return value == min_val

        return True

    def _matches_search_term(self, block, module_name, abs_addr=None):
        """Check if block/module matches search term"""
        if not self.search_term:
            return True

        search_lower = self.search_term.lower()

        # Search targets in order of likelihood for better performance
        search_targets = [
            module_name.lower(),  # Module name
            f"0x{block.start:x}",  # Block offset
        ]

        # Add virtual address if available
        if abs_addr is not None:
            search_targets.append(f"0x{abs_addr:x}")

        # Add module path if available
        if hasattr(block, "module") and block.module:
            search_targets.append(block.module.path.lower())

        return any(search_lower in target for target in search_targets)

    def _passes_all_filters(self, block, hits, module_name, abs_addr):
        """Check if block passes all active filters"""
        return (
            (self.hitcount_filter is None or hits == self.hitcount_filter)
            and self._matches_range_filter(hits, self.hitcount_range_filter)
            and self._matches_range_filter(block.size, self.size_filter)
            and self._matches_search_term(block, module_name, abs_addr)
        )

    def _get_module_display_name(self, module, module_id):
        """Get display name for a module"""
        return os.path.basename(module.path) if module else f"module_{module_id}"

    def _setup_data(self):
        """Prepare data for display"""
        self._refresh_module_list()
        self._refresh_block_list()

    def _refresh_module_list(self):
        """Refresh the module list for current filtered coverage"""
        by_module = self.filtered_coverage.get_coverage_by_module_with_base()
        self.module_list = []

        total_blocks = len(self.filtered_coverage.data.basic_blocks)

        # Create block-to-index mapping for efficient hit count lookup
        block_to_index = (
            {
                block: i
                for i, block in enumerate(self.filtered_coverage.data.basic_blocks)
            }
            if self.filtered_coverage.data.has_hit_counts()
            else {}
        )

        for module_name, blocks in sorted(
            by_module.items(), key=lambda x: x[0]  # sort by module name
        ):
            # Apply search filter to modules
            if self.search_term and self.search_term.lower() not in module_name.lower():
                continue

            block_count = len(blocks)
            total_size = sum(block.size for block in blocks)
            percentage = (block_count / total_blocks * 100) if total_blocks > 0 else 0

            # Calculate hit count statistics for this module
            if self.filtered_coverage.data.has_hit_counts():
                module_hits = sum(
                    self.filtered_coverage.data.get_hit_count(block_to_index[block])
                    for block in blocks
                )
            else:
                # Default hit count of 1 for each block
                module_hits = block_count

            self.module_list.append(
                {
                    "name": module_name,
                    "blocks": blocks,
                    "count": block_count,
                    "size": total_size,
                    "percentage": percentage,
                    "hits": module_hits,
                }
            )

    def _refresh_block_list(self):
        """Refresh the block list for current filtered coverage"""
        self.block_list = []

        # Create block list with hit information
        blocks_with_hits = self.filtered_coverage.data.get_blocks_with_hits()

        # Cache modules to avoid repeated lookups
        module_cache = {}

        for block, hits in blocks_with_hits:
            # Use cached module lookup
            if block.module_id not in module_cache:
                module_cache[block.module_id] = self.filtered_coverage.data.find_module(
                    block.module_id
                )
            module = module_cache[block.module_id]
            module_name = self._get_module_display_name(module, block.module_id)
            abs_addr = module.base + block.start if module else None

            # Apply all filters
            if not self._passes_all_filters(block, hits, module_name, abs_addr):
                continue
            self.block_list.append(
                {
                    "block": block,
                    "module": module,
                    "module_name": module_name,
                    "abs_addr": abs_addr,
                    "hits": hits,
                }
            )

        # Sort blocks based on current sort mode
        self._sort_block_list()

    def _sort_block_list(self):
        """Sort block list based on current sort mode"""
        if self.block_sort_mode == "hits":
            # Sort by hits (descending), then by address
            self.block_list.sort(
                key=lambda b: (-b["hits"], b["block"].module_id, b["block"].start)
            )
        else:
            # Sort by address (module_id, then start offset)
            self.block_list.sort(key=lambda b: (b["block"].module_id, b["block"].start))

    def _apply_filter(self, filter_text: str):
        """Apply module filter"""
        self.current_filter = filter_text
        if filter_text.strip():
            # remove @0xXXXX suffix if present for filtering
            base_filter = filter_text.strip().split("@")[0]
            self.filtered_coverage = self.coverage.filter_by_module(base_filter)
        else:
            self.filtered_coverage = self.coverage

        self._refresh_module_list()
        self._refresh_block_list()
        self._update_view()
        self._update_header_footer()

    def _update_view(self):
        """Update the current view"""
        if self.current_view == "modules":
            content = self.view_creator.create_modules_view()
        elif self.current_view == "blocks":
            content = self.view_creator.create_blocks_view()
        elif self.current_view == "stats":
            content = self.view_creator.create_stats_view()
        else:
            content = urwid.Filler(urwid.Text("Unknown view"), valign="middle")

        self.content_area.original_widget = content

    def _update_header_footer(self):
        """Update header and footer"""
        # Update header with current filter
        header = self._create_header()
        footer = self._create_footer()

        self.main_widget.header = header
        self.main_widget.footer = footer

    def _create_footer(self):
        """Create clean footer with essential controls"""
        base_help = (
            "[1]Modules [2]Blocks [3]Stats [f]Filter [/]Search [r]Reset [h]Help [q]Quit"
        )

        if self.current_view == "modules":
            if self.module_list:
                module_count = len(self.module_list)
                view_help = f" • {module_count} modules"
            else:
                view_help = ""
        elif self.current_view == "blocks":
            view_help = " • [s]Sort [c]Hits [C]Range [z]Size"
        else:
            view_help = ""

        help_text = base_help + view_help

        return urwid.AttrMap(urwid.Text(help_text), "footer")

    def _create_header(self):
        """Create header with better formatting"""
        filename = os.path.basename(self.filename)

        # Create title with coverage summary
        if self.current_filter:
            title = f"Coverage Inspector: {filename} (filtered: {self.current_filter})"
        else:
            title = f"Coverage Inspector: {filename}"

        # Add quick stats with percentages
        total_blocks = len(self.coverage.data.basic_blocks)
        filtered_blocks = len(self.filtered_coverage.data.basic_blocks)

        # Add hit count info to stats
        hit_info = ""
        if self.coverage.data.has_hit_counts():
            total_hits = sum(self.coverage.data.hit_counts)
            if self.current_filter:
                filtered_hits = sum(
                    self.coverage.data.get_hit_count(i)
                    for i, block in enumerate(self.coverage.data.basic_blocks)
                    if block in self.filtered_coverage.blocks
                )
                hit_info = f" | Hits: {filtered_hits:,}/{total_hits:,}"
            else:
                hit_info = f" | Hits: {total_hits:,}"

        if self.current_filter and total_blocks > 0:
            filter_pct = (filtered_blocks / total_blocks) * 100
            stats = f"Modules: {len(self.module_list)} | Blocks: {filtered_blocks:,}/{total_blocks:,} ({filter_pct:.1f}%){hit_info}"
        else:
            stats = f"Modules: {len(self.module_list)} | Blocks: {filtered_blocks:,}{hit_info}"

        # Add view-specific status for blocks view
        view_status = ""
        if self.current_view == "blocks" and self.block_list:
            block_count = len(self.block_list)
            displayed = min(10000, block_count)

            status_parts = []
            if block_count > 10000:
                status_parts.append(f"Showing {displayed:,} of {block_count:,}")
            else:
                status_parts.append(f"{block_count:,} blocks")

            if self.block_sort_mode == "hits":
                status_parts.append("sorted by hits")
            else:
                status_parts.append("sorted by address")

            if self.hitcount_filter is not None:
                status_parts.append(f"hits={self.hitcount_filter}")

            if self.hitcount_range_filter is not None:
                min_val, max_val, op = self.hitcount_range_filter
                if op == "range":
                    status_parts.append(f"hits={min_val}-{max_val}")
                else:
                    status_parts.append(f"hits{op}{min_val}")

            if self.size_filter is not None:
                min_val, max_val, op = self.size_filter
                if op == "range":
                    status_parts.append(f"size={min_val}-{max_val}")
                else:
                    status_parts.append(f"size{op}{min_val}")

            if self.search_term:
                status_parts.append(f"search='{self.search_term}'")

            # Add general hit count info
            if self.filtered_coverage.data.has_hit_counts():
                status_parts.append("with hit counts")
            else:
                status_parts.append("no hit counts")

            view_status = " | ".join(status_parts)

        # Create multi-line header
        header_lines = [
            urwid.AttrMap(urwid.Text(title), "header_title"),
            urwid.AttrMap(urwid.Text(stats, align="center"), "header_stats"),
        ]

        if view_status:
            header_lines.append(
                urwid.AttrMap(urwid.Text(view_status, align="center"), "header_stats")
            )

        header_content = urwid.Pile(header_lines)

        return header_content

    def _handle_input(self, key):
        """Enhanced input handling"""
        if key in ("q", "Q"):
            raise urwid.ExitMainLoop()
        elif key == "1":
            self.current_view = "modules"
            self._update_view()
            self._update_header_footer()
        elif key == "2":
            self.current_view = "blocks"
            self._update_view()
            self._update_header_footer()
        elif key == "3":
            self.current_view = "stats"
            self._update_view()
            self._update_header_footer()
        elif key == "enter" and self.current_view == "modules":
            self._handle_module_selection()
        elif key == "r":
            self._reset_all_filters()
        elif key == "f":
            FilterDialog(self).show()
        elif key == "s" and self.current_view == "blocks":
            self._toggle_block_sort()
        elif key == "c" and self.current_view == "blocks":
            HitCountDialog(self).show()
        elif key == "C" and self.current_view == "blocks":
            HitCountRangeDialog(self).show()
        elif key == "z" and self.current_view == "blocks":
            SizeFilterDialog(self).show()
        elif key == "/":
            SearchDialog(self).show()
        elif key in ("h", "?"):
            HelpDialog(self).show()
        elif key == "ctrl l":
            # Refresh screen
            self._update_view()
            self._update_header_footer()
        elif key in ("j", "k", "J", "K"):
            # Vi-style navigation
            self._handle_vi_navigation(key)
        else:
            # Let the widget handle other keys (like arrow keys)
            return key

    def _handle_vi_navigation(self, key):
        """Handle vi-style navigation (j/k/J/K)"""
        # Get the current focused widget
        focused_widget = None

        if self.current_view == "modules" and self.module_listbox:
            focused_widget = self.module_listbox
        elif self.current_view == "blocks" or self.current_view == "stats":
            # For blocks and stats views, we need to get the listbox from content area
            if hasattr(self.content_area, "original_widget"):
                focused_widget = self.content_area.original_widget
                if hasattr(focused_widget, "original_widget"):
                    focused_widget = focused_widget.original_widget

        if not focused_widget or not hasattr(focused_widget, "keypress"):
            return

        # Handle different navigation keys
        terminal_size = (self.DEFAULT_TERMINAL_WIDTH, self.DEFAULT_TERMINAL_HEIGHT)
        if key == "j":
            # Move down one line
            focused_widget.keypress(terminal_size, "down")
        elif key == "k":
            # Move up one line
            focused_widget.keypress(terminal_size, "up")
        elif key == "J":
            # Page down
            focused_widget.keypress(terminal_size, "page down")
        elif key == "K":
            # Page up
            focused_widget.keypress(terminal_size, "page up")

    def _handle_module_selection(self):
        """Handle module selection in modules view"""
        if not self.module_listbox or not self.module_list:
            return

        # Get current focus position
        _, focus_pos = self.module_listbox.get_focus()

        # Skip header and divider
        if focus_pos >= self.HEADER_ROWS:
            module_index = focus_pos - self.HEADER_ROWS
            if module_index < len(self.module_list):
                selected_mod = self.module_list[module_index]
                self._apply_filter(selected_mod["name"])
                self.current_view = "blocks"

    def _toggle_block_sort(self):
        """Toggle between sorting blocks by address and hits"""
        if self.block_sort_mode == "address":
            self.block_sort_mode = "hits"
        else:
            self.block_sort_mode = "address"

        self._refresh_block_list()
        self._update_view()
        self._update_header_footer()

    def _reset_all_filters(self):
        """Reset all filters to default state"""
        self.current_filter = ""
        self.hitcount_filter = None
        self.hitcount_range_filter = None
        self.size_filter = None
        self.search_term = ""
        self.filtered_coverage = self.coverage

        self._refresh_module_list()
        self._refresh_block_list()
        self._update_view()
        self._update_header_footer()

    def run(self):
        """Run the enhanced TUI inspector"""
        try:
            # Check if we have a proper terminal - but allow override for testing
            import sys
            import os

            if not sys.stdout.isatty() and not os.getenv("FORCE_TUI"):
                print(
                    "Error: TUI requires a terminal. Please run in an interactive terminal."
                )
                print("(You can set FORCE_TUI=1 to override this check)")
                return

            # Create the main layout
            self.content_area = urwid.WidgetPlaceholder(
                urwid.Text("Loading...", align="center")
            )

            # Create main widget
            header = self._create_header()
            footer = self._create_footer()

            self.main_widget = urwid.Frame(
                self.content_area, header=header, footer=footer
            )

            # Simple color palette for maximum compatibility
            palette = [
                ("header_title", "white,bold", "dark blue"),
                ("header_stats", "light cyan", "dark blue"),
                ("footer", "white", "dark red"),
                ("selected", "white,bold", "dark green"),
                ("focus", "white", "dark blue"),
                ("title", "white,bold", "default"),
                ("subtitle", "yellow,bold", "default"),
                ("header", "white,bold", "default"),
                ("dim", "dark gray", "default"),
                ("bold", "white,bold", "default"),
            ]

            # Initial view
            self._update_view()

            # Run the main loop
            self.main_loop = urwid.MainLoop(
                self.main_widget, palette, unhandled_input=self._handle_input
            )
            self.main_loop.run()

        except KeyboardInterrupt:
            pass
        except Exception as e:
            # Fallback if urwid fails
            print(f"TUI failed to start: {e}")
            print("Terminal may not support the required features.")
            print()
            print("Alternative commands:")
            print(
                f"  poetry run covtool info '{self.filename}' - Basic coverage information"
            )
            print("  poetry run covtool --help - Show all available commands")
            print()
            print("For TUI support, try running in a different terminal or")
            print("use a terminal that supports full ANSI escape sequences.")
            return


def run_inspector(coverage: CoverageSet, filename: str) -> None:
    """Run the coverage inspector TUI"""
    inspector = CoverageInspector(coverage, filename)
    inspector.run()
