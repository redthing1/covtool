"""Dialog classes for the coverage inspector TUI"""

import urwid


class BaseDialog:
    """Base class for dialogs with ESC/ENTER support"""

    def __init__(self, main_loop, main_widget):
        self.main_loop = main_loop
        self.main_widget = main_widget
        self.edit_widget = None

    def _handle_dialog_key(self, key):
        """Handle common dialog keys (ESC to cancel, ENTER to confirm)"""
        if key == "esc":
            self._on_cancel()
            return True
        elif key == "enter" and self.edit_widget and self.edit_widget.selectable():
            self._on_ok()
            return True
        return False

    def _on_ok(self):
        """Override in subclasses"""
        self.main_loop.widget = self.main_widget

    def _on_cancel(self):
        """Close dialog without action"""
        self.main_loop.widget = self.main_widget

    def _create_dialog_wrapper(self, content, title, width, height):
        """Create a dialog with key handling"""

        class DialogWrapper(urwid.WidgetWrap):
            def __init__(self, dialog_instance, content):
                self.dialog = dialog_instance
                super().__init__(content)

            def keypress(self, size, key):
                if self.dialog._handle_dialog_key(key):
                    return None
                return super().keypress(size, key)

        dialog_content = urwid.Filler(
            urwid.LineBox(content, title=title), valign="middle"
        )
        wrapped = DialogWrapper(self, dialog_content)

        overlay = urwid.Overlay(
            wrapped,
            self.main_widget,
            align="center",
            width=width,
            valign="middle",
            height=height,
        )
        return overlay


