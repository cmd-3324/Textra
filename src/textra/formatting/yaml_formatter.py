"""YAML: the same documented schema as JSON, in the form people hand-edit.

The payload comes from :func:`~textra.formatting.json_formatter.result_to_dict`
rather than being rebuilt here, so the two structured formats cannot drift apart:
a field added to the contract appears in both or in neither.

``safe_dump`` refuses arbitrary Python objects, which is exactly the guard wanted
here - the schema is plain data, and a leaked dataclass would be a bug.
"""

from __future__ import annotations

import yaml

from ..domain.models import ExtractionResult, OutputFormat
from .json_formatter import result_to_dict


class YamlFormatter:
    """Renders the JSON schema as YAML, preserving key order and Unicode."""

    output_format: OutputFormat = OutputFormat.YAML

    def render(self, result: ExtractionResult) -> str:
        return str(
            yaml.safe_dump(
                result_to_dict(result),
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=100,
            )
        )


__all__ = ["YamlFormatter"]
