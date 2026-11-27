"""The Pillow implementation of the :class:`ImagePreprocessor` port.

This adapter is the only place in the core that decodes pixels. It validates,
optionally preprocesses, and re-encodes the result as PNG so every engine -
local or remote - consumes exactly one documented format.

PNG rather than JPEG is deliberate: preprocessing has already changed the
pixels, and a lossy second encode would add ringing right where OCR looks for
stroke edges. The cost is a slightly larger in-memory payload, not disk I/O.
"""

from __future__ import annotations

import io

from PIL import Image

from ..domain.models import ImageDocument, ImageLimits, PreprocessOptions, PreprocessReport
from .chain import build_chain
from .quality import looks_blank
from .validation import DecodedImage, decode_image

WARNING_BLANK = "The image appears to be blank; there is almost no ink to read."
WARNING_UPSCALED = "The image was enlarged before OCR; accuracy may suffer."

#: An enlarged image is worth mentioning only when it grew substantially.
UPSCALE_WARNING_FACTOR = 1.5


class PillowPreprocessor:
    """Validate bytes, run the enabled steps, hand back a PNG document."""

    def __init__(self, limits: ImageLimits, defaults: PreprocessOptions) -> None:
        self._limits = limits
        self._defaults = defaults

    @property
    def limits(self) -> ImageLimits:
        return self._limits

    @property
    def defaults(self) -> PreprocessOptions:
        return self._defaults

    def prepare(
        self,
        data: bytes,
        *,
        source_name: str,
        preprocess: bool,
        options: PreprocessOptions | None = None,
    ) -> ImageDocument:
        """Return a decoded, optionally preprocessed PNG or raise a domain error."""
        decoded = decode_image(data, self._limits)
        chosen = options or self._defaults

        if preprocess:
            working, report = self._preprocess(decoded, chosen)
        else:
            working = decoded.image
            report = PreprocessReport(
                applied=(),
                skipped=True,
                width=working.width,
                height=working.height,
            )

        warnings: list[str] = []
        if looks_blank(working):
            warnings.append(WARNING_BLANK)
        if self._was_enlarged(decoded, working):
            warnings.append(WARNING_UPSCALED)

        return ImageDocument(
            png_bytes=_encode_png(working),
            format=decoded.format,
            width=working.width,
            height=working.height,
            original_width=decoded.original_width,
            original_height=decoded.original_height,
            byte_size=decoded.byte_size,
            source_name=source_name,
            preprocessing=report,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _was_enlarged(decoded: DecodedImage, working: Image.Image) -> bool:
        longest_before = max(decoded.original_width, decoded.original_height, 1)
        return max(working.width, working.height) > longest_before * UPSCALE_WARNING_FACTOR

    def _preprocess(
        self, decoded: DecodedImage, options: PreprocessOptions
    ) -> tuple[Image.Image, PreprocessReport]:
        chain = build_chain(options)
        working = chain.run(decoded.image)

        applied = list(chain.applied)
        if options.auto_orient and decoded.exif_rotated:
            # Orientation happened during decode, before any chain step existed.
            applied.insert(0, "orientation")

        report = PreprocessReport(
            applied=tuple(applied),
            skipped=False,
            skew_angle_degrees=chain.skew_angle_degrees,
            resized=chain.resized,
            width=working.width,
            height=working.height,
        )
        return working, report


def _encode_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


__all__ = ["WARNING_BLANK", "WARNING_UPSCALED", "PillowPreprocessor"]
