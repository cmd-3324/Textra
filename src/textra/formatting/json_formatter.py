"""Structured JSON: the machine-readable form of an extraction.

The schema is written by hand rather than derived from dataclasses so that it is
a contract. Renaming a Python field must not silently break a downstream
consumer; it should break this file, visibly, in review.

``schema_version`` is included from the first release so consumers can branch
on it when a future version adds fields.
"""

from __future__ import annotations

import json
from typing import Any

from ..domain.models import ExtractionResult, OutputFormat

SCHEMA_VERSION = "1.0"


class JsonFormatter:
    """Renders the full result: text, blocks, geometry, confidence and timings."""

    output_format: OutputFormat = OutputFormat.JSON

    def __init__(self, indent: int = 2) -> None:
        self._indent = indent

    def render(self, result: ExtractionResult) -> str:
        return json.dumps(
            result_to_dict(result),
            indent=self._indent,
            ensure_ascii=False,
        )


def result_to_dict(result: ExtractionResult) -> dict[str, Any]:
    """The documented schema, as plain Python objects."""
    return {
        "schema_version": SCHEMA_VERSION,
        "text": result.text,
        "image": {
            "source_name": result.image.source_name,
            "format": result.image.format,
            "width": result.image.width,
            "height": result.image.height,
            "original_width": result.image.original_width,
            "original_height": result.image.original_height,
            "byte_size": result.image.byte_size,
        },
        "engine": {
            "name": result.engine.name,
            "version": result.engine.version,
            "language": result.engine.language,
        },
        "preprocessing": {
            "applied": list(result.preprocessing.applied),
            "skipped": result.preprocessing.skipped,
            "skew_angle_degrees": result.preprocessing.skew_angle_degrees,
            "resized": result.preprocessing.resized,
        },
        "timings": result.timings.as_dict(),
        "warnings": list(result.warnings),
        "blocks": [
            {
                "type": block.kind.value,
                "level": block.level,
                "text": block.text,
                "confidence": round(block.confidence, 4),
                "bbox": block.bbox.as_dict(),
                "lines": [
                    {
                        "text": line.text,
                        "confidence": round(line.confidence, 4),
                        "bbox": line.bbox.as_dict(),
                        "polygon": [list(point) for point in line.polygon],
                    }
                    for line in block.lines
                ],
            }
            for block in result.blocks
        ],
    }


__all__ = ["SCHEMA_VERSION", "JsonFormatter", "result_to_dict"]
