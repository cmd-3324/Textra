"""The only bridge between Qt and the service.

A ``QThread`` whose ``run`` calls the service is the whole concurrency model:
the UI thread never blocks, and all communication back is through signals, which
Qt queues onto the GUI thread automatically. No widget reaches into the service
from a worker, and no service object knows Qt exists.

Signals are named ``stageChanged``/``succeeded`` rather than ``started``/
``finished`` because ``QThread`` already defines those, and shadowing a signal
that Qt emits itself is a subtle way to drop events.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, QThread, Signal

from ..domain.errors import ExtractionCancelledError, TextraError
from ..domain.models import ExtractionOutcome, ExtractionRequest
from ..services.cancellation import CancellationToken
from ..services.extraction_service import ExtractionService


class ExtractionWorker(QThread):
    """Runs one extraction off the GUI thread."""

    stageChanged = Signal(str, int)
    succeeded = Signal(object)  # ExtractionOutcome
    failed = Signal(str, str)  # user-facing message, diagnostic detail
    cancelled = Signal()

    def __init__(
        self,
        service: ExtractionService,
        request: ExtractionRequest,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._request = request
        self._token = CancellationToken()

    def cancel(self) -> None:
        """Ask the service to stop at its next checkpoint."""
        self._token.cancel()

    def run(self) -> None:
        try:
            outcome: ExtractionOutcome = self._service.extract(
                self._request,
                token=self._token,
                progress=self.stageChanged.emit,
            )
        except ExtractionCancelledError:
            self.cancelled.emit()
        except TextraError as exc:
            self.failed.emit(exc.message, _detail(exc))
        except Exception as exc:
            self.failed.emit(
                "Extraction failed unexpectedly. See the log for details.",
                repr(exc),
            )
        else:
            self.succeeded.emit(outcome)


def _detail(exc: TextraError) -> str:
    if not exc.context:
        return f"{exc.code}"
    rendered = json.dumps(exc.context, indent=2, ensure_ascii=False, default=str)
    return f"{exc.code}\n{rendered}"


__all__ = ["ExtractionWorker"]
