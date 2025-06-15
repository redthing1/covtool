"""Interactive TUI inspector for coverage traces using urwid"""

import os

import urwid

from .core import CoverageSet


class SelectableText(urwid.Text):
    """Text widget that can be selected and focused"""

    def __init__(self, text, index=None):
        super().__init__(text)
        self.index = index

    def selectable(self):
        return True

    def keypress(self, size, key):
        return key


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
    HELP_DIALOG_HEIGHT = 16
    FILTER_DIALOG_HEIGHT = 12
    
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

        # UI components
        self.main_loop = None
        self.content_area = None
        self.main_widget = None
        self.module_listbox = None

        self._setup_data()

    def _format_size(self, size):
        """Format size with appropriate units"""
        if size >= self.SIZE_MB_THRESHOLD:
            return f"{size / self.SIZE_MB_THRESHOLD:.1f}MB"
        elif size >= self.SIZE_KB_THRESHOLD:
            return f"{size / self.SIZE_KB_THRESHOLD:.1f}KB"
        else:
            return f"{size}B"
    
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
            truncate_len = max_len - 3  # account for "..."
        else:
            max_len = self.MODULE_WIDTH_NO_HITS
            truncate_len = max_len - 3
        
        return name[:truncate_len] + "..." if len(name) > max_len else name

    def _setup_data(self):
        """Prepare data for display"""
        self._refresh_module_list()
        self._refresh_block_list()

    def _refresh_module_list(self):
        """Refresh the module list for current filtered coverage"""
        by_module = self.filtered_coverage.get_coverage_by_module()
        self.module_list = []

        total_blocks = len(self.filtered_coverage.data.basic_blocks)
        for module_name, blocks in sorted(
            by_module.items(), key=lambda x: x[0]  # sort by module name
        ):
            block_count = len(blocks)
            total_size = sum(block.size for block in blocks)
            percentage = (block_count / total_blocks * 100) if total_blocks > 0 else 0
            
            # Calculate hit count statistics for this module
            module_hits = 0
            if self.filtered_coverage.data.has_hit_counts():
                for block in blocks:
                    block_index = self.filtered_coverage.data.basic_blocks.index(block)
                    hits = self.filtered_coverage.data.get_hit_count(block_index)
                    module_hits += hits
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
        
        for block, hits in blocks_with_hits:
            module = self.filtered_coverage.data.find_module(block.module_id)
            module_name = (
                os.path.basename(module.path) if module else f"module_{block.module_id}"
            )
            abs_addr = module.base + block.start if module else None
            
            # Apply hitcount filter (exact match)
            if self.hitcount_filter is None or hits == self.hitcount_filter:
                self.block_list.append(
                    {
                        "block": block,
                        "module": module,
                        "module_name": module_name,
                        "abs_addr": abs_addr,
                        "hits": hits,
                    }
                )
        
        # Sort based on current sort mode
        if self.block_sort_mode == "hits":
            # Sort by hits (descending), then by address
            self.block_list.sort(key=lambda b: (-b["hits"], b["block"].module_id, b["block"].start))
        else:
            # Sort by address (module_id, then start offset)
            self.block_list.sort(key=lambda b: (b["block"].module_id, b["block"].start))

    def _apply_filter(self, filter_text: str):
        """Apply module filter"""
        self.current_filter = filter_text
        if filter_text.strip():
            self.filtered_coverage = self.coverage.filter_by_module(filter_text.strip())
        else:
            self.filtered_coverage = self.coverage

        self._refresh_module_list()
        self._refresh_block_list()
        self._update_view()
        self._update_header_footer()

    def _create_modules_view(self):
        """Create the modules view with proper navigation"""
        if not self.module_list:
            return urwid.Filler(
                urwid.Text("No modules found", align="center"), valign="middle"
            )

        items = []
        items.extend(self._create_module_header())
        items.extend(self._create_module_entries())
        
        self.module_listbox = urwid.ListBox(urwid.SimpleFocusListWalker(items))
        
        # Set focus to first module (skip header and divider)
        if len(items) > 2:
            self.module_listbox.set_focus(2)
        
        return self.module_listbox
    
    def _create_module_header(self):
        """Create header for module view"""
        if self.filtered_coverage.data.has_hit_counts():
            header_text = f"{'Module':<{self.MODULE_WIDTH_WITH_HITS}} {'Blocks':<8} {'Size':<10} {'%':<8} {'Hits':<10}"
        else:
            header_text = f"{'Module':<{self.MODULE_WIDTH_NO_HITS}} {'Blocks':<10} {'Size':<12} {'%':<8}"
        
        header = urwid.AttrMap(urwid.Text(header_text), "header")
        return [header, urwid.Divider("═")]
    
    def _create_module_entries(self):
        """Create module entry rows"""
        items = []
        for i, mod_info in enumerate(self.module_list):
            line_text = self._format_module_line(mod_info)
            item = SelectableText(line_text, index=i)
            item = urwid.AttrMap(item, None, focus_map="selected")
            items.append(item)
        return items
    
    def _format_module_line(self, mod_info):
        """Format a single module line for display"""
        mod_name = self._truncate_module_name(mod_info["name"])
        size_str = self._format_size(mod_info["size"])
        
        if self.filtered_coverage.data.has_hit_counts():
            hits_str = self._format_hit_count(mod_info['hits'])
            return f"{mod_name:<{self.MODULE_WIDTH_WITH_HITS}} {mod_info['count']:<8,} {size_str:<10} {mod_info['percentage']:<7.1f}% {hits_str:<10}"
        else:
            return f"{mod_name:<{self.MODULE_WIDTH_NO_HITS}} {mod_info['count']:<10,} {size_str:<12} {mod_info['percentage']:<7.1f}%"

    def _create_blocks_view(self):
        """Create the blocks view with scrolling"""
        if not self.block_list:
            return urwid.Filler(
                urwid.Text("No blocks found", align="center"), valign="middle"
            )

        # Create block list items
        items = []

        # Header with hits column and sort indicator
        sort_indicator = " ↓" if self.block_sort_mode == "hits" else " ↑"
        hit_col_header = f"Hits{sort_indicator}" if self.block_sort_mode == "hits" else "Hits"
        addr_col_header = f"Offset{sort_indicator}" if self.block_sort_mode == "address" else "Offset"
        
        header_text = (
            f"{'Module':<{self.BLOCK_MODULE_WIDTH}} {addr_col_header:<12} {'Address':<16} {'Size':<6} {hit_col_header:<8}"
        )
        header = urwid.AttrMap(urwid.Text(header_text), "header")
        items.append(header)
        items.append(urwid.Divider("═"))

        # Block entries (show more blocks, with pagination)
        max_blocks = min(self.MAX_BLOCKS_DISPLAY, len(self.block_list))
        for block_info in self.block_list[:max_blocks]:
            block = block_info["block"]
            abs_addr_str = (
                f"0x{block_info['abs_addr']:x}" if block_info["abs_addr"] else "unknown"
            )

            mod_name = block_info["module_name"]

            hits_str = self._format_hit_count(block_info['hits'])
            mod_name = self._truncate_module_name(mod_name, has_hits=False)  # blocks view doesn't depend on hit count presence
            
            line_text = (
                f"{mod_name:<{self.BLOCK_MODULE_WIDTH}} 0x{block.start:08x} {abs_addr_str:<16} {block.size:<6} {hits_str:<8}"
            )
            item = SelectableText(line_text)
            item = urwid.AttrMap(item, None, focus_map="focus")
            items.append(item)

        if len(self.block_list) > max_blocks:
            remaining = len(self.block_list) - max_blocks
            items.append(
                urwid.AttrMap(
                    urwid.Text(
                        f"... ({remaining:,} more blocks - use filter to narrow down)"
                    ),
                    "dim",
                )
            )

        listbox = urwid.ListBox(urwid.SimpleFocusListWalker(items))
        return listbox

    def _create_stats_view(self):
        """Create an enhanced stats view"""
        stats_content = []
        
        stats_content.extend(self._create_stats_title())
        stats_content.extend(self._create_basic_stats())
        stats_content.extend(self._create_address_space_stats())
        stats_content.extend(self._create_hit_distribution_stats())
        stats_content.extend(self._create_top_modules_stats())
        
        pile = urwid.Pile(stats_content)
        return urwid.Filler(pile, valign="top")
    
    def _create_stats_title(self):
        """Create stats view title section"""
        title_text = (
            f"Coverage Analysis (Filtered: {self.current_filter})" 
            if self.current_filter 
            else "Coverage Analysis (All Modules)"
        )
        return [
            urwid.AttrMap(urwid.Text(title_text, align="center"), "title"),
            urwid.Divider()
        ]
    
    def _create_basic_stats(self):
        """Create basic statistics section"""
        cov = self.filtered_coverage
        basic_stats = [
            f"Total basic blocks: {len(cov):,}",
            f"Total modules: {len(cov.modules):,}",
            f"Hit count support: {'Yes' if cov.data.has_hit_counts() else 'No (defaults to 1)'}",
        ]
        
        if cov.data.basic_blocks:
            basic_stats.extend(self._get_size_stats())
            if cov.data.has_hit_counts():
                basic_stats.extend(self._get_hit_count_stats())
        
        content = [urwid.Text(f"  {stat}") for stat in basic_stats]
        content.append(urwid.Divider())
        return content
    
    def _get_size_stats(self):
        """Get size-related statistics"""
        cov = self.filtered_coverage
        total_size = sum(block.size for block in cov.data.basic_blocks)
        avg_size = total_size / len(cov.data.basic_blocks)
        min_size = min(block.size for block in cov.data.basic_blocks)
        max_size = max(block.size for block in cov.data.basic_blocks)
        
        total_size_str = self._format_size(total_size).replace('B', ' bytes').replace('MB', ' MB').replace('KB', ' KB')
        
        return [
            f"Total coverage size: {total_size_str}",
            f"Average block size: {avg_size:.1f} bytes",
            f"Block size range: {min_size} - {max_size} bytes",
        ]
    
    def _get_hit_count_stats(self):
        """Get hit count statistics"""
        hit_counts = self.filtered_coverage.data.hit_counts
        total_hits = sum(hit_counts)
        avg_hits = total_hits / len(hit_counts)
        min_hits = min(hit_counts)
        max_hits = max(hit_counts)
        
        return [
            f"Total hits: {total_hits:,}",
            f"Average hits per block: {avg_hits:.1f}",
            f"Hit count range: {min_hits} - {max_hits:,}",
        ]
    
    def _create_address_space_stats(self):
        """Create address space statistics section"""
        cov = self.filtered_coverage

        if cov.data.basic_blocks:
            addresses = cov.get_absolute_addresses()
            if addresses:
                min_addr = min(addresses)
                max_addr = max(addresses)
                addr_range = max_addr - min_addr

                return [
                    urwid.AttrMap(urwid.Text("Address Space", align="center"), "subtitle"),
                    urwid.Text(f"  Range: 0x{min_addr:x} - 0x{max_addr:x}"),
                    urwid.Text(f"  Span: {addr_range:,} bytes ({addr_range / 1024 / 1024:.1f} MB)"),
                    urwid.Divider()
                ]
        return []
        
    
    def _create_hit_distribution_stats(self):
        """Create hit count distribution section"""
        cov = self.filtered_coverage
        if not cov.data.has_hit_counts():
            return []
        
        hit_counts = cov.data.hit_counts
        hit_ranges = {
            "1 hit": sum(1 for h in hit_counts if h == 1),
            "2-10 hits": sum(1 for h in hit_counts if 2 <= h <= 10),
            "11-100 hits": sum(1 for h in hit_counts if 11 <= h <= 100),
            "101-1000 hits": sum(1 for h in hit_counts if 101 <= h <= 1000),
            "1000+ hits": sum(1 for h in hit_counts if h > 1000),
        }
        
        content = [
            urwid.AttrMap(urwid.Text("Hit Count Distribution", align="center"), "subtitle")
        ]
        
        total_blocks = len(hit_counts)
        for range_name, count in hit_ranges.items():
            if count > 0:
                percentage = (count / total_blocks) * 100
                content.append(
                    urwid.Text(f"  {range_name}: {count:,} blocks ({percentage:.1f}%)")
                )
        
        content.append(urwid.Divider())
        return content
    
    def _create_top_modules_stats(self):
        """Create top modules section"""
        if not self.module_list:
            return []
        
        content = [
            urwid.AttrMap(urwid.Text("Top Modules by Coverage", align="center"), "subtitle")
        ]
        
        for i, mod_info in enumerate(self.module_list[:5]):
            mod_name = os.path.basename(mod_info["name"])
            mod_name = self._truncate_module_name(mod_name, has_hits=False)
            content.append(
                urwid.Text(f"  {i+1}. {mod_name} ({mod_info['percentage']:.1f}%)")
            )
        
        return content

    def _update_view(self):
        """Update the current view"""
        if self.current_view == "modules":
            content = self._create_modules_view()
        elif self.current_view == "blocks":
            content = self._create_blocks_view()
        elif self.current_view == "stats":
            content = self._create_stats_view()
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
        """Create enhanced footer with context-sensitive help"""
        base_help = "[1]Modules [2]Blocks [3]Stats [f]Filter [r]Reset [h]Help [q]Quit"

        if self.current_view == "modules":
            view_help = " [j/k]↑↓ [J/K]Page [Enter]Select"
            if self.module_list:
                module_count = len(self.module_list)
                view_help += f" ({module_count} modules)"
        elif self.current_view == "blocks":
            view_help = " [j/k]↑↓ [J/K]Page [s]Sort [c]Filter hits"
        else:
            view_help = " [j/k]↑↓ [J/K]Page"

        help_text = base_help + view_help

        # Show current filter if active
        if self.current_filter:
            filter_info = f" | Filter: '{self.current_filter}'"
            help_text += filter_info

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
                filtered_hits = sum(self.coverage.data.get_hit_count(i) for i, block in enumerate(self.coverage.data.basic_blocks) if block in self.filtered_coverage.blocks)
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
            header_lines.append(urwid.AttrMap(urwid.Text(view_status, align="center"), "header_stats"))

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
            self._apply_filter("")
        elif key == "f":
            self._show_filter_dialog()
        elif key == "s" and self.current_view == "blocks":
            self._toggle_block_sort()
        elif key == "c" and self.current_view == "blocks":
            self._show_hitcount_filter_dialog()
        elif key in ("h", "?"):
            self._show_help_dialog()
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
            if hasattr(self.content_area, 'original_widget'):
                focused_widget = self.content_area.original_widget
                if hasattr(focused_widget, 'original_widget'):
                    focused_widget = focused_widget.original_widget
        
        if not focused_widget or not hasattr(focused_widget, 'keypress'):
            return
        
        # Handle different navigation keys
        if key == "j":
            # Move down one line
            focused_widget.keypress((80, 24), "down")
        elif key == "k":
            # Move up one line  
            focused_widget.keypress((80, 24), "up")
        elif key == "J":
            # Page down
            focused_widget.keypress((80, 24), "page down")
        elif key == "K":
            # Page up
            focused_widget.keypress((80, 24), "page up")

    def _handle_module_selection(self):
        """Handle module selection in modules view"""
        if not self.module_listbox or not self.module_list:
            return

        # Get current focus position
        _, focus_pos = self.module_listbox.get_focus()

        # Skip header and divider (positions 0 and 1)
        if focus_pos >= 2:
            module_index = focus_pos - 2
            if module_index < len(self.module_list):
                selected_mod = self.module_list[module_index]
                self._apply_filter(selected_mod["name"])
                self.current_view = "blocks"

    def _show_filter_dialog(self):
        """Show enhanced filter input dialog"""

        def on_ok(_button):
            filter_text = edit.get_edit_text()
            self._apply_filter(filter_text)
            self.main_loop.widget = self.main_widget

        def on_cancel(_button):
            self.main_loop.widget = self.main_widget

        def on_clear(_button):
            edit.set_edit_text("")

        edit = urwid.Edit("Filter: ", self.current_filter)
        ok_button = urwid.Button("Apply", on_ok)
        clear_button = urwid.Button("Clear", on_clear)
        cancel_button = urwid.Button("Cancel", on_cancel)

        # Enhanced dialog with instructions
        pile = urwid.Pile(
            [
                urwid.Text("Enter module name filter (case-insensitive):"),
                urwid.Text("Examples: 'libc', 'kernel', 'myapp', 'lib'"),
                urwid.Text("Tip: Use partial names to match multiple modules"),
                urwid.Divider(),
                edit,
                urwid.Divider(),
                urwid.Columns(
                    [
                        ("pack", ok_button),
                        ("pack", urwid.Text("  ")),
                        ("pack", clear_button),
                        ("pack", urwid.Text("  ")),
                        ("pack", cancel_button),
                    ]
                ),
            ]
        )

        dialog = urwid.Filler(
            urwid.LineBox(pile, title="Filter Modules"), valign="middle"
        )
        overlay = urwid.Overlay(
            dialog,
            self.main_widget,
            align="center",
            width=self.DIALOG_WIDTH,
            valign="middle",
            height=self.FILTER_DIALOG_HEIGHT,
        )
        self.main_loop.widget = overlay

    def _show_help_dialog(self):
        """Show help dialog"""

        def on_close(_button):
            self.main_loop.widget = self.main_widget

        help_text = [
            "Navigation:",
            "  1, 2, 3     - Switch between views (Modules/Blocks/Stats)",
            "  ↑ ↓ / j k   - Navigate lists (line by line)",
            "  Page Up/Dn  - Scroll faster through lists",
            "  J K         - Page up/down (vi-style)",
            "  Enter       - Select module (in modules view)",
            "",
            "Filtering:",
            "  f           - Open module filter dialog",
            "  r           - Reset/clear module filter",
            "",
            "Block View Controls:",
            "  s           - Toggle sort by hits/address",
            "  c           - Filter by exact hit count",
            "",
            "Other:",
            "  Ctrl+L      - Refresh screen",
            "  h, ?        - Show this help",
            "  q, Ctrl+C   - Quit",
            "",
            "Tips:",
            "  • Use filters to narrow down large lists",
            "  • Module view shows coverage by module",
            "  • Block view shows individual basic blocks with hit counts",
            "  • Stats view provides summary information",
        ]

        text_widgets = [urwid.Text(line) for line in help_text]
        close_button = urwid.Button("Close", on_close)

        pile = urwid.Pile(text_widgets + [urwid.Divider(), close_button])
        dialog = urwid.Filler(urwid.LineBox(pile, title="Help"), valign="middle")

        overlay = urwid.Overlay(
            dialog,
            self.main_widget,
            align="center",
            width=50,
            valign="middle",
            height=self.HELP_DIALOG_HEIGHT,
        )
        self.main_loop.widget = overlay

    def _toggle_block_sort(self):
        """Toggle between sorting blocks by address and hits"""
        if self.block_sort_mode == "address":
            self.block_sort_mode = "hits"
        else:
            self.block_sort_mode = "address"
        
        self._refresh_block_list()
        self._update_view()
        self._update_header_footer()

    def _show_hitcount_filter_dialog(self):
        """Show dialog to filter blocks by exact hit count"""

        def on_ok(_button):
            filter_text = edit.get_edit_text().strip()
            if filter_text == "":
                self.hitcount_filter = None
            else:
                try:
                    self.hitcount_filter = int(filter_text)
                except ValueError:
                    # Invalid input, ignore
                    pass
            self._refresh_block_list()
            self._update_view()
            self._update_header_footer()
            self.main_loop.widget = self.main_widget

        def on_cancel(_button):
            self.main_loop.widget = self.main_widget

        def on_clear(_button):
            edit.set_edit_text("")

        current_filter = str(self.hitcount_filter) if self.hitcount_filter is not None else ""
        edit = urwid.Edit("Hit count: ", current_filter)
        ok_button = urwid.Button("Apply", on_ok)
        clear_button = urwid.Button("Clear", on_clear)
        cancel_button = urwid.Button("Cancel", on_cancel)

        # Enhanced dialog with instructions
        has_hit_counts = self.filtered_coverage.data.has_hit_counts()
        instructions = [
            urwid.Text("Filter blocks by exact hit count:"),
            urwid.Text("Enter a number to show only blocks with that hit count"),
            urwid.Text("Leave empty to show all blocks"),
        ]
        
        if has_hit_counts:
            instructions.append(urwid.Text("Note: This file contains actual hit count data"))
        else:
            instructions.append(urwid.Text("Note: This file shows default hit counts (=1)"))
        
        pile = urwid.Pile(
            instructions + [
                urwid.Divider(),
                edit,
                urwid.Divider(),
                urwid.Columns(
                    [
                        ("pack", ok_button),
                        ("pack", urwid.Text("  ")),
                        ("pack", clear_button),
                        ("pack", urwid.Text("  ")),
                        ("pack", cancel_button),
                    ]
                ),
            ]
        )

        dialog = urwid.Filler(
            urwid.LineBox(pile, title="Filter by Hit Count"), valign="middle"
        )
        overlay = urwid.Overlay(
            dialog,
            self.main_widget,
            align="center",
            width=65,
            valign="middle",
            height=14,
        )
        self.main_loop.widget = overlay

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
