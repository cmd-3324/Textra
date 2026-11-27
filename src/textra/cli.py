"""Command line interface: the same service the window uses.

``textra extract`` exists for scripting and for testing an engine without
opening a window; it must never grow its own OCR path. The CLI builds the
service from settings, hands it an :class:`ExtractionRequest`, writes the
rendered content, and maps domain errors to documented exit codes so a shell
script can branch on the failure kind.

Exit codes:
    0 success, 1 I/O or unexpected failure, 2 bad usage, 3 invalid image,
    4 engine unavailable or failed, 5 timeout, 6 configuration, 130 cancelled.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import ValidationError

from . import APP_NAME, __version__
from .config import Settings
from .domain.errors import (
    ConfigurationError,
    EngineExecutionError,
    EngineInitializationError,
    ExtractionCancelledError,
    ExtractionTimeoutError,
    ImageTooLargeError,
    InvalidImageError,
    TextraError,
)
from .domain.models import ExtractionRequest, OutputFormat
from .engines.registry import build_default_registry
from .logging import configure_logging
from .services.extraction_service import ExtractionService

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_INVALID_IMAGE = 3
EXIT_ENGINE = 4
EXIT_TIMEOUT = 5
EXIT_CONFIGURATION = 6
EXIT_CANCELLED = 130

ServiceFactory = Callable[[Settings], ExtractionService]

#: Errors that are the user's configuration, not a bug, map to their own code.
_ERROR_EXIT_CODES: tuple[tuple[type[BaseException], int], ...] = (
    (ExtractionCancelledError, EXIT_CANCELLED),
    (ImageTooLargeError, EXIT_INVALID_IMAGE),
    (InvalidImageError, EXIT_INVALID_IMAGE),
    (EngineInitializationError, EXIT_ENGINE),
    (EngineExecutionError, EXIT_ENGINE),
    (ExtractionTimeoutError, EXIT_TIMEOUT),
    (ConfigurationError, EXIT_CONFIGURATION),
    (TextraError, EXIT_ERROR),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="textra",
        description=f"{APP_NAME} {__version__} - image to text, on your machine.",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    extract = subparsers.add_parser("extract", help="read one image and print the text")
    extract.add_argument("image", type=Path, help="path to a PNG, JPEG, WEBP, BMP or TIFF image")
    extract.add_argument(
        "-f",
        "--format",
        choices=[fmt.value for fmt in OutputFormat],
        default=OutputFormat.PLAIN.value,
        help="output format (default: plain)",
    )
    extract.add_argument(
        "-e", "--engine", default=None, help="engine name (default: from settings)"
    )
    extract.add_argument(
        "--no-preprocess",
        action="store_true",
        help="skip resizing, contrast normalisation and deskew",
    )
    extract.add_argument(
        "-o", "--output", type=Path, default=None, help="write here instead of stdout"
    )
    extract.add_argument("-q", "--quiet", action="store_true", help="suppress progress and summary")

    subparsers.add_parser("engines", help="list OCR engines and whether they can run here")

    subparsers.add_parser("doctor", help="check configuration and engine availability")

    gui = subparsers.add_parser("gui", help="open the desktop window")
    gui.add_argument("image", nargs="?", type=Path, default=None, help="image to open on start")

    return parser


def main(
    argv: Sequence[str] | None = None, *, service_factory: ServiceFactory | None = None
) -> int:
    """Entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        return _launch_gui(None)

    try:
        settings = Settings()
    except ValidationError as exc:
        return _report_configuration_error(exc)

    configure_logging(settings)

    if args.command == "gui":
        return _launch_gui(args.image)

    factory = service_factory or _default_service_factory
    if args.command == "engines":
        return _cmd_engines(settings, factory)
    if args.command == "doctor":
        return _cmd_doctor(settings, factory)
    if args.command == "extract":
        return _cmd_extract(args, settings, factory)

    parser.print_help()
    return EXIT_USAGE


