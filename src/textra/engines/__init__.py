"""OCR engine adapters and the registry that selects between them."""

from __future__ import annotations

from .language import RAPIDOCR_LANGUAGES, rapidocr_language
from .rapidocr_engine import RapidOcrEngine
from .registry import ENTRY_POINT_GROUP, EngineRegistry, build_default_registry
from .tesseract_engine import TesseractEngine

__all__ = [
    "ENTRY_POINT_GROUP",
    "RAPIDOCR_LANGUAGES",
    "EngineRegistry",
    "RapidOcrEngine",
    "TesseractEngine",
    "build_default_registry",
    "rapidocr_language",
]
