"""View creation and formatting utilities for the coverage inspector TUI"""

import os
import urwid


class SelectableText(urwid.Text):
    """Text widget that can be selected and focused"""

    def __init__(self, text, index=None):
        super().__init__(text)
        self.index = index

    def selectable(self):
        return True

    def keypress(self, size, key):
        return key


class ViewCreator:
    """Handles creation of all views for the coverage inspector"""

    def __init__(self, inspector):
        self.inspector = inspector

    def create_modules_view(self):
        """Create the modules view with proper navigation"""
        if not self.inspector.module_list:
            return urwid.Filler(
                urwid.Text("No modules found", align="center"), valign="middle"
            )

        items = []
        items.extend(self._create_module_header())
        items.extend(self._create_module_entries())

        self.inspector.module_listbox = urwid.ListBox(
            urwid.SimpleFocusListWalker(items)
        )

        # Set focus to first module (skip header and divider)
        if len(items) > self.inspector.HEADER_ROWS:
            self.inspector.module_listbox.set_focus(self.inspector.HEADER_ROWS)

        return self.inspector.module_listbox

    def _create_module_header(self):
        """Create header for module view"""
        if self.inspector.filtered_coverage.data.has_hit_counts():
            header_text = f"{'Module':<{self.inspector.MODULE_WIDTH_WITH_HITS}} {'Blocks':<8} {'Size':<10} {'%':<8} {'Hits':<10}"
        else:
            header_text = f"{'Module':<{self.inspector.MODULE_WIDTH_NO_HITS}} {'Blocks':<10} {'Size':<12} {'%':<8}"

        header = urwid.AttrMap(urwid.Text(header_text), "header")
        return [header, urwid.Divider("═")]

    def _create_module_entries(self):
        """Create module entry rows"""
        items = []
        for i, mod_info in enumerate(self.inspector.module_list):
            line_text = self._format_module_line(mod_info)
            item = SelectableText(line_text, index=i)
            item = urwid.AttrMap(item, None, focus_map="selected")
            items.append(item)
        return items

    def _format_module_line(self, mod_info):
        """Format a single module line for display"""
        mod_name = self.inspector._truncate_module_name(mod_info["name"])
        size_str = self.inspector._format_size(mod_info["size"])

        if self.inspector.filtered_coverage.data.has_hit_counts():
            hits_str = self.inspector._format_hit_count(mod_info["hits"])
            percentage_str = f"{mod_info['percentage']:.1f}%"
            return f"{mod_name:<{self.inspector.MODULE_WIDTH_WITH_HITS}} {mod_info['count']:<8,} {size_str:<10} {percentage_str:<8} {hits_str:<10}"
        else:
            percentage_str = f"{mod_info['percentage']:.1f}%"
            return f"{mod_name:<{self.inspector.MODULE_WIDTH_NO_HITS}} {mod_info['count']:<10,} {size_str:<12} {percentage_str:<8}"

    def create_blocks_view(self):
        """Create the blocks view with scrolling"""
        if not self.inspector.block_list:
            return urwid.Filler(
                urwid.Text("No blocks found", align="center"), valign="middle"
            )

        # Create block list items
        items = []

        # Header with hits column and sort indicator
        sort_indicator = " ↓" if self.inspector.block_sort_mode == "hits" else " ↑"
        hit_col_header = (
            f"Hits{sort_indicator}"
            if self.inspector.block_sort_mode == "hits"
            else "Hits"
        )
        addr_col_header = (
            f"Offset{sort_indicator}"
            if self.inspector.block_sort_mode == "address"
            else "Offset"
        )

        header_text = f"{'Module':<{self.inspector.BLOCK_MODULE_WIDTH}} {addr_col_header:<{self.inspector.OFFSET_FIELD_WIDTH}} {'Address':<{self.inspector.ADDRESS_FIELD_WIDTH}} {'Size':<{self.inspector.SIZE_FIELD_WIDTH}} {hit_col_header:<{self.inspector.HITS_FIELD_WIDTH}}"
        header = urwid.AttrMap(urwid.Text(header_text), "header")
        items.append(header)
        items.append(urwid.Divider("═"))

        # Block entries (show more blocks, with pagination)
        max_blocks = min(
            self.inspector.MAX_BLOCKS_DISPLAY, len(self.inspector.block_list)
        )
        for block_info in self.inspector.block_list[:max_blocks]:
            block = block_info["block"]
            abs_addr_str = (
                f"0x{block_info['abs_addr']:x}" if block_info["abs_addr"] else "unknown"
            )

            mod_name = block_info["module_name"]

            hits_str = self.inspector._format_hit_count(block_info["hits"])
            mod_name = self.inspector._truncate_module_name(
                mod_name, has_hits=False
            )  # blocks view doesn't depend on hit count presence

            line_text = f"{mod_name:<{self.inspector.BLOCK_MODULE_WIDTH}} 0x{block.start:08x} {abs_addr_str:<{self.inspector.ADDRESS_FIELD_WIDTH}} {block.size:<{self.inspector.SIZE_FIELD_WIDTH}} {hits_str:<{self.inspector.HITS_FIELD_WIDTH}}"
            item = SelectableText(line_text)
            item = urwid.AttrMap(item, None, focus_map="focus")
            items.append(item)

        if len(self.inspector.block_list) > max_blocks:
            remaining = len(self.inspector.block_list) - max_blocks
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

    def create_stats_view(self):
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
            f"Coverage Analysis (Filtered: {self.inspector.current_filter})"
            if self.inspector.current_filter
            else "Coverage Analysis (All Modules)"
        )
        return [
            urwid.AttrMap(urwid.Text(title_text, align="center"), "title"),
            urwid.Divider(),
        ]

    def _create_basic_stats(self):
        """Create basic statistics section"""
        cov = self.inspector.filtered_coverage
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
        cov = self.inspector.filtered_coverage
        total_size = sum(block.size for block in cov.data.basic_blocks)
        avg_size = total_size / len(cov.data.basic_blocks)
        min_size = min(block.size for block in cov.data.basic_blocks)
        max_size = max(block.size for block in cov.data.basic_blocks)

        total_size_str = self.inspector._format_size(total_size).replace(" B", " bytes")

        return [
            f"Total coverage size: {total_size_str}",
            f"Average block size: {avg_size:.1f} bytes",
            f"Block size range: {min_size} - {max_size} bytes",
        ]

    def _get_hit_count_stats(self):
        """Get hit count statistics"""
        hit_counts = self.inspector.filtered_coverage.data.hit_counts
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
        cov = self.inspector.filtered_coverage

        if cov.data.basic_blocks:
            addresses = cov.get_absolute_addresses()
            if addresses:
                min_addr = min(addresses)
                max_addr = max(addresses)
                addr_range = max_addr - min_addr

                return [
                    urwid.AttrMap(
                        urwid.Text("Address Space", align="center"), "subtitle"
                    ),
                    urwid.Text(f"  Range: 0x{min_addr:x} - 0x{max_addr:x}"),
                    urwid.Text(
                        f"  Span: {addr_range:,} bytes ({addr_range / 1024 / 1024:.1f} MB)"
                    ),
                    urwid.Divider(),
                ]
        return []

    def _create_hit_distribution_stats(self):
        """Create hit count distribution section"""
        cov = self.inspector.filtered_coverage
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
            urwid.AttrMap(
                urwid.Text("Hit Count Distribution", align="center"), "subtitle"
            )
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
        if not self.inspector.module_list:
            return []

        content = [
            urwid.AttrMap(
                urwid.Text("Top Modules by Coverage", align="center"), "subtitle"
            )
        ]

        for i, mod_info in enumerate(self.inspector.module_list[:5]):
            mod_name = os.path.basename(mod_info["name"])
            mod_name = self.inspector._truncate_module_name(mod_name, has_hits=False)
            content.append(
                urwid.Text(f"  {i+1}. {mod_name} ({mod_info['percentage']:.1f}%)")
            )

        return content
