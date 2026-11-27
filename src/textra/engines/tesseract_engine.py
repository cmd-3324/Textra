"""Tesseract backend, for machines that already have the binary.

Tesseract remains the most predictable engine for Latin and many historic
scripts, and it is the natural second choice when RapidOCR's models cannot be
downloaded. It is optional: the Python package and the native binary are both
required, and the availability probe explains which one is missing rather than
letting the first scan fail.

``pytesseract`` shells out to the binary, so parallel calls are safe; the
per-call timeout is passed to the subprocess as a second line of defence behind
the service's own deadline.
"""

from __future__ import annotations

import importlib.metadata
import shutil
from io import BytesIO

from PIL import Image

from ..domain.errors import EngineExecutionError, EngineInitializationError
from ..domain.models import BoundingBox, EngineAvailability, EngineSettings, RawLine

INSTALL_HINT = (
    "pip install 'textra[tesseract]' and install the tesseract binary "
    "(Windows: winget install UB-Mannheim.TesseractOCR; "
    "macOS: brew install tesseract; Debian/Ubuntu: sudo apt install tesseract-ocr)"
)


class TesseractEngine:
    """An :class:`~textra.domain.ports.OCREngine` backed by the tesseract CLI."""

    name = "tesseract"

    def __init__(self, settings: EngineSettings) -> None:
        self._settings = settings
        self._version = "not initialized"

    # -- provider protocol ------------------------------------------------ #
    @classmethod
    def availability(cls, settings: EngineSettings) -> EngineAvailability:
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            return EngineAvailability(
                name=cls.name,
                available=False,
                detail="the pytesseract package is not installed",
                requires=INSTALL_HINT,
            )

        binary = _resolve_binary(settings)
        if binary is None:
            return EngineAvailability(
                name=cls.name,
                available=False,
                detail="the tesseract executable was not found on PATH",
                requires=INSTALL_HINT,
            )
        return EngineAvailability(
            name=cls.name,
            available=True,
            detail=f"pytesseract {_package_version('pytesseract')} ({binary})",
            requires=None,
        )

    @classmethod
    def create(cls, settings: EngineSettings) -> TesseractEngine:
        return cls(settings)

    # -- engine protocol --------------------------------------------------- #
    def initialize(self) -> None:
        try:
            import pytesseract
        except ImportError as exc:  # pragma: no cover - availability covers it
            raise EngineInitializationError(
                "pytesseract is not installed. " + INSTALL_HINT,
                context={"package": "pytesseract"},
            ) from exc

        binary = _resolve_binary(self._settings)
        if binary is None:
            raise EngineInitializationError(
                "The tesseract executable was not found. " + INSTALL_HINT,
                context={"tesseract_cmd": str(self._settings.tesseract_cmd or "")},
            )
        pytesseract.pytesseract.tesseract_cmd = binary

        try:
            version = pytesseract.get_tesseract_version()
        except Exception as exc:
            raise EngineInitializationError(
                "The tesseract executable could not be run. " + INSTALL_HINT,
                context={"binary": binary, "error": repr(exc)},
            ) from exc

        self._version = f"tesseract {version}"

    def recognize(self, image_png: bytes) -> tuple[RawLine, ...]:
        try:
            import pytesseract
        except ImportError as exc:  # pragma: no cover
            raise EngineExecutionError("pytesseract is not installed.") from exc

        try:
            with Image.open(BytesIO(image_png)) as image:
                data = pytesseract.image_to_data(
                    image.convert("RGB"),
                    lang=self._settings.language,
                    config="--oem 3 --psm 3",
                    output_type=pytesseract.Output.DICT,
                    timeout=max(1, int(self._settings.timeout_seconds)),
                )
        except Exception as exc:
            raise EngineExecutionError(
                "Tesseract failed while reading this image.",
                context={"engine": self.name, "error": repr(exc)},
            ) from exc

        return _lines_from_data(data)

    def close(self) -> None:
        """Nothing to release: each call runs in its own subprocess."""

    @property
    def version(self) -> str:
        return self._version


def _resolve_binary(settings: EngineSettings) -> str | None:
    if settings.tesseract_cmd is not None:
        candidate = str(settings.tesseract_cmd)
        return candidate if shutil.which(candidate) or _is_file(candidate) else None
    return shutil.which("tesseract")


def _is_file(path: str) -> bool:
    from pathlib import Path

    return Path(path).is_file()


def _lines_from_data(data: dict[str, list[str]]) -> tuple[RawLine, ...]:
    """Rebuild line-level results from tesseract's word-level table.

    ``image_to_data`` reports one row per word. Grouping by
    ``(block_num, par_num, line_num)`` and unioning the boxes recovers the line
    the engine actually read, which is the unit the layout analyser expects.
    """
    grouped: dict[tuple[int, int, int], list[int]] = {}
    for index, raw_text in enumerate(data.get("text", [])):
        if not str(raw_text).strip():
            continue
        key = (
            int(data["block_num"][index]),
            int(data["par_num"][index]),
            int(data["line_num"][index]),
        )
        grouped.setdefault(key, []).append(index)

    lines: list[RawLine] = []
    for key in sorted(grouped):
        indices = grouped[key]
        words = [str(data["text"][i]).strip() for i in indices]
        confidences = [float(data["conf"][i]) for i in indices if float(data["conf"][i]) >= 0]
        if not confidences:
            continue
        left = min(int(data["left"][i]) for i in indices)
        top = min(int(data["top"][i]) for i in indices)
        right = max(int(data["left"][i]) + int(data["width"][i]) for i in indices)
        bottom = max(int(data["top"][i]) + int(data["height"][i]) for i in indices)
        lines.append(
            RawLine(
                text=" ".join(word for word in words if word),
                confidence=max(0.0, min(1.0, sum(confidences) / len(confidences) / 100.0)),
                bbox=BoundingBox(float(left), float(top), float(right), float(bottom)),
            )
        )
    return tuple(lines)


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover
        return "unknown"


__all__ = ["TesseractEngine"]
