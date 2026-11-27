"""Image validation and decoding.

Uploaded bytes - a dropped file or a clipboard image - are hostile input. Three
defences live here, and none can be delegated to Qt:

1. **Sniff, do not trust.** The extension and the clipboard MIME type are
   provenance, not evidence. Pillow's signature detection decides.
2. **Bound before decoding.** ``Image.open`` reads only the header, so pixel
   count and side length are rejected before any large allocation happens. A
   small PNG that expands to gigapixels never reaches the decoder.
3. **Verify, then load.** ``verify()`` walks the container and catches
   truncation; the subsequent ``load()`` catches everything else.

Colour management is deliberately simple: transparency is flattened onto white
because OCR wants dark glyphs on a light page, and every other mode becomes RGB.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from ..domain.errors import ImageTooLargeError, InvalidImageError, UnsupportedImageFormatError
from ..domain.models import ImageLimits

#: Pillow warns above its own threshold and raises above twice it. We install a
#: permissive ceiling and enforce the configured one ourselves, first.
_PIL_SAFETY_FACTOR = 2


@dataclass(frozen=True, slots=True)
class DecodedImage:
    """A decoded RGB image plus everything the report needs to know."""

    image: Image.Image
    format: str
    width: int
    height: int
    original_width: int
    original_height: int
    byte_size: int
    exif_rotated: bool


def _fail_too_large(message: str, **context: int) -> ImageTooLargeError:
    return ImageTooLargeError(message, context=dict(context))


def decode_image(data: bytes, limits: ImageLimits) -> DecodedImage:
    """Validate ``data`` and decode it into an RGB image.

    Raises:
        ImageTooLargeError: byte size, pixel count or a side is over its limit.
        UnsupportedImageFormatError: not an image, or not an accepted format.
        InvalidImageError: truncated, corrupt, or smaller than the minimum side.
    """
    if not data:
        raise InvalidImageError("The image is empty.")

    if len(data) > limits.max_bytes:
        raise _fail_too_large(
            f"The image is {len(data) / 1_048_576:.1f} MB; "
            f"the limit is {limits.max_bytes / 1_048_576:.1f} MB.",
            bytes=len(data),
            max_bytes=limits.max_bytes,
        )

    Image.MAX_IMAGE_PIXELS = limits.max_pixels * _PIL_SAFETY_FACTOR

    try:
        with Image.open(io.BytesIO(data)) as probe:
            image_format = (probe.format or "").upper()
            width, height = probe.size
            exif_orientation = probe.getexif().get(0x0112, 1)
    except UnidentifiedImageError as exc:
        raise UnsupportedImageFormatError(
            "That file is not an image Textra can read.",
            context={"allowed_formats": sorted(limits.allowed_formats)},
        ) from exc
    except Image.DecompressionBombError as exc:
        raise _fail_too_large(
            "The image declares more pixels than Textra will decode.",
            max_pixels=limits.max_pixels,
        ) from exc
    except OSError as exc:
        raise InvalidImageError(f"The image header could not be read: {exc}") from exc

    if image_format not in limits.allowed_formats:
        raise UnsupportedImageFormatError(
            f"{image_format or 'That'} images are not supported; "
            f"use {', '.join(sorted(limits.allowed_formats))}.",
            context={"format": image_format or None},
        )

    if width < limits.min_side or height < limits.min_side:
        raise InvalidImageError(
            f"The image is only {width}x{height}; each side must be at least {limits.min_side} px.",
            context={"width": width, "height": height},
        )
    if width > limits.max_side or height > limits.max_side:
        raise _fail_too_large(
            f"The image is {width}x{height}; no side may exceed {limits.max_side} px.",
            width=width,
            height=height,
        )
    pixels = width * height
    if pixels > limits.max_pixels:
        raise _fail_too_large(
            f"The image is {pixels:,} pixels; the limit is {limits.max_pixels:,}.",
            pixels=pixels,
        )

    try:
        # verify() consumes its handle, so decoding needs a fresh one. A corrupt
        # file must fail here, not inside the engine where it would surface as
        # an opaque "engine failed" dialog.
        with Image.open(io.BytesIO(data)) as verifier:
            verifier.verify()
        with Image.open(io.BytesIO(data)) as decoded:
            decoded.seek(0)  # multi-page TIFF: first page only
            image = ImageOps.exif_transpose(decoded)
            image.load()
    except Image.DecompressionBombError as exc:
        raise _fail_too_large(
            "The image declares more pixels than Textra will decode.",
            max_pixels=limits.max_pixels,
        ) from exc
    except (OSError, ValueError) as exc:
        raise InvalidImageError(f"The image could not be decoded: {exc}") from exc

    return DecodedImage(
        image=_flatten(image),
        format=image_format,
        width=image.width,
        height=image.height,
        original_width=width,
        original_height=height,
        byte_size=len(data),
        exif_rotated=exif_orientation != 1,
    )


def _flatten(image: Image.Image) -> Image.Image:
    """Return an RGB image with any transparency composited onto white."""
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, "white")
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        return canvas
    if image.mode != "RGB":
        return image.convert("RGB")
    return image


__all__ = ["DecodedImage", "decode_image"]