# -- commands --------------------------------------------------------------- #
def _cmd_extract(args: argparse.Namespace, settings: Settings, factory: ServiceFactory) -> int:
    path: Path = args.image
    try:
        data = path.read_bytes()
    except OSError as exc:
        print(f"textra: cannot read {path}: {exc.strerror or exc}", file=sys.stderr)
        return EXIT_ERROR

    output_format = OutputFormat(args.format)
    request = ExtractionRequest(
        data=data,
        source_name=path.name,
        output_format=output_format,
        engine=args.engine,
        preprocess=False if args.no_preprocess else None,
    )

    progress = None if args.quiet else _print_progress
    service = factory(settings)
    try:
        outcome = service.extract(request, progress=progress)
    except TextraError as exc:
        return _report_domain_error(exc)
    finally:
        service.close()

    if args.output is not None:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(outcome.content, encoding="utf-8")
        except OSError as exc:
            print(f"textra: cannot write {args.output}: {exc.strerror or exc}", file=sys.stderr)
            return EXIT_ERROR
        destination = str(args.output)
    else:
        sys.stdout.write(outcome.content)
        sys.stdout.flush()
        destination = "stdout"

    if not args.quiet:
        result = outcome.result
        print(
            f"\ntextra: {result.image.source_name} -> {destination} | "
            f"{result.line_count} lines | "
            f"{result.mean_confidence * 100:.1f}% confidence | "
            f"{result.timings.total_ms / 1000:.2f} s | {result.engine.name}",
            file=sys.stderr,
        )
    return EXIT_OK


def _cmd_engines(settings: Settings, factory: ServiceFactory) -> int:
    service = factory(settings)
    try:
        states = service.available_engines()
    finally:
        service.close()

    if not states:
        print("No OCR engines are registered.")
        return EXIT_ENGINE

    name_width = max(len(state.name) for state in states)
    for state in states:
        status = "ready" if state.available else "unavailable"
        print(f"{state.name:<{name_width}}  {status:<11}  {state.detail}")
        if state.requires and not state.available:
            print(f"{'':<{name_width}}  {'':<11}  install: {state.requires}")
    return EXIT_OK


def _cmd_doctor(settings: Settings, factory: ServiceFactory) -> int:
    print(f"{APP_NAME} {__version__}")
    print(f"  environment         {settings.environment}")
    print(f"  default engine      {settings.default_engine}")
    print(f"  language            {settings.ocr_language}")
    print(f"  timeout             {settings.extraction_timeout_seconds:.0f} s")
    print(
        f"  max image           {settings.max_image_bytes / 1_048_576:.0f} MB, "
        f"{settings.max_image_pixels:,} px"
    )
    print(
        f"  preprocessing       {'on' if settings.preprocess_enabled else 'off'}"
        f" (max {settings.preprocess_max_dimension or 'unlimited'} px)"
    )
    print(f"  log file            {settings.log_file_path() or 'none'}")

    service = factory(settings)
    try:
        states = service.available_engines()
    finally:
        service.close()

    print("\nengines:")
    for state in states:
        marker = "ok  " if state.available else "miss"
        print(f"  [{marker}] {state.name}: {state.detail}")
        if state.requires and not state.available:
            print(f"         install: {state.requires}")

    if not any(state.available for state in states):
        print("\nNo engine can run. Install one before extracting.")
        return EXIT_ENGINE

    print("\nAt least one engine is ready.")
    return EXIT_OK


def _launch_gui(image: Path | None) -> int:
    """Import Qt only when a window is actually requested."""
    try:
        from .ui.app import run
    except ImportError as exc:  # pragma: no cover - PySide6 is a core dependency
        print(
            "textra: the desktop UI needs PySide6. Install it with: pip install PySide6",
            file=sys.stderr,
        )
        print(f"        ({exc})", file=sys.stderr)
        return EXIT_ERROR

    return run(initial_image=image)


# -- helpers ---------------------------------------------------------------- #
def _default_service_factory(settings: Settings) -> ExtractionService:
    return ExtractionService(settings, registry=build_default_registry())


def _print_progress(stage: str, percent: int) -> None:
    print(f"\r[{percent:3d}%] {stage:<20}", end="", file=sys.stderr, flush=True)
    if percent >= 100:
        print(file=sys.stderr)


def _report_domain_error(exc: TextraError) -> int:
    print(f"textra: {exc.message}", file=sys.stderr)
    if exc.context:
        print(
            f"        {json.dumps(exc.context, ensure_ascii=False, default=str)}", file=sys.stderr
        )
    for error_type, code in _ERROR_EXIT_CODES:
        if isinstance(exc, error_type):
            return code
    return EXIT_ERROR


def _report_configuration_error(exc: ValidationError) -> int:
    print("textra: invalid configuration.", file=sys.stderr)
    for error in exc.errors():
        field = ".".join(str(part) for part in error["loc"])
        print(f"  TEXTRA_{field.upper()}: {error['msg']}", file=sys.stderr)
    return EXIT_CONFIGURATION


__all__ = ["EXIT_OK", "build_parser", "main"]
