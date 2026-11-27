"""Engine registry: the one place that knows which backends exist.

Adding a backend means implementing :class:`~textra.domain.ports.OCREngine` and
:class:`~textra.domain.ports.EngineProvider` on one class, then either listing
it here or publishing an entry point in the ``textra.engines`` group. Neither
the service, the pipeline nor the UI changes.

Entry-point plugins are loaded lazily and defensively: a broken third-party
package must not stop Textra from starting with its built-in engines.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from importlib import metadata
from typing import cast

from ..domain.errors import EngineInitializationError
from ..domain.models import EngineAvailability, EngineSettings
from ..domain.ports import EngineProvider, OCREngine
from .rapidocr_engine import RapidOcrEngine
from .tesseract_engine import TesseractEngine

ENTRY_POINT_GROUP = "textra.engines"

_logger = logging.getLogger(__name__)


class EngineRegistry:
    """A name-to-provider mapping with deterministic ordering."""

    def __init__(self, providers: Iterable[type[EngineProvider]] = ()) -> None:
        self._providers: dict[str, type[EngineProvider]] = {}
        self._order: list[str] = []
        for provider in providers:
            self.register(provider)

    # -- mutation ---------------------------------------------------------- #
    def register(self, provider: type[EngineProvider], *, replace: bool = False) -> None:
        """Add a provider under its own ``name``.

        Raises:
            EngineInitializationError: the name is taken and ``replace`` is
                false, which catches two plugins silently claiming one name.
        """
        name = getattr(provider, "name", "")
        if not name or not isinstance(name, str):
            raise EngineInitializationError("An OCR engine provider must define a string 'name'.")
        if name in self._providers and not replace:
            raise EngineInitializationError(
                f"An OCR engine named '{name}' is already registered.",
                context={"engine": name},
            )
        if name not in self._providers:
            self._order.append(name)
        self._providers[name] = provider

    # -- queries ----------------------------------------------------------- #
    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._order)

    def has(self, name: str) -> bool:
        return name in self._providers

    def provider(self, name: str) -> type[EngineProvider]:
        try:
            return self._providers[name]
        except KeyError:
            raise EngineInitializationError(
                f"Unknown OCR engine '{name}'. Available: {', '.join(self._order) or 'none'}.",
                context={"engine": name, "available": list(self._order)},
            ) from None

    def availability(self, settings: EngineSettings) -> tuple[EngineAvailability, ...]:
        """Probe every provider without constructing any of them."""
        results: list[EngineAvailability] = []
        for name in self._order:
            provider = self._providers[name]
            try:
                results.append(provider.availability(settings))
            except Exception as exc:
                _logger.warning("engine.availability_failed engine=%s error=%r", name, exc)
                results.append(
                    EngineAvailability(
                        name=name,
                        available=False,
                        detail=f"availability check failed: {exc}",
                    )
                )
        return tuple(results)

    def default_name(self, settings: EngineSettings) -> str:
        """Resolve ``auto`` to the first engine that can actually run."""
        if not self._order:
            raise EngineInitializationError("No OCR engines are registered.")

        states = self.availability(settings)
        usable = [state.name for state in states if state.available]
        if not usable:
            details = "; ".join(f"{state.name}: {state.detail}" for state in states)
            raise EngineInitializationError(
                "No OCR engine is available on this machine. " + details,
                context={"engines": [state.name for state in states]},
            )
        return usable[0]

    def create(self, name: str, settings: EngineSettings) -> OCREngine:
        provider = self.provider(name)
        state = provider.availability(settings)
        if not state.available:
            raise EngineInitializationError(
                f"The '{name}' engine cannot run here: {state.detail}"
                + (f" {state.requires}" if state.requires else ""),
                context={"engine": name},
            )
        return provider.create(settings)

    # -- construction ------------------------------------------------------ #
    @classmethod
    def with_builtins(cls, *, load_plugins: bool = True) -> EngineRegistry:
        # Concrete providers satisfy the protocol structurally, but a Protocol
        # with classmethod members is not assignable from ``type[Concrete]`` for
        # a static checker. Registration is duck-typed at runtime; the cast keeps
        # the public registry API strong without demanding nominal subclasses.
        providers = (
            cast(type[EngineProvider], RapidOcrEngine),
            cast(type[EngineProvider], TesseractEngine),
        )
        registry = cls(providers)
        if load_plugins:
            registry.load_entry_points()
        return registry

    def load_entry_points(self) -> None:
        """Register plugins published under ``textra.engines``.

        A plugin that fails to import is logged and skipped: an optional
        third-party backend must never make the application unusable.
        """
        for entry_point in metadata.entry_points(group=ENTRY_POINT_GROUP):
            if self.has(entry_point.name):
                _logger.warning("engine.plugin_skipped name=%s reason=duplicate", entry_point.name)
                continue
            try:
                provider = entry_point.load()
            except Exception as exc:
                _logger.warning("engine.plugin_failed name=%s error=%r", entry_point.name, exc)
                continue
            self.register(provider)


def build_default_registry(*, load_plugins: bool = True) -> EngineRegistry:
    """The registry an installed Textra uses."""
    return EngineRegistry.with_builtins(load_plugins=load_plugins)


__all__ = [
    "ENTRY_POINT_GROUP",
    "EngineRegistry",
    "build_default_registry",
]
