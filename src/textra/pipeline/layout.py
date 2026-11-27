"""Turn a bag of detected lines into the text a person would read.

An OCR engine returns lines with boxes in whatever order its detector produced
them. Writing ``"\\n".join(line.text ...)`` produces a document where columns
interleave and wrapped paragraphs break mid-sentence. This module recovers
structure from geometry alone:

* **rows** - lines whose vertical centres agree within half a line height.
* **blocks** - consecutive rows separated by less than one line height with
  meaningful horizontal overlap; a heading-sized single row ends a block.
* **reading order** - rows top to bottom, lines left to right, or right to left
  when the recognised script is RTL.
* **paragraph text** - wrapped lines are joined, and a trailing hyphen before a
  lowercase continuation is removed ("inter-"/"national" -> "international").
* **kind** - list markers and text height identify list items and headings.

Everything here is pure: tuples in, tuples out, no engine, no file system, no
clock. That is why the layout rules are cheap to test exhaustively.

Known limitation, stated plainly: two-column pages are read row by row, so a
newspaper-style layout interleaves its columns. Detecting columns reliably needs
page segmentation, which is a different problem from OCR.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Sequence

from ..domain.models import BlockKind, BoundingBox, RawLine, TextBlock, TextLine

#: Vertical tolerance for "these lines sit on the same row", in line heights.
ROW_TOLERANCE = 0.55
#: Vertical gap still counted as the same paragraph, in line heights.
#: Tight enough that a blank line between two sections separates them, loose
#: enough that ordinary 1.2-1.5x line spacing stays one paragraph.
PARAGRAPH_GAP = 0.6
#: Minimum horizontal overlap for two rows to belong to one block.
PARAGRAPH_OVERLAP = 0.25
#: A single row at least this much taller than the median is a heading.
HEADING_SCALE = 1.2
#: A heading is short: long wrapped text with one big word is not a title.
HEADING_MAX_WORDS = 14

_LIST_MARKER = re.compile(r"^(?:[-*•‣∙]|\(?\d{1,3}[.)])\s+")
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")
_RTL = re.compile(
    r"[\u0590-\u05ff\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb1d-\ufdff\ufe70-\ufeff]"
)
_TERMINAL = re.compile(r"[.!?。！？:;,]$")
_NO_SPACE_BEFORE = ",.;:!?%)]}>/"


def build_blocks(
    lines: Sequence[RawLine],
    *,
    min_confidence: float = 0.0,
) -> tuple[TextBlock, ...]:
    """Return readable blocks in reading order.

    Args:
        lines: engine detections, in any order.
        min_confidence: detections below this score are discarded; 0 keeps all.
    """
    usable = [_to_text_line(line, min_confidence) for line in lines]
    kept = [line for line in usable if line is not None]
    if not kept:
        return ()

    heights = [line.bbox.height for line in kept if line.bbox.height > 0]
    median_height = statistics.median(heights) if heights else 1.0
    rtl = _is_rtl(" ".join(line.text for line in kept))

    rows = _group_rows(kept, median_height, rtl)
    groups = _group_paragraphs(rows, median_height)

    blocks = [block for group in groups if (block := _make_block(group, median_height)) is not None]
    return tuple(blocks)


def _to_text_line(line: RawLine, min_confidence: float) -> TextLine | None:
    text = " ".join(line.text.split())
    if not text or line.confidence < min_confidence:
        return None
    return TextLine(
        text=text,
        confidence=max(0.0, min(1.0, line.confidence)),
        bbox=line.bbox,
        polygon=line.polygon,
    )


def _is_rtl(text: str) -> bool:
    """True when RTL letters dominate; used only to order lines within a row."""
    rtl = len(_RTL.findall(text))
    if rtl == 0:
        return False
    letters = sum(1 for char in text if char.isalpha())
    return letters > 0 and rtl / letters > 0.3


def _group_rows(lines: list[TextLine], median_height: float, rtl: bool) -> list[list[TextLine]]:
    rows: list[list[TextLine]] = []
    for line in sorted(lines, key=lambda item: (item.bbox.center_y, item.bbox.x0)):
        if rows:
            current = rows[-1]
            row_center = statistics.fmean(item.bbox.center_y for item in current)
            tolerance = ROW_TOLERANCE * max(median_height, line.bbox.height, 1.0)
            if abs(line.bbox.center_y - row_center) <= tolerance:
                current.append(line)
                continue
        rows.append([line])

    for row in rows:
        row.sort(key=lambda item: item.bbox.x1 if rtl else item.bbox.x0, reverse=rtl)
    return rows


def _row_box(row: list[TextLine]) -> BoundingBox:
    box = row[0].bbox
    for line in row[1:]:
        box = box.union(line.bbox)
    return box


def _is_heading_row(row: list[TextLine], median_height: float) -> bool:
    return len(row) == 1 and row[0].bbox.height >= median_height * HEADING_SCALE


def _group_paragraphs(
    rows: list[list[TextLine]], median_height: float
) -> list[list[list[TextLine]]]:
    groups: list[list[list[TextLine]]] = [[rows[0]]]
    previous_was_heading = _is_heading_row(rows[0], median_height)

    for row in rows[1:]:
        previous_box = _row_box(groups[-1][-1])
        row_box = _row_box(row)
        gap = row_box.y0 - previous_box.y1
        overlap = row_box.horizontal_overlap(previous_box)
        same_paragraph = (
            not previous_was_heading
            and gap <= PARAGRAPH_GAP * median_height
            and overlap >= PARAGRAPH_OVERLAP
        )
        if same_paragraph:
            groups[-1].append(row)
        else:
            groups.append([row])
        previous_was_heading = _is_heading_row(row, median_height)

    return groups


def _make_block(group: list[list[TextLine]], median_height: float) -> TextBlock | None:
    lines = tuple(line for row in group for line in row)
    if not lines:
        return None

    # A list is a block whose lines are entries, not a wrapped sentence: joining
    # them with spaces would turn two bullet points into one run-on line.
    is_list = bool(_LIST_MARKER.match(lines[0].text))
    text = _join_lines([line.text for line in lines], separate_lines=is_list)
    if not text:
        return None

    box = lines[0].bbox
    for line in lines[1:]:
        box = box.union(line.bbox)
    confidence = statistics.fmean(line.confidence for line in lines)

    kind, level = _classify(lines, box, text, median_height, is_list=is_list)
    return TextBlock(
        kind=kind,
        text=text,
        confidence=confidence,
        bbox=box,
        lines=lines,
        level=level,
    )


def _classify(
    lines: tuple[TextLine, ...],
    box: BoundingBox,
    text: str,
    median_height: float,
    *,
    is_list: bool,
) -> tuple[BlockKind, int | None]:
    if is_list:
        return BlockKind.LIST_ITEM, None

    if len(lines) > 1 or median_height <= 0:
        return BlockKind.PARAGRAPH, None

    ratio = box.height / median_height
    words = len(text.split())
    if ratio < HEADING_SCALE or words > HEADING_MAX_WORDS or _TERMINAL.search(text):
        return BlockKind.PARAGRAPH, None

    if ratio >= 1.9:
        level = 1
    elif ratio >= 1.45:
        level = 2
    else:
        level = 3
    return BlockKind.HEADING, level


def _join_lines(raw_texts: Sequence[str], *, separate_lines: bool) -> str:
    """Join wrapped lines, undoing hyphenation and spacing CJK correctly."""
    if not raw_texts:
        return ""
    if separate_lines:
        return "\n".join(text.strip() for text in raw_texts if text.strip())

    text = raw_texts[0].strip()
    for raw in raw_texts[1:]:
        piece = raw.strip()
        if not piece:
            continue
        if text.endswith("-") and len(text) > 1 and piece[0].islower():
            text = text[:-1] + piece
        elif _needs_space(text[-1], piece[0]):
            text = f"{text} {piece}"
        else:
            text = text + piece
    return text


def _needs_space(previous: str, following: str) -> bool:
    if not previous or not following:
        return False
    if _CJK.match(previous) or _CJK.match(following):
        return False
    if previous in "([{":
        return False
    return following not in _NO_SPACE_BEFORE


__all__ = ["build_blocks"]