class FilterDialog(BaseDialog):
    """Module filter dialog"""

    def __init__(self, inspector):
        super().__init__(inspector.main_loop, inspector.main_widget)
        self.inspector = inspector

    def _on_ok(self):
        filter_text = self.edit_widget.get_edit_text()
        self.inspector._apply_filter(filter_text)
        super()._on_ok()

    def show(self):
        def on_clear(_button):
            self.edit_widget.set_edit_text("")

        self.edit_widget = urwid.Edit("Filter: ", self.inspector.current_filter)
        ok_button = urwid.Button("Apply", lambda _: self._on_ok())
        clear_button = urwid.Button("Clear", on_clear)
        cancel_button = urwid.Button("Cancel", lambda _: self._on_cancel())

        pile = urwid.Pile(
            [
                urwid.Text("Enter module name filter (case-insensitive):"),
                urwid.Text("Examples: 'libc', 'kernel', 'myapp', 'lib'"),
                urwid.Text("Tip: Use partial names to match multiple modules"),
                urwid.Divider(),
                self.edit_widget,
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

        overlay = self._create_dialog_wrapper(
            pile,
            "Filter Modules",
            self.inspector.DIALOG_WIDTH,
            self.inspector.FILTER_DIALOG_HEIGHT,
        )
        self.main_loop.widget = overlay


class SearchDialog(BaseDialog):
    """Search dialog for filtering modules and blocks"""

    def __init__(self, inspector):
        super().__init__(inspector.main_loop, inspector.main_widget)
        self.inspector = inspector

    def _on_ok(self):
        search_text = self.edit_widget.get_edit_text().strip()
        self.inspector.search_term = search_text
        self.inspector._refresh_module_list()
        self.inspector._refresh_block_list()
        self.inspector._update_view()
        self.inspector._update_header_footer()
        super()._on_ok()

    def show(self):
        def on_clear(_button):
            self.edit_widget.set_edit_text("")

        self.edit_widget = urwid.Edit("Search: ", self.inspector.search_term)
        clear_button = urwid.Button("Clear", on_clear)

        instructions = [
            urwid.Text(
                "Search in module names and addresses (ESC=Cancel, Enter=Apply):"
            ),
            urwid.Text("• Module names (case-insensitive)"),
            urwid.Text("• Block offsets (hex, e.g., '0x1000', '1000')"),
            urwid.Text("• Virtual addresses (hex, e.g., '0x401000')"),
            urwid.Text("• Module paths"),
        ]

        pile = urwid.Pile(
            instructions
            + [
                urwid.Divider(),
                self.edit_widget,
                urwid.Divider(),
                urwid.Columns([("pack", clear_button)]),
            ]
        )

        overlay = self._create_dialog_wrapper(
            pile,
            "Search Modules and Blocks",
            self.inspector.DIALOG_WIDTH,
            self.inspector.SEARCH_DIALOG_HEIGHT,
        )
        self.main_loop.widget = overlay


class HitCountDialog(BaseDialog):
    """Dialog to filter blocks by exact hit count"""

    def __init__(self, inspector):
        super().__init__(inspector.main_loop, inspector.main_widget)
        self.inspector = inspector

    def _on_ok(self):
        filter_text = self.edit_widget.get_edit_text().strip()
        if filter_text == "":
            self.inspector.hitcount_filter = None
        else:
            try:
                self.inspector.hitcount_filter = int(filter_text)
            except ValueError:
                # Invalid input, ignore
                pass
        self.inspector._refresh_block_list()
        self.inspector._update_view()
        self.inspector._update_header_footer()
        super()._on_ok()

    def show(self):
        def on_clear(_button):
            self.edit_widget.set_edit_text("")

        current_filter = (
            str(self.inspector.hitcount_filter)
            if self.inspector.hitcount_filter is not None
            else ""
        )
        self.edit_widget = urwid.Edit("Hit count: ", current_filter)
        clear_button = urwid.Button("Clear", on_clear)

        has_hit_counts = self.inspector.filtered_coverage.data.has_hit_counts()
        instructions = [
            urwid.Text("Filter blocks by exact hit count (ESC=Cancel, Enter=Apply):"),
            urwid.Text("Enter a number to show only blocks with that hit count"),
        ]

        if has_hit_counts:
            instructions.append(
                urwid.Text("Note: This file contains actual hit count data")
            )
        else:
            instructions.append(
                urwid.Text("Note: This file shows default hit counts (=1)")
            )

        pile = urwid.Pile(
            instructions
            + [
                urwid.Divider(),
                self.edit_widget,
                urwid.Divider(),
                urwid.Columns([("pack", clear_button)]),
            ]
        )

        overlay = self._create_dialog_wrapper(
            pile,
            "Filter by Hit Count",
            self.inspector.DIALOG_WIDTH,
            self.inspector.FILTER_DIALOG_HEIGHT,
        )
        self.main_loop.widget = overlay


class HitCountRangeDialog(BaseDialog):
    """Dialog to filter blocks by hit count range"""

    def __init__(self, inspector):
        super().__init__(inspector.main_loop, inspector.main_widget)
        self.inspector = inspector

    def _on_ok(self):
        filter_text = self.edit_widget.get_edit_text().strip()
        if filter_text == "":
            self.inspector.hitcount_range_filter = None
        else:
            parsed_filter = self.inspector._parse_range_filter(filter_text)
            if parsed_filter:
                self.inspector.hitcount_range_filter = parsed_filter
        self.inspector._refresh_block_list()
        self.inspector._update_view()
        self.inspector._update_header_footer()
        super()._on_ok()

    def show(self):
        def on_clear(_button):
            self.edit_widget.set_edit_text("")

        current_filter = ""
        if self.inspector.hitcount_range_filter:
            min_val, max_val, op = self.inspector.hitcount_range_filter
            if op == "range":
                current_filter = f"{min_val}-{max_val}"
            else:
                current_filter = f"{op}{min_val}"

        self.edit_widget = urwid.Edit("Hit count range: ", current_filter)
        clear_button = urwid.Button("Clear", on_clear)

        instructions = [
            urwid.Text("Filter blocks by hit count range (ESC=Cancel, Enter=Apply):"),
            urwid.Text("Examples: '>50', '10-100', '<=5', '>=10'"),
            urwid.Text("Operators: >, <, >=, <=, ==, range (-)"),
            urwid.Text("Leave empty to show all blocks"),
        ]

        pile = urwid.Pile(
            instructions
            + [
                urwid.Divider(),
                self.edit_widget,
                urwid.Divider(),
                urwid.Columns([("pack", clear_button)]),
            ]
        )

        overlay = self._create_dialog_wrapper(
            pile,
            "Filter by Hit Count Range",
            self.inspector.DIALOG_WIDTH_WIDE,
            self.inspector.RANGE_FILTER_DIALOG_HEIGHT,
        )
        self.main_loop.widget = overlay


class SizeFilterDialog(BaseDialog):
    """Dialog to filter blocks by size range"""

    def __init__(self, inspector):
        super().__init__(inspector.main_loop, inspector.main_widget)
        self.inspector = inspector

    def _on_ok(self):
        filter_text = self.edit_widget.get_edit_text().strip()
        if filter_text == "":
            self.inspector.size_filter = None
        else:
            parsed_filter = self.inspector._parse_range_filter(filter_text)
            if parsed_filter:
                self.inspector.size_filter = parsed_filter
        self.inspector._refresh_block_list()
        self.inspector._update_view()
        self.inspector._update_header_footer()
        super()._on_ok()

    def show(self):
        def on_clear(_button):
            self.edit_widget.set_edit_text("")

        current_filter = ""
        if self.inspector.size_filter:
            min_val, max_val, op = self.inspector.size_filter
            if op == "range":
                current_filter = f"{min_val}-{max_val}"
            else:
                current_filter = f"{op}{min_val}"

        self.edit_widget = urwid.Edit("Block size range: ", current_filter)
        clear_button = urwid.Button("Clear", on_clear)

        instructions = [
            urwid.Text(
                "Filter blocks by size range (in bytes) (ESC=Cancel, Enter=Apply):"
            ),
            urwid.Text("Examples: '>100', '1-64', '<=32', '>=16'"),
            urwid.Text("Operators: >, <, >=, <=, ==, range (-)"),
            urwid.Text("Leave empty to show all blocks"),
        ]

        pile = urwid.Pile(
            instructions
            + [
                urwid.Divider(),
                self.edit_widget,
                urwid.Divider(),
                urwid.Columns([("pack", clear_button)]),
            ]
        )

        overlay = self._create_dialog_wrapper(
            pile,
            "Filter by Block Size Range",
            self.inspector.DIALOG_WIDTH_WIDE,
            self.inspector.RANGE_FILTER_DIALOG_HEIGHT,
        )
        self.main_loop.widget = overlay


class HelpDialog:
    """Help dialog"""

    def __init__(self, inspector):
        self.inspector = inspector

    def show(self):
        def on_close(_button):
            self.inspector.main_loop.widget = self.inspector.main_widget

        help_text = [
            "Navigation:",
            "  1, 2, 3     - Switch between views (Modules/Blocks/Stats)",
            "  ↑ ↓ j k     - Navigate lists (line by line)",
            "  Page Up/Dn  - Scroll faster through lists",
            "  J K         - Page up/down (vi-style)",
            "  Enter       - Select module (in modules view)",
            "",
            "Filtering:",
            "  f           - Open module filter dialog",
            "  /           - Search modules, blocks, and addresses",
            "  r           - Reset/clear all filters",
            "",
            "Block View Controls:",
            "  s           - Toggle sort by hits/address",
            "  c           - Filter by exact hit count",
            "  C           - Filter by hit count range (>50, 10-100, etc.)",
            "  z           - Filter by block size range",
            "",
            "Dialog Controls:",
            "  ESC         - Cancel dialog",
            "  Enter       - Apply/confirm in dialogs",
            "",
            "Other:",
            "  Ctrl+L      - Refresh screen",
            "  h, ?        - Show this help",
            "  q, Ctrl+C   - Quit",
            "",
            "Tips:",
            "  • Use filters to narrow down large lists",
            "  • Combine multiple filters for precise analysis",
            "  • Block view shows individual basic blocks with hit counts",
            "  • Stats view provides summary information",
        ]

        text_widgets = [urwid.Text(line) for line in help_text]
        close_button = urwid.Button("Close", on_close)

        pile = urwid.Pile(text_widgets + [urwid.Divider(), close_button])
        dialog = urwid.Filler(urwid.LineBox(pile, title="Help"), valign="middle")

        overlay = urwid.Overlay(
            dialog,
            self.inspector.main_widget,
            align="center",
            width=50,
            valign="middle",
            height=self.inspector.HELP_DIALOG_HEIGHT,
        )
        self.inspector.main_loop.widget = overlay
