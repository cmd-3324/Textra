"""The application service: one method that turns bytes into a document.

Everything the UI and the CLI need lives behind :meth:`ExtractionService.extract`.
It owns the sequence, the deadlines, the timing telemetry and the engine cache;
it owns no pixels, no Qt and no engine internals.

Two resource decisions are worth knowing:

* **Engines are created once and reused.** Loading an ONNX model costs seconds;
  doing it per image would make the second scan feel broken.
* **One worker thread.** A local OCR engine saturates the CPU it is given, so
  serialising extraction is faster overall than thrashing, and it is what makes
  a timed-out call safe: the next one queues instead of racing a half-dead
  session. Python cannot kill a running native call, so a timed-out attempt may
  still finish in the background; its result is discarded.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any

from ..config import Settings
from ..domain.errors import (
    EngineExecutionError,
    ExtractionCancelledError,
    ExtractionError,
    ExtractionTimeoutError,
    TextraError,
)
from ..domain.models import (
    EngineAvailability,
    EngineInfo,
    ExtractionOutcome,
    ExtractionRequest,
    ExtractionResult,
    ImageInfo,
    OutputFormat,
    RawLine,
    Timings,
)
from ..domain.ports import ImagePreprocessor, OCREngine, ProgressCallback, ResultFormatter
from ..engines.registry import EngineRegistry, build_default_registry
from ..formatting import DEFAULT_FORMATTERS
from ..logging import get_logger
from ..pipeline.layout import build_blocks
from ..preprocessing.pillow_preprocessor import PillowPreprocessor
from .cancellation import CancellationToken

#: Cancellation and deadline checks while waiting on the engine, in seconds.
_POLL_INTERVAL = 0.2
WARNING_NO_TEXT = "No text was detected in this image."


def _noop_progress(_stage: str, _percent: int) -> None:
    """Default progress sink for callers that do not care."""


class ExtractionService:
    """Orchestrates validation, preprocessing, OCR, layout and formatting."""

    def __init__(
        self,
        settings: Settings,
        *,
        registry: EngineRegistry | None = None,
        preprocessor: ImagePreprocessor | None = None,
        formatters: Mapping[OutputFormat, ResultFormatter] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._settings = settings
        self._registry = registry or build_default_registry()
        self._preprocessor = preprocessor or PillowPreprocessor(
            settings.image_limits(), settings.preprocess_options()
        )
        self._formatters: Mapping[OutputFormat, ResultFormatter] = formatters or DEFAULT_FORMATTERS
        self._logger = logger or get_logger(__name__)

        self._engines: dict[str, OCREngine] = {}
        self._engine_lock = threading.Lock()
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="textra-ocr")

    # -- queries ---------------------------------------------------------- #
    def available_engines(self) -> tuple[EngineAvailability, ...]:
        """Probe the registry; safe to call before any engine is constructed."""
        return self._registry.availability(self._settings.engine_settings())

    def default_engine_name(self) -> str:
        """The engine this service will use when a request does not name one."""
        requested = self._settings.default_engine
        if requested != "auto":
            return requested
        return self._registry.default_name(self._settings.engine_settings())

    def render(self, result: ExtractionResult, output_format: OutputFormat) -> str:
        """Re-render an existing result, so switching format needs no new OCR."""
        return self._formatter(output_format).render(result)

    # -- extraction -------------------------------------------------------- #
    def extract(
        self,
        request: ExtractionRequest,
        *,
        token: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> ExtractionOutcome:
        """Run the full pipeline for one image.

        Raises:
            TextraError: one of the domain errors, always with a displayable
                message. Unexpected exceptions are wrapped in
                :class:`~textra.domain.errors.ExtractionError`.
        """
        if self._closed:
            raise ExtractionError("The extraction service has been closed.")

        cancellation = token or CancellationToken()
        notify = progress or _noop_progress
        started = time.monotonic()
        deadline = started + self._settings.extraction_timeout_seconds
        engine_name = request.engine or self.default_engine_name()

        self._logger.info(
            "extraction.started",
            extra={
                "engine": engine_name,
                "output_format": request.output_format.value,
                "source": request.source_name,
                "bytes": len(request.data),
            },
        )

        try:
            notify("Preparing image", 10)
            cancellation.raise_if_cancelled()
            prepare_started = time.monotonic()
            document = self._preprocessor.prepare(
                request.data,
                source_name=request.source_name,
                preprocess=(
                    request.preprocess
                    if request.preprocess is not None
                    else self._settings.preprocess_enabled
                ),
            )
            preprocessing_ms = _elapsed_ms(prepare_started)
            self._check_deadline(deadline)
            cancellation.raise_if_cancelled()

            notify("Reading text", 40)
            engine = self._engine(engine_name)
            recognition_started = time.monotonic()
            raw_lines = self._recognise(engine, document.png_bytes, deadline, cancellation)
            recognition_ms = _elapsed_ms(recognition_started)

            notify("Building document", 85)
            cancellation.raise_if_cancelled()
            layout_started = time.monotonic()
            blocks = build_blocks(
                raw_lines,
                min_confidence=(
                    request.min_confidence
                    if request.min_confidence is not None
                    else self._settings.min_confidence
                ),
            )
            layout_ms = _elapsed_ms(layout_started)

            result = ExtractionResult(
                text="\n\n".join(block.text for block in blocks),
                blocks=blocks,
                image=ImageInfo(
                    source_name=document.source_name,
                    format=document.format,
                    width=document.width,
                    height=document.height,
                    original_width=document.original_width,
                    original_height=document.original_height,
                    byte_size=document.byte_size,
                ),
                preprocessing=document.preprocessing,
                engine=EngineInfo(
                    name=engine.name,
                    version=engine.version,
                    language=self._settings.ocr_language,
                ),
                timings=Timings(
                    preprocessing_ms=preprocessing_ms,
                    recognition_ms=recognition_ms,
                    layout_ms=layout_ms,
                    formatting_ms=0.0,
                    total_ms=0.0,
                ),
                warnings=document.warnings + ((WARNING_NO_TEXT,) if not blocks else ()),
            )

            notify("Formatting output", 95)
            formatter = self._formatter(request.output_format)
            formatting_started = time.monotonic()
            formatter.render(result)  # warm-up render, timed
            formatting_ms = _elapsed_ms(formatting_started)

            total_ms = _elapsed_ms(started)
            result = _with_timings(result, formatting_ms, total_ms)
            # Render again so the JSON export reports the final timings. The
            # first pass is measured (timing a render cannot include its own
            # result); the second is cheap and keeps the document self-consistent.
            content = formatter.render(result)
            cancellation.raise_if_cancelled()

            self._logger.info(
                "extraction.completed",
                extra={
                    "engine": engine.name,
                    "output_format": request.output_format.value,
                    "blocks": len(result.blocks),
                    "lines": result.line_count,
                    "characters": len(content),
                    "duration_ms": round(total_ms, 1),
                    "confidence": round(result.mean_confidence, 3),
                },
            )
            notify("Done", 100)
            return ExtractionOutcome(
                result=result,
                content=content,
                output_format=request.output_format,
            )
        except ExtractionCancelledError:
            self._logger.info("extraction.cancelled", extra={"source": request.source_name})
            raise
        except TextraError as exc:
            self._logger.warning(
                "extraction.failed",
                extra={"code": exc.code, "reason": exc.message, "context": exc.context},
            )
            raise
        except Exception as exc:
            self._logger.exception("extraction.crashed")
            raise ExtractionError(
                "Extraction failed unexpectedly. See the log for details.",
                context={"error": repr(exc)},
            ) from exc

    # -- engine lifecycle -------------------------------------------------- #
    def _engine(self, name: str) -> OCREngine:
        with self._engine_lock:
            engine = self._engines.get(name)
            if engine is not None:
                return engine
            self._logger.info("engine.initializing", extra={"engine": name})
            created = self._registry.create(name, self._settings.engine_settings())
            created.initialize()
            self._engines[name] = created
            self._logger.info(
                "engine.ready",
                extra={"engine": created.name, "version": created.version},
            )
            return created

    def _recognise(
        self,
        engine: OCREngine,
        png_bytes: bytes,
        deadline: float,
        token: CancellationToken,
    ) -> tuple[RawLine, ...]:
        """Run inference with a deadline, polling so Cancel is responsive."""
        future = self._executor.submit(engine.recognize, png_bytes)
        while True:
            if token.is_cancelled:
                future.cancel()
                raise ExtractionCancelledError("The extraction was cancelled.")

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                future.cancel()
                raise ExtractionTimeoutError(
                    f"OCR did not finish within {self._settings.extraction_timeout_seconds:.0f} s.",
                    context={"engine": engine.name},
                )

            try:
                return future.result(timeout=min(_POLL_INTERVAL, remaining))
            except FutureTimeoutError:
                continue
            except TextraError:
                raise
            except Exception as exc:
                raise EngineExecutionError(
                    "The OCR engine failed while reading this image.",
                    context={"engine": engine.name, "error": repr(exc)},
                ) from exc

    def _formatter(self, output_format: OutputFormat) -> ResultFormatter:
        try:
            return self._formatters[output_format]
        except KeyError:
            raise ExtractionError(f"No formatter is registered for '{output_format}'.") from None

    @staticmethod
    def _check_deadline(deadline: float) -> None:
        if time.monotonic() > deadline:
            raise ExtractionTimeoutError("Extraction exceeded its time budget.")

    # -- teardown ---------------------------------------------------------- #
    def close(self) -> None:
        """Release engines and the worker thread. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        with self._engine_lock:
            for engine in self._engines.values():
                try:
                    engine.close()
                except Exception:
                    self._logger.warning("engine.close_failed", exc_info=True)
            self._engines.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def __enter__(self) -> ExtractionService:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()


def _elapsed_ms(started: float) -> float:
    return (time.monotonic() - started) * 1000.0


def _with_timings(
    result: ExtractionResult, formatting_ms: float, total_ms: float
) -> ExtractionResult:
    timings = Timings(
        preprocessing_ms=result.timings.preprocessing_ms,
        recognition_ms=result.timings.recognition_ms,
        layout_ms=result.timings.layout_ms,
        formatting_ms=formatting_ms,
        total_ms=total_ms,
    )
    return ExtractionResult(
        text=result.text,
        blocks=result.blocks,
        image=result.image,
        preprocessing=result.preprocessing,
        engine=result.engine,
        timings=timings,
        warnings=result.warnings,
    )


__all__ = ["WARNING_NO_TEXT", "ExtractionService"]
