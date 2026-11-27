"""Preprocessing steps, each small enough to reason about alone.

A step returns the image unchanged (the same object) when it decides there is
nothing to do; :class:`~textra.preprocessing.chain.PreprocessingChain` uses
identity to record only the steps that actually changed pixels. That keeps the
report truthful - "deskew" appears in ``applied`` only when a rotation
happened, not merely because the toggle was on.

Every step is a pure function of its input image, so the suite can test each one
without a service, a thread or an engine.
"""

from __future__ import annotations

import math
from typing import Protocol

import numpy as np
from PIL import Image, ImageOps

#: Below this the correction is smaller than the interpolation error it adds.
MIN_DESKEW_DEGREES = 0.3
#: Longest side the skew search analyses; a full-resolution sweep costs more
#: than the OCR call it is meant to improve.
SKEW_ANALYSIS_SIDE = 900
#: Ink/paper cut-off on the 0-255 luminance scale.
INK_THRESHOLD = 160


class PreprocessStep(Protocol):
    """One optional transformation."""

    name: str

    def apply(self, image: Image.Image) -> Image.Image:
        """Return the transformed image, or the same object for a no-op."""


class ResizeStep:
    """Downscale oversized scans and (optionally) upscale thumbnails."""

    name = "resize"

    def __init__(self, max_dimension: int, min_dimension: int) -> None:
        self._max = max_dimension
        self._min = min_dimension

    def apply(self, image: Image.Image) -> Image.Image:
        width, height = image.size
        longest = max(width, height)
        shortest = min(width, height)

        if self._max and longest > self._max:
            scale = self._max / longest
        elif self._min and shortest < self._min:
            scale = self._min / shortest
        else:
            return image

        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        return image.resize(size, Image.Resampling.LANCZOS)


class AutocontrastStep:
    """Normalise a faded scan without clipping thin strokes.

    A 1 % cutoff ignores the extreme 1 % of pixels, which is where sensor noise
    and page shadows live; a wider cutoff starts eroding light grey text.
    """

    name = "autocontrast"

    def __init__(self, cutoff: float = 1.0) -> None:
        self._cutoff = cutoff

    def apply(self, image: Image.Image) -> Image.Image:
        return ImageOps.autocontrast(image, cutoff=self._cutoff)


class DeskewStep:
    """Rotate a tilted page upright using a projection-profile search.

    Text rows produce sharp peaks in the horizontal ink profile when level, so
    the angle with the highest profile variance is the upright one. The search
    runs on a thumbnail and in two passes (coarse, then fine) because a full
    sweep at 0.1 degree resolution would dominate request latency.

    The angle is in Pillow's convention: positive rotates counter-clockwise,
    and the value returned is exactly the rotation that levels the page.
    """

    name = "deskew"

    def __init__(
        self,
        max_degrees: float = 6.0,
        fine_step_degrees: float = 0.5,
    ) -> None:
        self._max = max_degrees
        self._fine_step = fine_step_degrees
        self.last_angle_degrees = 0.0

    def apply(self, image: Image.Image) -> Image.Image:
        self.last_angle_degrees = self._estimate(image)
        if abs(self.last_angle_degrees) < MIN_DESKEW_DEGREES:
            return image
        return image.rotate(
            self.last_angle_degrees,
            resample=Image.Resampling.BICUBIC,
            expand=True,
            fillcolor="white",
        )

    def _estimate(self, image: Image.Image) -> float:
        if self._max <= 0 or self._fine_step <= 0:
            return 0.0

        grey = image.convert("L")
        grey.thumbnail((SKEW_ANALYSIS_SIDE, SKEW_ANALYSIS_SIDE), Image.Resampling.BILINEAR)
        ink = (np.asarray(grey, dtype=np.uint8) < INK_THRESHOLD).astype(np.float32)
        if ink.mean() < 0.002:  # a nearly blank page has no rows to align
            return 0.0

        coarse_step = max(self._fine_step * 2.0, 1.0)
        coarse = _best_angle(ink, self._max, coarse_step)
        window = min(self._max, coarse_step * 2.0)
        return round(_best_angle(ink, window, self._fine_step, center=coarse), 2)


def _best_angle(
    ink: np.ndarray,
    half_range: float,
    step: float,
    *,
    center: float = 0.0,
) -> float:
    """Return the angle near ``center`` whose row profile is sharpest."""
    canvas = Image.fromarray((ink * 255.0).astype(np.uint8), mode="L")
    steps = round(half_range / step)
    best_angle = center
    best_score = -math.inf
    for index in range(-steps, steps + 1):
        angle = center + index * step
        rotated = canvas.rotate(angle, resample=Image.Resampling.NEAREST, fillcolor=0)
        row_sums = np.asarray(rotated, dtype=np.float32).sum(axis=1)
        # Normalising by mean ink stops a rotation that merely keeps more
        # pixels in frame from winning.
        score = float(row_sums.var() / (row_sums.mean() + 1e-6))
        if score > best_score:
            best_score = score
            best_angle = angle
    return float(best_angle)


__all__ = [
    "INK_THRESHOLD",
    "MIN_DESKEW_DEGREES",
    "AutocontrastStep",
    "DeskewStep",
    "PreprocessStep",
    "ResizeStep",
]
