"""Textra: image-to-text desktop application and embeddable core library.

The package is split along one boundary that matters: :mod:`textra.domain`,
:mod:`textra.engines`, :mod:`textra.preprocessing`, :mod:`textra.formatting`,
:mod:`textra.pipeline` and :mod:`textra.services` know nothing about Qt. The
desktop layer in :mod:`textra.ui` and the terminal layer in :mod:`textra.cli`
are interchangeable adapters over the same service.
"""

from __future__ import annotations

__version__ = "0.1.0"
APP_NAME = "Textra"

__all__ = ["APP_NAME", "__version__"]
