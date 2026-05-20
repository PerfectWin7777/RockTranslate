# src/core/reading_order.py

from typing import List
from core.domain import FitzBlock


class ReadingOrderSorter:
    """
    Sorts FitzBlocks on a page into the natural human reading order.
    Handles complex, alternating layouts (e.g., 1-column header, 
    2-column body, 1-column wide figure, 2-column footer).
    """

    def __init__(self, column_tolerance_ratio: float = 0.6, alignment_mid_tolerance: float = 15.0):
        """
        Args:
            column_tolerance_ratio: Blocks wider than this fraction of page width are 1-column.
            alignment_mid_tolerance: Max distance in points from page center to consider a block centered.
        """
        self.column_tolerance_ratio = column_tolerance_ratio
        self.alignment_mid_tolerance = alignment_mid_tolerance

    def process_page_layout(self, blocks: List[FitzBlock], page_width: float) -> List[FitzBlock]:
        """
        Calculates alignments, detects column scopes, and sorts blocks in reading order.
        """
        if not blocks:
            return []

        # Step 1: Assign alignment & initial column layout labels
        page_mid = page_width / 2.0
        for block in blocks:
            self._apply_block_properties(block, page_width, page_mid)

        # Step 2: Slice the page vertically into horizontal Y-bands (strips)
        # We sort blocks from top to bottom first to identify horizontal separators
        sorted_by_y = sorted(blocks, key=lambda b: b.top)
        bands: List[List[FitzBlock]] = []
        current_band: List[FitzBlock] = []

        for block in sorted_by_y:
            # If we encounter a full-width block, it acts as a layout separator (barrier)
            if block.column == 0:
                if current_band:
                    bands.append(current_band)
                    current_band = []
                bands.append([block])  # Full-width block sits in its own band
            else:
                current_band.append(block)

        if current_band:
            bands.append(current_band)

        # Step 3: Sort each band internally based on its local layout (1-col or 2-col)
        ordered_blocks: List[FitzBlock] = []
        for band in bands:
            if len(band) == 1:
                ordered_blocks.append(band[0])
            else:
                sorted_band = self._sort_band_by_columns(band, page_mid)
                ordered_blocks.extend(sorted_band)

        # Assign updated sequential block IDs based on final reading order
        for idx, block in enumerate(ordered_blocks):
            block.block_id = idx

        return ordered_blocks

    def _apply_block_properties(self, block: FitzBlock, page_width: float, page_mid: float) -> None:
        """
        Determines the block's visual alignment and assigns its column structure ID.
        """
        block_width = block.width

        # Detect Column Layout (0 = Full width, 1 = Left col, 2 = Right col)
        if block_width > page_width * self.column_tolerance_ratio:
            block.column = 0
        elif block.x_center < page_mid:
            block.column = 1
        else:
            block.column = 2

        # Detect Alignment (Matching poc_render.py's criteria)
        is_centered = (
            abs(block.x_center - page_mid) < self.alignment_mid_tolerance 
            and block_width < (page_width * 0.8)
        )
        should_justify = len(block.lines) > 1 or block_width > (page_width * 0.4)

        if is_centered:
            block.alignment = "center"
        elif should_justify:
            block.alignment = "justify"
        else:
            block.alignment = "left"

    def _sort_band_by_columns(self, band: List[FitzBlock], page_mid: float) -> List[FitzBlock]:
        """
        Sorts blocks within a mixed band: left column blocks top-to-bottom first, 
        then right column blocks top-to-bottom.
        """
        left_column = [b for b in band if b.column == 1]
        right_column = [b for b in band if b.column == 2]
        undecided = [b for b in band if b.column == 0]  # Fallback for unexpected items

        # Sort left column top-to-bottom
        left_sorted = sorted(left_column, key=lambda b: b.top)
        
        # Sort right column top-to-bottom
        right_sorted = sorted(right_column, key=lambda b: b.top)
        
        # Fallbacks sorted by Y
        undecided_sorted = sorted(undecided, key=lambda b: b.top)

        # Natural reading flow: Left column first, then Right column
        return left_sorted + right_sorted + undecided_sorted