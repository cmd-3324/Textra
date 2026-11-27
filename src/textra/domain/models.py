"""Framework-free domain models.

Nothing in this module imports Qt, Pillow or an OCR library. That is what makes
the core testable headlessly and what lets a future web or batch adapter reuse
it unchanged. Images that must travel between layers are carried as encoded
PNG bytes rather than as a live library object, so no vendor type leaks into
the contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class OutputFormat(StrEnum):
    """The serialisations Textra can produce."""

    PLAIN = "plain"
    MARKDOWN = "markdown"
    JSON = "json"

    @property
    def suffix(self) -> str:
        return {"plain": ".txt", "markdown": ".md", "json": ".json"}[self.value]

    @property
    def label(self) -> str:
        return {"plain": "Plain text", "markdown": "Markdown", "json": "Structured JSON"}[
            self.value
        ]


class BlockKind(StrEnum):
    """What a run of lines looks like, judged from geometry alone."""

    PARAGRAPH = "paragraph"
    HEADING = "heading"
    LIST_ITEM = "list_item"


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Axis-aligned box in pixels of the image the engine actually saw."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2.0

    def union(self, other: BoundingBox) -> BoundingBox:
        return BoundingBox(
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        )

    def horizontal_overlap(self, other: BoundingBox) -> float:
        """Shared x-range as a fraction of the narrower box (0..1)."""
        shared = min(self.x1, other.x1) - max(self.x0, other.x0)
        narrower = min(self.width, other.width)
        if shared <= 0.0 or narrower <= 0.0:
            return 0.0
        return min(1.0, shared / narrower)

    def as_dict(self) -> dict[str, float]:
        return {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1}


@dataclass(frozen=True, slots=True)
class RawLine:
    """One detection straight from an engine, before any interpretation."""

    text: str
    confidence: float
    bbox: BoundingBox
    polygon: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True, slots=True)
class TextLine:
    """A detection that survived filtering, ready to be grouped."""

    text: str
    confidence: float
    bbox: BoundingBox
    polygon: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True, slots=True)
class TextBlock:
    """A paragraph-like unit: lines that read as one piece of text."""

    kind: BlockKind
    text: str
    confidence: float
    bbox: BoundingBox
    lines: tuple[TextLine, ...] = ()
    level: int | None = None  # heading depth, 1-6, when kind is HEADING


@dataclass(frozen=True, slots=True)
class ImageLimits:
    """Ingestion ceilings, resolved from configuration once per process."""

    max_bytes: int
    max_pixels: int
    max_side: int
    min_side: int
    allowed_formats: frozenset[str]


@dataclass(frozen=True, slots=True)
class PreprocessOptions:
    """Which optional preprocessing steps to run, and how far they may go."""

    enabled: bool = True
    auto_orient: bool = True
    autocontrast: bool = True
    deskew: bool = True
    max_dimension: int = 2400
    min_dimension: int = 0


@dataclass(frozen=True, slots=True)
class PreprocessReport:
    """What preprocessing actually did, so a bad result can be explained."""

    applied: tuple[str, ...] = ()
    skipped: bool = False
    skew_angle_degrees: float = 0.0
    resized: bool = False
    width: int = 0
    height: int = 0


@dataclass(frozen=True, slots=True)
class ImageDocument:
    """A validated image, encoded once as PNG for every backend to consume."""

    png_bytes: bytes
    format: str
    width: int
    height: int
    original_width: int
    original_height: int
    byte_size: int
    source_name: str
    preprocessing: PreprocessReport
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ImageInfo:
    """Image provenance as it appears in a result (no pixel payload)."""

    source_name: str
    format: str
    width: int
    height: int
    original_width: int
    original_height: int
    byte_size: int


@dataclass(frozen=True, slots=True)
class EngineInfo:
    """Which backend produced a result, and in which language."""

    name: str
    version: str
    language: str


@dataclass(frozen=True, slots=True)
class Timings:
    """Wall-clock milliseconds per stage."""

    preprocessing_ms: float
    recognition_ms: float
    layout_ms: float
    formatting_ms: float
    total_ms: float

    def as_dict(self) -> dict[str, float]:
        return {
            "preprocessing_ms": round(self.preprocessing_ms, 3),
            "recognition_ms": round(self.recognition_ms, 3),
            "layout_ms": round(self.layout_ms, 3),
            "formatting_ms": round(self.formatting_ms, 3),
            "total_ms": round(self.total_ms, 3),
        }


@dataclass(frozen=True, slots=True)
class ExtractionRequest:
    """One caller's intent: these bytes, this format, this engine."""

    data: bytes
    source_name: str
    output_format: OutputFormat = OutputFormat.PLAIN
    engine: str | None = None
    preprocess: bool | None = None
    min_confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.data:
            from .errors import InvalidImageError

            raise InvalidImageError("The image is empty.")
        if self.min_confidence is not None and not 0.0 <= self.min_confidence <= 1.0:
            from .errors import ConfigurationError

            raise ConfigurationError("min_confidence must be between 0 and 1.")


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Everything one image produced, independent of output format."""

    text: str
    blocks: tuple[TextBlock, ...]
    image: ImageInfo
    preprocessing: PreprocessReport
    engine: EngineInfo
    timings: Timings
    warnings: tuple[str, ...] = ()

    @property
    def line_count(self) -> int:
        return sum(len(block.lines) for block in self.blocks)

    @property
    def mean_confidence(self) -> float:
        lines = [line for block in self.blocks for line in block.lines]
        if not lines:
            return 0.0
        return sum(line.confidence for line in lines) / len(lines)


@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    """A result plus the rendered document the caller asked for."""

    result: ExtractionResult
    content: str
    output_format: OutputFormat


@dataclass(frozen=True, slots=True)
class EngineSettings:
    """The narrow slice of configuration an engine is allowed to see."""

    language: str = "en"
    timeout_seconds: float = 60.0
    tesseract_cmd: Path | None = None
    model_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class EngineAvailability:
    """Whether an engine can run on this machine, and what it would need."""

    name: str
    available: bool
    detail: str
    requires: str | None = None


__all__ = [
    "BlockKind",
    "BoundingBox",
    "EngineAvailability",
    "EngineInfo",
    "EngineSettings",
    "ExtractionOutcome",
    "ExtractionRequest",
    "ExtractionResult",
    "ImageDocument",
    "ImageInfo",
    "ImageLimits",
    "OutputFormat",
    "PreprocessOptions",
    "PreprocessReport",
    "RawLine",
    "TextBlock",
    "TextLine",
    "Timings",
]
