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
from typing import Any

import numpy as np

from ..domain.errors import EngineExecutionError, EngineInitializationError
from ..domain.models import BoundingBox, EngineAvailability, EngineSettings, RawLine
from .language import rapidocr_language

INSTALL_HINT = "pip install rapidocr onnxruntime"

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
        except ImportError as exc:  # pragma: no cover - availability covers it
            raise EngineInitializationError(
                "RapidOCR is not installed. Install it with: " + INSTALL_HINT,
                context={"package": "rapidocr"},
            ) from exc

        language = rapidocr_language(self._settings.language)
        params: dict[str, Any] = {
            "Global.log_level": "warning",
            "Global.text_score": 0.3,
            "Rec.lang_type": language,
        }
        if self._settings.model_dir is not None:
            params["Global.model_root_dir"] = str(self._settings.model_dir)
        if language in _V5_LANGUAGES:
            params["Rec.ocr_version"] = "PP-OCRv5"
            params["Rec.model_type"] = "mobile"

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
            output = self._runtime(image_png)
        except Exception as exc:
            raise EngineExecutionError(
                "The OCR engine failed while reading this image.",
                context={"engine": self.name, "error": repr(exc)},
            ) from exc

        if output is None or output.txts is None or output.boxes is None:
            return ()

        boxes = np.asarray(output.boxes, dtype=float)
        lines: list[RawLine] = []
        for box, text, score in zip(boxes, output.txts, output.scores, strict=False):
            cleaned = (text or "").strip()
            if not cleaned:
                continue
            polygon = tuple((float(x), float(y)) for x, y in box)
            lines.append(
                RawLine(
                    text=cleaned,
                    confidence=_clamp(float(score)),
                    bbox=_box_from_polygon(polygon),
                    polygon=polygon,
                )
            )
        return tuple(lines)

    def close(self) -> None:
        self._runtime = None

    @property
    def version(self) -> str:
        return self._version


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


__all__ = ["RapidOcrEngine"]
