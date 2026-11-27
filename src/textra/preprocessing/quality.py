"""Quality heuristics that explain an empty result.

"No text found" is a legitimate outcome for a photo of a wall, but it is also
what a mis-aimed scan looks like. Reporting the difference is the difference
between a user retrying with a better photo and a user filing a bug.

These are warnings, never rejections: an image with a little ink still goes to
the engine, because a small signature in a large page is real text.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from .steps import INK_THRESHOLD

#: Below this fraction of dark pixels an image is reported as effectively blank.
BLANK_INK_RATIO = 0.0015
_ANALYSIS_SIDE = 400


def ink_ratio(image: Image.Image) -> float:
    """Fraction of pixels darker than the ink threshold, sampled at 400 px."""
    grey = image.convert("L")
    grey.thumbnail((_ANALYSIS_SIDE, _ANALYSIS_SIDE), Image.Resampling.BILINEAR)
    return float((np.asarray(grey, dtype=np.uint8) < INK_THRESHOLD).mean())


def looks_blank(image: Image.Image) -> bool:
    """True when there is too little ink for an engine to have found anything."""
    return ink_ratio(image) < BLANK_INK_RATIO


__all__ = ["BLANK_INK_RATIO", "ink_ratio", "looks_blank"]
