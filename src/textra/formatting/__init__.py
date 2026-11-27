"""Output formatters and the mapping the service renders through."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from ..domain.models import ExtractionResult, OutputFormat
from ..domain.ports import ResultFormatter
from .json_formatter import SCHEMA_VERSION, JsonFormatter, result_to_dict
from .markdown import MarkdownFormatter
from .plain_text import PlainTextFormatter

DEFAULT_FORMATTERS: Mapping[OutputFormat, ResultFormatter] = MappingProxyType(
    {
        OutputFormat.PLAIN: PlainTextFormatter(),
        OutputFormat.MARKDOWN: MarkdownFormatter(),
        OutputFormat.JSON: JsonFormatter(),
    }
)


def format_result(
    result: ExtractionResult,
    output_format: OutputFormat,
    formatters: Mapping[OutputFormat, ResultFormatter] | None = None,
) -> str:
    """Render ``result`` in ``output_format``.

    Raises:
        ValueError: the format has no registered formatter.
    """
    available = formatters or DEFAULT_FORMATTERS
    try:
        formatter = available[output_format]
    except KeyError:
        raise ValueError(f"No formatter is registered for '{output_format}'.") from None
    return formatter.render(result)


__all__ = [
    "DEFAULT_FORMATTERS",
    "SCHEMA_VERSION",
    "JsonFormatter",
    "MarkdownFormatter",
    "PlainTextFormatter",
    "format_result",
    "result_to_dict",
]
