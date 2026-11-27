"""RapidOCR backend: the default, and the only one with no system dependency.

RapidOCR runs PP-OCR detection/recognition models through ONNX Runtime on the
CPU. It is a normal wheel install, which matters for a desktop app that cannot
ask a user to install a C++ binary before their first scan. Models are fetched
once on first use and cached; ``TEXTRA_MODEL_DIR`` pins that cache for offline
machines.

The import is deferred to ``initialize`` so that a Tesseract-only deployment
never pays the ONNX Runtime startup cost, and so that a missing optional wheel
produces a domain error with install instructions instead of an ImportError at
application start.
"""

from __future__ import annotations

import importlib.metadata
import io
from typing import Any

import numpy as np
from PIL import Image

from ..domain.errors import EngineExecutionError, EngineInitializationError
from ..domain.models import BoundingBox, EngineAvailability, EngineSettings, RawLine
from .language import rapidocr_language

INSTALL_HINT = "pip install rapidocr onnxruntime"

#: Detector windows, in pixels of the image the engine receives.
#:
#: PP-OCR's detection head expects an input around 960 px. Handed a whole
#: 2560 px screenshot it renders 13 px UI text as noise and returns nothing at
#: all - the failure mode where a pasted screen produces an empty document.
#: Reading overlapping windows keeps glyphs at the scale the model was trained
#: for. Only the centre of a window is trusted, so a line lying on a seam is
#: reported once, by the window that holds its middle.
TILE_WIDTH = 1400
TILE_HEIGHT = 900
TILE_OVERLAP = 120

#: Scripts RapidOCR's PP-OCRv6 default models were not trained for. Those fall
#: back to the PP-OCRv5 mobile recognition model, which covers the wider set.
_V5_LANGUAGES = frozenset(
    {
        "arabic",
        "chinese_cht",
        "cyrillic",
        "devanagari",
        "japan",
        "korean",
        "latin",
        "ta",
        "te",
        "ka",
        "th",
        "el",
        "eslav",
    }
)


class RapidOcrEngine:
    """An :class:`~textra.domain.ports.OCREngine` backed by RapidOCR."""

    name = "rapidocr"

    def __init__(self, settings: EngineSettings) -> None:
        self._settings = settings
        self._runtime: Any | None = None
        self._version = "not initialized"

    # -- provider protocol ------------------------------------------------ #
    @classmethod
    def availability(cls, settings: EngineSettings) -> EngineAvailability:
        missing: list[str] = []
        versions: list[str] = []
        for package in ("rapidocr", "onnxruntime"):
            try:
                versions.append(f"{package} {importlib.metadata.version(package)}")
            except importlib.metadata.PackageNotFoundError:
                missing.append(package)
        if missing:
            return EngineAvailability(
                name=cls.name,
                available=False,
                detail=f"missing Python package(s): {', '.join(missing)}",
                requires=INSTALL_HINT,
            )
        return EngineAvailability(
            name=cls.name,
            available=True,
            detail=", ".join(versions),
            requires=None,
        )

    @classmethod
    def create(cls, settings: EngineSettings) -> RapidOcrEngine:
        return cls(settings)

    # -- engine protocol --------------------------------------------------- #
    def initialize(self) -> None:
        try:
            from rapidocr import RapidOCR
            from rapidocr.utils.typings import ModelType, OCRVersion
        except ImportError as exc:  # pragma: no cover - availability covers it
            raise EngineInitializationError(
                "RapidOCR is not installed. Install it with: " + INSTALL_HINT,
                context={"package": "rapidocr"},
            ) from exc

        language = rapidocr_language(self._settings.language)
        params: dict[str, Any] = {
            "Global.log_level": "warning",
            "Global.text_score": 0.3,
            # A window is never larger than TILE_WIDTH/TILE_HEIGHT, so this
            # ceiling only guards against an unexpected resize inside the
            # library; the detector's own 736 px minimum side then enlarges a
            # short crop, which is what small text needs.
            "Global.max_side_len": 3200,
            "Rec.lang_type": language,
        }
        if self._settings.model_dir is not None:
            params["Global.model_root_dir"] = str(self._settings.model_dir)
        if language in _V5_LANGUAGES:
            # Model selection is enum-typed; strings raise TypeError inside
            # RapidOCR's parameter parser.
            params["Rec.ocr_version"] = OCRVersion.PPOCRV5
            params["Rec.model_type"] = ModelType.MOBILE

        try:
            self._runtime = RapidOCR(params=params)
        except Exception as exc:
            raise EngineInitializationError(
                "RapidOCR could not load its models. Check the network on first run, "
                "or set TEXTRA_MODEL_DIR to a folder containing the models.",
                context={"language": language, "error": repr(exc)},
            ) from exc

        self._version = f"rapidocr {_package_version('rapidocr')}"

    def recognize(self, image_png: bytes) -> tuple[RawLine, ...]:
        if self._runtime is None:
            raise EngineExecutionError("The OCR engine was used before initialization.")

        try:
            image = _decode(image_png)
            tiles = _plan_tiles(image)
            if tiles is None:
                return tuple(self._recognise(image_png, 0, 0, None))

            lines: list[RawLine] = []
            for box, core in tiles:
                cropped = image.crop(box)
                lines.extend(self._recognise(_encode(cropped), box[0], box[1], core))
            return tuple(lines)
        except Exception as exc:
            raise EngineExecutionError(
                "The OCR engine failed while reading this image.",
                context={"engine": self.name, "error": repr(exc)},
            ) from exc

    def _recognise(
        self,
        image_png: bytes,
        offset_x: int,
        offset_y: int,
        core: tuple[float, float, float, float] | None,
    ) -> list[RawLine]:
        """Run one inference and shift its geometry into image coordinates."""
        if self._runtime is None:  # pragma: no cover - checked by recognize
            raise EngineExecutionError("The OCR engine was used before initialization.")

        output = self._runtime(image_png)
        if output is None or output.txts is None or output.boxes is None:
            return []

        boxes = np.asarray(output.boxes, dtype=float)
        lines: list[RawLine] = []
        for box, text, score in zip(boxes, output.txts, output.scores, strict=False):
            cleaned = (text or "").strip()
            if not cleaned:
                continue
            polygon = tuple((float(x) + offset_x, float(y) + offset_y) for x, y in box)
            bbox = _box_from_polygon(polygon)
            if core is not None and not _contains_point(core, bbox):
                continue
            lines.append(
                RawLine(
                    text=cleaned,
                    confidence=_clamp(float(score)),
                    bbox=bbox,
                    polygon=polygon,
                )
            )
        return lines

    def close(self) -> None:
        self._runtime = None

    @property
    def version(self) -> str:
        return self._version


