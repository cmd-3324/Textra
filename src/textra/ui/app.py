"""Application bootstrap: settings, service, theme, window.

Composition happens here and nowhere else. The window receives a ready service,
so it can be constructed in a test with a fake engine and no configuration file.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .. import APP_NAME, __version__
from ..config import Settings
from ..engines.registry import build_default_registry
from ..logging import configure_logging, get_logger
from ..services.extraction_service import ExtractionService
from .main_window import MainWindow
from .theme import apply_theme

_logger = get_logger(__name__)


def create_application(argv: Sequence[str] | None = None) -> QApplication:
    """Return the process's QApplication, creating it once."""
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing

    # Fractional scaling on a 125 %/150 % Windows display must render text at
    # the real ratio; rounding to whole factors blurs small OCR text badly.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(list(argv) if argv is not None else [sys.argv[0]])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(_app_icon())
    return app


def _app_icon() -> QIcon:
    """Return the packaged window icon, or an empty icon if it is missing."""
    path = Path(__file__).resolve().parents[1] / "assets" / "textra.ico"
    return QIcon(str(path)) if path.is_file() else QIcon()


def run(initial_image: Path | None = None, argv: Sequence[str] | None = None) -> int:
    """Start the desktop application. Returns the Qt exit code."""
    try:
        settings = Settings()
    except ValidationError as exc:
        _print_configuration_error(exc)
        return 6

    configure_logging(settings)
    _logger.info("app.starting", extra={"version": __version__})

    app = create_application(argv)
    apply_theme(app, settings.ui_theme)

    service = ExtractionService(settings, registry=build_default_registry())
    window = MainWindow(settings, service)
    window.show()

    if initial_image is not None:
        QTimer.singleShot(0, lambda: window.load_path(initial_image))

    try:
        return app.exec()
    finally:
        service.close()
        _logger.info("app.stopped")


def _print_configuration_error(exc: ValidationError) -> None:
    lines = ["Textra could not start: the configuration is invalid."]
    for error in exc.errors():
        field = ".".join(str(part) for part in error["loc"])
        lines.append(f"  TEXTRA_{field.upper()}: {error['msg']}")
    message = "\n".join(lines)
    print(message, file=sys.stderr)

    if QApplication.instance() is not None:
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Configuration error")
        box.setText("Textra could not start.")
        box.setInformativeText(message)
        box.exec()


def main() -> int:
    """Console entry point for the ``textra-gui`` script."""
    return run()


__all__ = ["create_application", "main", "run"]
