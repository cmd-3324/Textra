"""Typed configuration, read once from the environment and an optional ``.env``.

Rules this module enforces on the rest of the codebase:

* No other module reads ``os.environ``. A new setting is added here, given a
  default, listed in ``.env.example`` and validated at load.
* Failures are loud and early. ``TEXTRA_MAX_IMAGE_BYTES=lots`` stops startup
  with a message naming the variable, rather than raising inside a worker
  thread where the user sees a dialog with no explanation.
* Paths are ``pathlib.Path`` from the moment they are parsed.

The settings object is frozen and safe to share between the UI thread and
extraction workers.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .domain.models import EngineSettings, ImageLimits, PreprocessOptions

DEFAULT_ALLOWED_FORMATS = "PNG,JPEG,WEBP,BMP,TIFF"

_ENGINE_NAME = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
_LANGUAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_+-]{1,31}$")


class Settings(BaseSettings):
    """Every knob Textra has, with a default that works on a fresh machine."""

    model_config = SettingsConfigDict(
        env_prefix="TEXTRA_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    # -- application ---------------------------------------------------- #
    environment: Literal["development", "test", "production"] = "development"
    default_engine: str = "auto"

    # -- OCR ------------------------------------------------------------ #
    ocr_language: str = "en"
    extraction_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    min_confidence: float = Field(default=0.0, ge=0, le=1)
    tesseract_cmd: str | None = None
    model_dir: str | None = None

    # -- ingestion ------------------------------------------------------ #
    allowed_formats: str = DEFAULT_ALLOWED_FORMATS
    max_image_bytes: int = Field(default=20 * 1024 * 1024, ge=1024)
    max_image_pixels: int = Field(default=80_000_000, ge=10_000)
    max_image_side: int = Field(default=15_000, ge=64)
    min_image_side: int = Field(default=8, ge=1)

    # -- preprocessing -------------------------------------------------- #
    preprocess_enabled: bool = True
    preprocess_auto_orient: bool = True
    preprocess_autocontrast: bool = True
    preprocess_deskew: bool = True
    preprocess_max_dimension: int = Field(default=3600, ge=0)
    preprocess_min_dimension: int = Field(default=0, ge=0)

    # -- observability --------------------------------------------------- #
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["console", "json"] = "console"
    log_file: str | None = None

    # -- desktop --------------------------------------------------------- #
    ui_theme: Literal["dark", "light"] = "dark"
    ui_window_width: int = Field(default=1180, ge=640, le=8000)
    ui_window_height: int = Field(default=760, ge=480, le=8000)

    # -- validators ------------------------------------------------------ #
    @field_validator("default_engine")
    @classmethod
    def _check_engine_name(cls, value: str) -> str:
        value = value.strip().lower()
        if not _ENGINE_NAME.match(value):
            raise ValueError("must match ^[a-z][a-z0-9_]{1,30}$ (for example 'auto' or 'rapidocr')")
        return value

    @field_validator("ocr_language")
    @classmethod
    def _check_language(cls, value: str) -> str:
        value = value.strip()
        if not _LANGUAGE.match(value):
            raise ValueError("must be a language code such as 'en', 'eng+fas' or 'arabic'")
        return value

    @field_validator("allowed_formats")
    @classmethod
    def _check_formats(cls, value: str) -> str:
        formats = [part.strip().upper() for part in value.split(",") if part.strip()]
        if not formats:
            raise ValueError("must list at least one image format")
        for name in formats:
            if not re.fullmatch(r"[A-Z0-9]{2,12}", name):
                raise ValueError(f"'{name}' is not a Pillow format name")
        return ",".join(dict.fromkeys(formats))

    @field_validator("tesseract_cmd", "model_dir", "log_file", mode="before")
    @classmethod
    def _blank_path_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _check_cross_field_rules(self) -> Settings:
        if (
            self.preprocess_min_dimension
            and self.preprocess_max_dimension
            and self.preprocess_min_dimension > self.preprocess_max_dimension
        ):
            raise ValueError(
                "TEXTRA_PREPROCESS_MIN_DIMENSION must not exceed TEXTRA_PREPROCESS_MAX_DIMENSION"
            )
        if self.min_image_side > self.max_image_side:
            raise ValueError("TEXTRA_MIN_IMAGE_SIDE must not exceed TEXTRA_MAX_IMAGE_SIDE")
        return self

    # -- derived domain values ------------------------------------------- #
    @property
    def allowed_format_set(self) -> frozenset[str]:
        return frozenset(self.allowed_formats.split(","))

    def image_limits(self) -> ImageLimits:
        return ImageLimits(
            max_bytes=self.max_image_bytes,
            max_pixels=self.max_image_pixels,
            max_side=self.max_image_side,
            min_side=self.min_image_side,
            allowed_formats=self.allowed_format_set,
        )

    def preprocess_options(self) -> PreprocessOptions:
        return PreprocessOptions(
            enabled=self.preprocess_enabled,
            auto_orient=self.preprocess_auto_orient,
            autocontrast=self.preprocess_autocontrast,
            deskew=self.preprocess_deskew,
            max_dimension=self.preprocess_max_dimension,
            min_dimension=self.preprocess_min_dimension,
        )

    def engine_settings(self) -> EngineSettings:
        return EngineSettings(
            language=self.ocr_language,
            timeout_seconds=self.extraction_timeout_seconds,
            tesseract_cmd=Path(self.tesseract_cmd).expanduser() if self.tesseract_cmd else None,
            model_dir=Path(self.model_dir).expanduser() if self.model_dir else None,
        )

    def log_file_path(self) -> Path | None:
        return Path(self.log_file).expanduser() if self.log_file else None


__all__ = ["DEFAULT_ALLOWED_FORMATS", "Settings"]
