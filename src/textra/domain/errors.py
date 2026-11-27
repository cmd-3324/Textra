"""Domain errors: one hierarchy, no framework exceptions leaking out.

The GUI, the CLI and the tests all need to distinguish "the user picked a PDF",
"this machine has no OCR engine" and "the engine crashed". Encoding that as a
stable class hierarchy keeps status/exit-code mapping in one place and lets the
UI show a useful sentence instead of a traceback.

Every error carries a ``message`` that is safe to show to a person. Anything
needed to diagnose the failure goes in ``context``, which is logged, never
displayed verbatim.
"""

from __future__ import annotations

from typing import Any


class TextraError(Exception):
    """Base class for every failure Textra raises deliberately."""

    #: Short machine-readable identifier, stable across releases.
    code: str = "textra_error"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = context or {}

    def __str__(self) -> str:
        return self.message


class ConfigurationError(TextraError):
    """The environment does not describe a runnable application."""

    code = "configuration_error"


class InvalidImageError(TextraError):
    """The bytes are not a usable image."""

    code = "invalid_image"


class UnsupportedImageFormatError(InvalidImageError):
    """The image is valid but its format is not accepted."""

    code = "unsupported_image_format"


class ImageTooLargeError(InvalidImageError):
    """The upload or its decoded pixel grid exceeds a configured ceiling."""

    code = "image_too_large"


class EngineInitializationError(TextraError):
    """An engine is missing, not installed, or failed to load its model."""

    code = "engine_initialization_failed"


class EngineExecutionError(TextraError):
    """An engine loaded but failed while reading this image."""

    code = "engine_execution_failed"


class ExtractionTimeoutError(TextraError):
    """One image took longer than the configured budget."""

    code = "extraction_timeout"


class ExtractionCancelledError(TextraError):
    """The caller cancelled the extraction; no result was produced."""

    code = "extraction_cancelled"


class ExtractionError(TextraError):
    """An unexpected failure, wrapped so every caller handles one type."""

    code = "extraction_failed"


__all__ = [
    "ConfigurationError",
    "EngineExecutionError",
    "EngineInitializationError",
    "ExtractionCancelledError",
    "ExtractionError",
    "ExtractionTimeoutError",
    "ImageTooLargeError",
    "InvalidImageError",
    "TextraError",
    "UnsupportedImageFormatError",
]
