"""Image preview and drop target.

The widget owns no file logic beyond accepting a dropped path and announcing it;
reading, validating and OCR all happen in the service. Scaling keeps the aspect
ratio so a tall receipt stays legible instead of being stretched to the pane.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QImage,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

EMPTY_TEXT = "Drop an image here\nor press Ctrl+V to paste"
SUPPORTED_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"})


class ImagePreview(QFrame):
    """A card that shows one image and accepts image files dragged onto it."""

    fileDropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAcceptDrops(True)
        self.setMinimumWidth(320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._pixmap: QPixmap | None = None

        self._canvas = QLabel(EMPTY_TEXT, self)
        self._canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._canvas.setWordWrap(True)
        self._canvas.setObjectName("Meta")

        self._caption = QLabel("No image loaded", self)
        self._caption.setObjectName("Meta")
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(8)
        layout.addWidget(self._canvas, 1)
        layout.addWidget(self._caption, 0)

    # -- content ---------------------------------------------------------- #
    def show_image(self, image: QImage, name: str) -> None:
        """Replace the placeholder with ``image``, sized to the pane."""
        self._pixmap = QPixmap.fromImage(image)
        self._caption.setText(f"{name}  ·  {image.width()} x {image.height()}")
        self._rescale()

    @property
    def has_image(self) -> bool:
        return self._pixmap is not None and not self._pixmap.isNull()

    # -- geometry --------------------------------------------------------- #
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            return
        area = self._canvas.size()
        if area.width() <= 0 or area.height() <= 0:
            return
        self._canvas.setText("")
        self._canvas.setPixmap(
            self._pixmap.scaled(
                area,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    # -- drag and drop ---------------------------------------------------- #
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._first_supported_url(event) is not None:
            event.acceptProposedAction()
            self.setProperty("dragActive", True)
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        path = self._first_supported_url(event)
        if path is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.fileDropped.emit(path)

    @staticmethod
    def _first_supported_url(event: QDragEnterEvent | QDropEvent) -> str | None:
        mime = event.mimeData()
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.suffix.lower() in SUPPORTED_SUFFIXES and path.is_file():
                return str(path)
        return None


__all__ = ["EMPTY_TEXT", "SUPPORTED_SUFFIXES", "ImagePreview"]
