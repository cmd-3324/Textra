"""Ports: the interfaces the core depends on, and everything else implements.

`typing.Protocol` rather than ABCs: adapters do not have to import Textra to
satisfy a protocol, which keeps a third-party engine a plain class with three
methods. Structural typing also makes test doubles trivial - the fake engine in
the test suite is a dozen lines with no inheritance.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from .models import (
    EngineAvailability,
    EngineSettings,
    ExtractionResult,
    ImageDocument,
    OutputFormat,
    PreprocessOptions,
    RawLine,
)

#: Called with a short human-readable stage name and a 0-100 percentage.
ProgressCallback = Callable[[str, int], None]


@runtime_checkable
class OCREngine(Protocol):
    """A text-recognition backend.

    ``recognize`` receives encoded PNG bytes, not a library image object: a
    remote backend needs bytes, and a local one can decode them without the
    domain ever naming Pillow.
    """

    name: str
    version: str

    def initialize(self) -> None:
        """Load models or import native libraries; may be slow and raise."""

    def recognize(self, image_png: bytes) -> tuple[RawLine, ...]:
        """Return detections for one image, or raise a domain error."""

    def close(self) -> None:
        """Release native resources. Must be safe to call more than once."""


class EngineProvider(Protocol):
    """A registry entry: a class that can describe and build an engine."""

    name: str

    @classmethod
    def availability(cls, settings: EngineSettings) -> EngineAvailability:
        """Report whether this engine can run here, without constructing it."""

    @classmethod
    def create(cls, settings: EngineSettings) -> OCREngine:
        """Build and return the engine. ``initialize`` is called separately."""


class ImagePreprocessor(Protocol):
    """Turns untrusted bytes into a validated, OCR-ready PNG."""

    def prepare(
        self,
        data: bytes,
        *,
        source_name: str,
        preprocess: bool,
        options: PreprocessOptions | None = None,
    ) -> ImageDocument:
        """Validate and (optionally) preprocess, or raise ``InvalidImageError``."""


class ResultFormatter(Protocol):
    """Renders a result in one output format."""

    output_format: OutputFormat

    def render(self, result: ExtractionResult) -> str:
        """Return the document text for this format."""


__all__ = [
    "EngineProvider",
    "ImagePreprocessor",
    "OCREngine",
    "ProgressCallback",
    "ResultFormatter",
]