def _decode(image_png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(image_png)).convert("RGB")


def _encode(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _plan_tiles(
    image: Image.Image,
) -> list[tuple[tuple[int, int, int, int], tuple[float, float, float, float]]] | None:
    """Split a large image into overlapping windows, or ``None`` to read it whole.

    Each entry is the crop rectangle plus the absolute rectangle whose lines the
    crop is allowed to report. Windows overlap, their cores do not: a detection
    is kept by exactly one window, so no line is duplicated and no line on a
    seam is lost.
    """
    width, height = image.size
    if width <= TILE_WIDTH and height <= TILE_HEIGHT:
        return None

    xs = _starts(width, TILE_WIDTH, TILE_WIDTH - TILE_OVERLAP)
    ys = _starts(height, TILE_HEIGHT, TILE_HEIGHT - TILE_OVERLAP)
    x_cores = _core_edges(xs, TILE_WIDTH, width)
    y_cores = _core_edges(ys, TILE_HEIGHT, height)

    tiles: list[tuple[tuple[int, int, int, int], tuple[float, float, float, float]]] = []
    for top, (core_top, core_bottom) in zip(ys, y_cores, strict=True):
        for left, (core_left, core_right) in zip(xs, x_cores, strict=True):
            crop = (left, top, min(left + TILE_WIDTH, width), min(top + TILE_HEIGHT, height))
            tiles.append((crop, (core_left, core_top, core_right, core_bottom)))
    return tiles


def _starts(total: int, size: int, step: int) -> list[int]:
    """Tile origins along one axis; the last window sits flush with the edge."""
    if total <= size:
        return [0]
    starts = list(range(0, total - size, step))
    starts.append(total - size)
    return starts


def _core_edges(starts: list[int], size: int, total: int) -> list[tuple[int, int]]:
    """Turn origins into non-overlapping ownership spans.

    Neighbouring windows share ``TILE_OVERLAP`` pixels; the seam runs through the
    middle of that overlap, so every pixel belongs to exactly one window.
    """
    edges: list[tuple[int, int]] = []
    for index, start in enumerate(starts):
        left = 0 if index == 0 else (size + starts[index - 1] + start) // 2
        right = total if index == len(starts) - 1 else (size + start + starts[index + 1]) // 2
        edges.append((left, right))
    return edges


def _contains_point(rect: tuple[float, float, float, float], bbox: BoundingBox) -> bool:
    center_x = (bbox.x0 + bbox.x1) / 2.0
    center_y = (bbox.y0 + bbox.y1) / 2.0
    left, top, right, bottom = rect
    return left <= center_x < right and top <= center_y < bottom


def _box_from_polygon(polygon: tuple[tuple[float, float], ...]) -> BoundingBox:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return BoundingBox(min(xs), min(ys), max(xs), max(ys))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover
        return "unknown"


__all__ = ["TILE_HEIGHT", "TILE_OVERLAP", "TILE_WIDTH", "RapidOcrEngine"]
