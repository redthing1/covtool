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

            self.module_list.append(
                {
                    "name": module_name,
                    "blocks": blocks,
                    "count": block_count,
                    "size": total_size,
                    "percentage": percentage,
                }
            )

    def _refresh_block_list(self):
        """Refresh the block list for current filtered coverage"""
        self.block_list = []

        # Create block list with hit information
        blocks = self.filtered_coverage.data.basic_blocks
        
        for block in blocks:
            module = self.filtered_coverage.data.find_module(block.module_id)
            module_name = (
                os.path.basename(module.path) if module else f"module_{block.module_id}"
            )
            abs_addr = module.base + block.start if module else None
            
            # For DrCov format, each block has a hit count of 1 (executed)
            # In the future, this could be extended to support actual hit counts
            hits = 1
            
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

        # Create module list items
        items = []

        # Header
        header_text = f"{'Module':<40} {'Blocks':<10} {'Size':<12} {'%':<8}"
        header = urwid.AttrMap(urwid.Text(header_text), "header")
        items.append(header)
        items.append(urwid.Divider("═"))

        # Module entries
        for i, mod_info in enumerate(self.module_list):
            mod_name = mod_info["name"]
            if len(mod_name) > 38:
                mod_name = mod_name[:35] + "..."

            # Format size with units
            size = mod_info["size"]
            if size >= 1024 * 1024:
                size_str = f"{size / (1024 * 1024):.1f}MB"
            elif size >= 1024:
                size_str = f"{size / 1024:.1f}KB"
            else:
                size_str = f"{size}B"

            line_text = f"{mod_name:<40} {mod_info['count']:<10,} {size_str:<12} {mod_info['percentage']:<7.1f}%"

            # Create selectable text widget
            item = SelectableText(line_text, index=i)
            item = urwid.AttrMap(item, None, focus_map="selected")
            items.append(item)

        # Create listbox with proper focus handling
        self.module_listbox = urwid.ListBox(urwid.SimpleFocusListWalker(items))

        # Set focus to first module (skip header and divider)
        if len(items) > 2:
            self.module_listbox.set_focus(2)

        return self.module_listbox

    def _create_blocks_view(self):
        """Create the blocks view with scrolling"""
        if not self.block_list:
            return urwid.Filler(
                urwid.Text("No blocks found", align="center"), valign="middle"
            )

        # Create block list items
        items = []

        # Header with hits column and sort indicator
        sort_indicator = " ↓" if self.block_sort_mode == "hits" else ""
        header_text = (
            f"{'Offset':<12} {'Size':<6} {'Hits':<6}{sort_indicator} {'Module':<22} {'Absolute Address':<16}"
        )
        header = urwid.AttrMap(urwid.Text(header_text), "header")
        items.append(header)
        items.append(urwid.Divider("═"))

        # Block entries (show more blocks, with pagination)
        max_blocks = min(10000, len(self.block_list))  # Show up to 10,000 blocks
        for block_info in self.block_list[:max_blocks]:
            block = block_info["block"]
            abs_addr_str = (
                f"0x{block_info['abs_addr']:x}" if block_info["abs_addr"] else "unknown"
            )

            mod_name = block_info["module_name"]
            if len(mod_name) > 23:
                mod_name = mod_name[:20] + "..."

            line_text = (
                f"0x{block.start:08x} {block.size:<6} {block_info['hits']:<6} {mod_name:<22} {abs_addr_str}"
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
        cov = self.filtered_coverage

        stats_content = []

        # Title with filter info
        if self.current_filter:
            title_text = f"Coverage Analysis (Filtered: {self.current_filter})"
        else:
            title_text = "Coverage Analysis (All Modules)"
        stats_content.append(
            urwid.AttrMap(urwid.Text(title_text, align="center"), "title")
        )
        stats_content.append(urwid.Divider())

        # Basic stats in columns
        basic_stats = [
            f"Total basic blocks: {len(cov):,}",
            f"Total modules: {len(cov.modules):,}",
        ]

        if cov.data.basic_blocks:
            total_size = sum(block.size for block in cov.data.basic_blocks)
            avg_size = total_size / len(cov.data.basic_blocks)
            min_size = min(block.size for block in cov.data.basic_blocks)
            max_size = max(block.size for block in cov.data.basic_blocks)

            # Format total size
            if total_size > 1024 * 1024:
                total_size_str = f"{total_size / (1024 * 1024):.2f} MB"
            elif total_size > 1024:
                total_size_str = f"{total_size / 1024:.2f} KB"
            else:
                total_size_str = f"{total_size} bytes"

            basic_stats.extend(
                [
                    f"Total coverage size: {total_size_str}",
                    f"Average block size: {avg_size:.1f} bytes",
                    f"Block size range: {min_size} - {max_size} bytes",
                ]
            )

        for stat in basic_stats:
            stats_content.append(urwid.Text(f"  {stat}"))

        stats_content.append(urwid.Divider())

        # Address space info
        if cov.data.basic_blocks:
            addresses = cov.get_absolute_addresses()
            if addresses:
                min_addr = min(addresses)
                max_addr = max(addresses)
                addr_range = max_addr - min_addr

                stats_content.append(
                    urwid.AttrMap(
                        urwid.Text("Address Space", align="center"), "subtitle"
                    )
                )
                stats_content.append(
                    urwid.Text(f"  Range: 0x{min_addr:x} - 0x{max_addr:x}")
                )
                stats_content.append(
                    urwid.Text(
                        f"  Span: {addr_range:,} bytes ({addr_range / 1024 / 1024:.1f} MB)"
                    )
                )
                stats_content.append(urwid.Divider())

        # Top modules summary
        if self.module_list:
            stats_content.append(
                urwid.AttrMap(
                    urwid.Text("Top Modules by Coverage", align="center"), "subtitle"
                )
            )
            for i, mod_info in enumerate(self.module_list[:5]):
                mod_name = os.path.basename(mod_info["name"])
                if len(mod_name) > 30:
                    mod_name = mod_name[:27] + "..."
                stats_content.append(
                    urwid.Text(f"  {i+1}. {mod_name} ({mod_info['percentage']:.1f}%)")
                )

        pile = urwid.Pile(stats_content)
        return urwid.Filler(pile, valign="top")

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
            view_help = " [↑↓]Navigate [Enter]Select"
            if self.module_list:
                module_count = len(self.module_list)
                view_help += f" ({module_count} modules)"
        elif self.current_view == "blocks":
            view_help = " [↑↓]Scroll [s]Sort [c]Filter hits"
        else:
            view_help = " [↑↓]Scroll"

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

        if self.current_filter and total_blocks > 0:
            filter_pct = (filtered_blocks / total_blocks) * 100
            stats = f"Modules: {len(self.module_list)} | Blocks: {filtered_blocks:,}/{total_blocks:,} ({filter_pct:.1f}%)"
        else:
            stats = f"Modules: {len(self.module_list)} | Blocks: {filtered_blocks:,}"

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
        else:
            # Let the widget handle other keys (like arrow keys)
            return key

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
            width=65,
            valign="middle",
            height=12,
        )
        self.main_loop.widget = overlay

    def _show_help_dialog(self):
        """Show help dialog"""

        def on_close(_button):
            self.main_loop.widget = self.main_widget

        help_text = [
            "Navigation:",
            "  1, 2, 3     - Switch between views (Modules/Blocks/Stats)",
            "  ↑ ↓         - Navigate lists",
            "  Page Up/Dn  - Scroll faster through lists",
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
            height=16,
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
        pile = urwid.Pile(
            [
                urwid.Text("Filter blocks by exact hit count:"),
                urwid.Text("Enter a number to show only blocks with that hit count"),
                urwid.Text("Leave empty to show all blocks"),
                urwid.Text("Note: DrCov blocks always have hit count = 1"),
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
