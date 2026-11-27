"""The main window: presentation and event wiring only.

Anything that could fail on real input - decoding, preprocessing, OCR, layout -
lives behind :class:`~textra.services.extraction_service.ExtractionService`.
This file reads bytes, hands them over, and renders the answer. The one piece of
logic it keeps is turning a failed run into text a person can act on.

Extraction runs in :class:`~textra.ui.workers.ExtractionWorker`, so a slow scan
never blocks the event loop; Cancel flips the worker's token rather than killing
a thread.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import (
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QGuiApplication,
    QImage,
    QKeySequence,
    QShortcut,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..config import Settings
from ..domain.models import (
    EngineAvailability,
    ExtractionOutcome,
    ExtractionRequest,
    OutputFormat,
)
from ..services.extraction_service import ExtractionService
from .image_view import SUPPORTED_SUFFIXES, ImagePreview
from .result_panel import ResultPanel
from .workers import ExtractionWorker

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;All files (*)"
WINDOW_TITLE = f"{APP_NAME} — Image to Text"


class MainWindow(QMainWindow):
    """One window: pick an image, watch the progress, read and export the text."""

    def __init__(
        self,
        settings: Settings,
        service: ExtractionService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._service = service
        self._worker: ExtractionWorker | None = None
        self._outcome: ExtractionOutcome | None = None
        self._source_bytes: bytes | None = None
        self._source_name: str = "clipboard.png"

        self.setWindowTitle(f"{WINDOW_TITLE} {__version__}")
        self.resize(settings.ui_window_width, settings.ui_window_height)
        self.setAcceptDrops(True)

        self._build_ui()
        self._connect_signals()
        self._populate_engines()
        self._update_actions()

    # -- construction ------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("Root")
        self.setCentralWidget(root)

        title = QLabel(APP_NAME, root)
        title.setObjectName("AppTitle")
        tagline = QLabel(
            "Local OCR with structure — drop an image, paste a screenshot, or open a file.",
            root,
        )
        tagline.setObjectName("Tagline")

        header = QVBoxLayout()
        header.setSpacing(2)
        header.addWidget(title)
        header.addWidget(tagline)

        toolbar = self._build_toolbar(root)

        self.preview = ImagePreview(root)
        self.result = ResultPanel(root)

        splitter = QSplitter(Qt.Orientation.Horizontal, root)
        splitter.addWidget(self.preview)
        splitter.addWidget(self.result)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([480, 620])

        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 16, 18, 10)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addWidget(toolbar)
        layout.addWidget(splitter, 1)

        self._status = QLabel("Ready", self)
        self._metrics = QLabel("", self)
        self._metrics.setObjectName("Meta")
        self._progress = QProgressBar(self)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedWidth(150)
        self._progress.hide()

        status_bar = self.statusBar()
        status_bar.addWidget(self._status, 1)
        status_bar.addPermanentWidget(self._progress)
        status_bar.addPermanentWidget(self._metrics)

    def _build_toolbar(self, parent: QWidget) -> QFrame:
        self.open_button = QPushButton("Open image…", parent)
        self.paste_button = QPushButton("Paste", parent)
        self.engine_label = QLabel("Engine", parent)
        self.engine_label.setObjectName("Meta")
        self.engine_combo = QComboBox(parent)
        self.format_label = QLabel("Format", parent)
        self.format_label.setObjectName("Meta")
        self.format_combo = QComboBox(parent)
        for output_format in OutputFormat:
            self.format_combo.addItem(output_format.label, output_format.value)
        self.preprocess_check = QCheckBox("Preprocess", parent)
        self.preprocess_check.setChecked(self._settings.preprocess_enabled)
        self.preprocess_check.setToolTip(
            "Resize, normalise contrast and straighten the page before reading it"
        )

        self.extract_button = QPushButton("Extract text", parent)
        self.extract_button.setObjectName("Primary")
        self.extract_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel", parent)
        self.cancel_button.setEnabled(False)
        self.cancel_button.hide()

        bar = QFrame(parent)
        bar.setObjectName("Card")
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(8)
        row.addWidget(self.open_button)
        row.addWidget(self.paste_button)
        row.addSpacing(10)
        row.addWidget(self.engine_label)
        row.addWidget(self.engine_combo)
        row.addSpacing(6)
        row.addWidget(self.format_label)
        row.addWidget(self.format_combo)
        row.addSpacing(6)
        row.addWidget(self.preprocess_check)
        row.addStretch(1)
        row.addWidget(self.cancel_button)
        row.addWidget(self.extract_button)
        return bar

    def _connect_signals(self) -> None:
        self.open_button.clicked.connect(self._choose_file)
        self.paste_button.clicked.connect(self._paste_from_clipboard)
        self.extract_button.clicked.connect(self.start_extraction)
        self.cancel_button.clicked.connect(self._cancel_extraction)
        self.preview.fileDropped.connect(self.load_path)
        self.result.copy_button.clicked.connect(self._copy_result)
        self.result.save_button.clicked.connect(self._save_result)
        self.format_combo.currentIndexChanged.connect(self._rerender_for_format)

        QShortcut(QKeySequence.StandardKey.Open, self, self._choose_file)
        QShortcut(QKeySequence.StandardKey.Paste, self, self._paste_from_clipboard)
        QShortcut(QKeySequence.StandardKey.Save, self, self._save_result)
        QShortcut(QKeySequence("Ctrl+Return"), self, self.start_extraction)
        QShortcut(QKeySequence("Ctrl+Enter"), self, self.start_extraction)
        QShortcut(QKeySequence("Escape"), self, self._cancel_extraction)

    def _populate_engines(self) -> None:
        self.engine_combo.clear()
        self.engine_combo.addItem("Auto (detect)", None)
        states = self.service_availability()
        for state in states:
            label = state.name if state.available else f"{state.name} (unavailable)"
            self.engine_combo.addItem(label, state.name)
            index = self.engine_combo.count() - 1
            tooltip = state.detail if state.available else f"{state.detail}\n{state.requires or ''}"
            self.engine_combo.setItemData(index, tooltip, Qt.ItemDataRole.ToolTipRole)
            if not state.available:
                model = self.engine_combo.model()
                if isinstance(model, QStandardItemModel):
                    item = model.item(index)
                    if item is not None:
                        item.setEnabled(False)

        preferred = self._settings.default_engine
        if preferred != "auto":
            position = self.engine_combo.findData(preferred)
            if position >= 0:
                self.engine_combo.setCurrentIndex(position)

    def service_availability(self) -> tuple[EngineAvailability, ...]:
        """Probe engines; a broken engine list must not stop the window opening."""
        try:
            return self._service.available_engines()
        except Exception:
            return ()

    # -- intake ------------------------------------------------------------ #
    def _choose_file(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self, "Open an image", str(Path.home()), IMAGE_FILTER
        )
        if path:
            self.load_path(path)

    def load_path(self, path: str | Path) -> None:
        """Load an image file into the preview and make it ready to extract."""
        source = Path(path)
        try:
            data = source.read_bytes()
        except OSError as exc:
            self._warn("Cannot read that file", f"{source}\n\n{exc.strerror or exc}")
            return

        image = QImage.fromData(data)
        if image.isNull():
            self._warn(
                "Not an image",
                f"{source.name} could not be decoded. Supported formats: "
                "PNG, JPEG, WEBP, BMP and TIFF.",
            )
            return

        self._source_bytes = data
        self._source_name = source.name
        self.preview.show_image(image, source.name)
        self._reset_result()
        self._status.setText(f"Loaded {source.name} — press Extract text")
        self._update_actions()

    def _paste_from_clipboard(self) -> None:
        clipboard = QGuiApplication.clipboard()
        image = clipboard.image()

        if image.isNull():
            mime = clipboard.mimeData()
            if mime is not None and mime.hasUrls():
                for url in mime.urls():
                    path = Path(url.toLocalFile()) if url.isLocalFile() else None
                    if path and path.suffix.lower() in SUPPORTED_SUFFIXES and path.is_file():
                        self.load_path(path)
                        return
            self._status.setText("The clipboard does not contain an image.")
            return

        self._source_bytes = self._encode_png(image)
        self._source_name = "clipboard.png"
        self.preview.show_image(image, "Pasted image")
        self._reset_result()
        self._status.setText("Pasted image from the clipboard — press Extract text")
        self._update_actions()

    @staticmethod
    def _encode_png(image: QImage) -> bytes:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, b"PNG")
        # QByteArray -> buffer protocol -> bytes; the second .data() is what
        # PySide6 exposes for the raw payload.
        return bytes(buffer.data().data())

    # -- extraction -------------------------------------------------------- #
    def start_extraction(self) -> None:
        if self._worker is not None:
            return
        if self._source_bytes is None:
            self._status.setText("Open or paste an image first.")
            return

        request = ExtractionRequest(
            data=self._source_bytes,
            source_name=self._source_name,
            output_format=self._selected_format(),
            engine=self.engine_combo.currentData(),
            preprocess=self.preprocess_check.isChecked(),
        )

        worker = ExtractionWorker(self._service, request, self)
        worker.stageChanged.connect(self._on_stage_changed)
        worker.succeeded.connect(self._on_succeeded)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker

        self._set_busy(True)
        self._progress.setValue(0)
        self._status.setText("Starting…")
        self._metrics.setText("")
        worker.start()

    def _cancel_extraction(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._status.setText("Cancelling…")

    def _on_stage_changed(self, stage: str, percent: int) -> None:
        self._status.setText(f"{stage}…")
        self._progress.setValue(percent)

    def _on_succeeded(self, outcome: ExtractionOutcome) -> None:
        self._outcome = outcome
        self.result.set_content(outcome.content)
        self.result.set_actions_enabled(True)

        result = outcome.result
        self.result.set_meta(
            f"{result.engine.name} · {result.mean_confidence * 100:.1f}% confidence"
        )
        self._metrics.setText(f"{result.line_count} lines · {result.timings.total_ms / 1000:.2f} s")
        self._status.setText("Done.")
        if result.warnings:
            self._status.setText(f"Done — {result.warnings[0]}")

    def _on_failed(self, message: str, detail: str) -> None:
        self._status.setText(f"Failed: {message}")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Extraction failed")
        box.setText(message)
        box.setInformativeText("The image was not changed. See details for the technical reason.")
        box.setDetailedText(detail)
        box.exec()

    def _on_cancelled(self) -> None:
        self._status.setText("Cancelled. The image is still loaded.")

    def _on_worker_finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        self._set_busy(False)
        self._progress.hide()
        self._update_actions()

    # -- result actions ---------------------------------------------------- #
    def _rerender_for_format(self) -> None:
        """Switching format re-renders the last result instead of re-running OCR."""
        if self._outcome is None:
            return
        output_format = self._selected_format()
        try:
            content = self._service.render(self._outcome.result, output_format)
        except Exception as exc:
            self._status.setText(f"Could not render {output_format.label}: {exc}")
            return
        self.result.set_content(content)

    def _copy_result(self) -> None:
        content = self.result.content()
        if not content:
            return
        QGuiApplication.clipboard().setText(content)
        self._status.setText("Copied to the clipboard.")

    def _save_result(self) -> None:
        content = self.result.content()
        if not content:
            return
        output_format = self._selected_format()
        stem = Path(self._source_name).stem or "textra"
        suggested = str(Path.home() / f"{stem}{output_format.suffix}")
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save extracted text",
            suggested,
            f"{output_format.label} (*{output_format.suffix})",
        )
        if not path:
            return
        try:
            Path(path).write_text(content, encoding="utf-8")
        except OSError as exc:
            self._warn("Could not save", f"{path}\n\n{exc.strerror or exc}")
            return
        self._status.setText(f"Saved {Path(path).name}.")

    # -- state ------------------------------------------------------------- #
    def _selected_format(self) -> OutputFormat:
        return OutputFormat(str(self.format_combo.currentData()))

    def _reset_result(self) -> None:
        self._outcome = None
        self.result.clear()
        self._metrics.setText("")

    def _set_busy(self, busy: bool) -> None:
        for widget in (
            self.open_button,
            self.paste_button,
            self.engine_combo,
            self.format_combo,
            self.preprocess_check,
            self.extract_button,
        ):
            widget.setEnabled(not busy)
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy)
        self._progress.setVisible(busy)

    def _update_actions(self) -> None:
        has_source = self._source_bytes is not None
        self.extract_button.setEnabled(has_source and self._worker is None)
        self.extract_button.setToolTip("" if has_source else "Open or paste an image first")

    def _warn(self, title: str, message: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(title)
        box.setInformativeText(message)
        box.exec()

    # -- window ------------------------------------------------------------ #
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                if path.suffix.lower() in SUPPORTED_SUFFIXES and path.is_file():
                    event.acceptProposedAction()
                    self.load_path(path)
                    return
        event.ignore()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(3000)
        self._service.close()
        event.accept()

    # -- test seam --------------------------------------------------------- #
    @property
    def has_source(self) -> bool:
        """True when an image bytes payload is loaded and ready to extract."""
        return self._source_bytes is not None

    @property
    def outcome(self) -> ExtractionOutcome | None:
        """The last successful outcome, for tests and for future menu actions."""
        return self._outcome

    @property
    def worker_running(self) -> bool:
        return self._worker is not None


__all__ = ["MainWindow"]
