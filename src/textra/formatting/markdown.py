"""Markdown: a document that survives being pasted into an issue or a wiki.

Geometry already told the layout analyser which blocks are headings and which
are list items; this formatter is the only place that decides how those look.
Heading depth comes from the block's detected level, clamped to six, because
``####### title`` is not Markdown.
"""

from __future__ import annotations

import re

from ..domain.models import BlockKind, ExtractionResult, OutputFormat, TextBlock

MAX_HEADING_LEVEL = 6

#: Mirrors the recogniser in ``textra.pipeline.layout``: a block that was
#: classified as a list item still carries its original marker in ``text``.
_LIST_MARKER = re.compile(r"^(?:[-*•‣∙]|\(?\d{1,3}[.)])\s+")


class MarkdownFormatter:
    """Renders headings, list items and paragraphs with Markdown markup."""

    output_format: OutputFormat = OutputFormat.MARKDOWN

    def render(self, result: ExtractionResult) -> str:
        rendered = [self._render_block(block) for block in result.blocks]
        parts = [part for part in rendered if part]
        if not parts:
            return ""
        return "\n\n".join(parts) + "\n"

    def _render_block(self, block: TextBlock) -> str:
        text = block.text.strip()
        if not text:
            return ""
        if block.kind is BlockKind.HEADING:
            level = min(max(block.level or 1, 1), MAX_HEADING_LEVEL)
            return f"{'#' * level} {text}"
        if block.kind is BlockKind.LIST_ITEM:
            return self._render_list_items(text)
        return text

    @staticmethod
    def _render_list_items(text: str) -> str:
        """Normalise each detected marker to a dash, without doubling it.

        Re-numbering would be wrong: the source may start at 3, and a list that
        used bullets should not silently become an ordered list.
        """
        entries = [
            _LIST_MARKER.sub("", entry.strip(), count=1)
            for entry in text.splitlines()
            if entry.strip()
        ]
        return "\n".join(f"- {entry}" for entry in entries)


__all__ = ["MAX_HEADING_LEVEL", "MarkdownFormatter"]
