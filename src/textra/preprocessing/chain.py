"""Compose preprocessing steps into one pass.

The chain owns ordering, which is not arbitrary: resize first (cheaper
rotations and contrast work, less memory), then normalise contrast, then deskew
last so the rotation operates on the final pixel grid. Each step decides for
itself whether it changes anything, and the chain records only real changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image

from ..domain.models import PreprocessOptions
from .steps import AutocontrastStep, DeskewStep, PreprocessStep, ResizeStep


@dataclass(slots=True)
class PreprocessingChain:
    """An ordered list of steps plus the outcome of the last run."""

    steps: tuple[PreprocessStep, ...]
    applied: list[str] = field(default_factory=list)
    skew_angle_degrees: float = 0.0
    resized: bool = False

    def run(self, image: Image.Image) -> Image.Image:
        """Apply every step in order and return the final image."""
        self.applied.clear()
        self.skew_angle_degrees = 0.0
        self.resized = False

        working = image
        for step in self.steps:
            result = step.apply(working)
            if result is working:
                continue
            if step.name == "deskew":
                self.skew_angle_degrees = getattr(step, "last_angle_degrees", 0.0)
                self.applied.append("deskew")
            elif step.name == "resize":
                self.resized = True
                self.applied.append("resize")
            else:
                self.applied.append(step.name)
            working = result
        return working


def build_chain(options: PreprocessOptions) -> PreprocessingChain:
    """Build a fresh chain for one run.

    Fresh steps per run keep the skew angle and reporting state out of shared
    objects, so two concurrent extractions cannot read each other's result.
    """
    steps: list[PreprocessStep] = []
    if options.max_dimension or options.min_dimension:
        steps.append(ResizeStep(options.max_dimension, options.min_dimension))
    if options.autocontrast:
        steps.append(AutocontrastStep())
    if options.deskew:
        steps.append(DeskewStep())
    return PreprocessingChain(steps=tuple(steps))


__all__ = ["PreprocessingChain", "build_chain"]
