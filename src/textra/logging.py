"""Structured logging for both the GUI and the CLI.

The desktop app has no terminal, so a log file is the only way to diagnose a
report of "it failed on my scan". Every extraction therefore logs one start
record and one end record carrying the same ``job`` id, the engine, the image
size and per-stage milliseconds, and the file handler rotates so a long-lived
window cannot fill the disk.

The module is named ``logging`` after the standard library on purpose: absolute
imports mean ``import logging`` inside this file still resolves to the stdlib.
Anything importing Textra's helpers imports them from ``textra.logging``.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from .config import Settings

JOB_CONTEXT: ContextVar[str | None] = ContextVar("textra_job", default=None)
MAX_LOG_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 3

#: Attributes every LogRecord already has; anything else is a structured extra.
_RESERVED: frozenset[str] = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def current_job_id() -> str | None:
    return JOB_CONTEXT.get()


class JsonFormatter(logging.Formatter):
    """One JSON object per line, including the job id and structured extras."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        job = getattr(record, "job", None) or current_job_id()
        if job:
            payload["job"] = job
        for key, value in record.__dict__.items():
            if key in _RESERVED or key in payload or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """Readable one-line output for a terminal."""

    def __init__(self) -> None:
        super().__init__(fmt="%(asctime)s %(levelname)-7s %(name)s %(message)s", datefmt="%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        job = getattr(record, "job", None) or current_job_id()
        if job:
            line = f"{line} [job={job}]"
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED and key not in {"job"} and not key.startswith("_")
        }
        if extras:
            rendered = " ".join(f"{key}={value!r}" for key, value in sorted(extras.items()))
            line = f"{line} {rendered}"
        return line


def _build_formatter(settings: Settings) -> logging.Formatter:
    return JsonFormatter() if settings.log_format == "json" else ConsoleFormatter()


def configure_logging(settings: Settings, *, stream: Any | None = None) -> None:
    """Install one console handler and, if configured, one rotating file handler.

    Safe to call again: existing root handlers are replaced rather than stacked,
    which is what otherwise turns every line into two after a development reload.
    """
    level = getattr(logging, settings.log_level)
    formatter = _build_formatter(settings)

    console = logging.StreamHandler(stream if stream is not None else sys.stderr)
    console.setFormatter(formatter)

    handlers: list[logging.Handler] = [console]

    log_path: Path | None = settings.log_file_path()
    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=MAX_LOG_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            handlers.append(file_handler)
        except OSError:
            # A read-only install or an unwritable path must not stop OCR from
            # working; the console handler still tells the story.
            console.handle(
                logging.LogRecord(
                    "textra.logging",
                    logging.WARNING,
                    __file__,
                    0,
                    "Could not open log file %s; staying on console output.",
                    (str(log_path),),
                    None,
                )
            )

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)

    # Let Qt and the OCR libraries be quiet unless something is actually wrong.
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("rapidocr").setLevel(logging.WARNING)
    logging.getLogger("onnxruntime").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """A namespaced logger; callers pass ``__name__``."""
    return logging.getLogger(name)


__all__ = [
    "JOB_CONTEXT",
    "configure_logging",
    "current_job_id",
    "get_logger",
]
