"""Plain text: the format to paste into any other application.

Blocks are separated by a blank line, which is how a reader expects paragraphs
to be spaced, and a single trailing newline keeps ``cat`` and editors happy.
Headings keep their text but lose their markup, because this format has none.
"""

from __future__ import annotations

from ..domain.models import ExtractionResult, OutputFormat


class PlainTextFormatter:
    """Renders blocks separated by blank lines."""

    output_format: OutputFormat = OutputFormat.PLAIN

    def render(self, result: ExtractionResult) -> str:
        parts = [block.text.strip() for block in result.blocks if block.text.strip()]
        if not parts:
            return ""
        return "\n\n".join(parts) + "\n"


__all__ = ["PlainTextFormatter"]
