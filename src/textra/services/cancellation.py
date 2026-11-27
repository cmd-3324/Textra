"""A cooperative cancellation token.

Qt's "Cancel" button must not terminate a thread - killing a thread mid-inference
corrupts native state. Instead the caller flips a flag and the service checks it
at stage boundaries and while it waits for the engine. Work already inside the
engine finishes and its result is discarded, which is the only safe contract
Python can offer for a blocking C call.
"""

from __future__ import annotations

import threading

from ..domain.errors import ExtractionCancelledError


class CancellationToken:
    """Thread-safe one-way flag."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Request cancellation. Idempotent."""
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        """Stop the pipeline if cancellation has been requested."""
        if self._event.is_set():
            raise ExtractionCancelledError("The extraction was cancelled.")


__all__ = ["CancellationToken"]
