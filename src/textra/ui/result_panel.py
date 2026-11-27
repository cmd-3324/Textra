"""The extracted text pane.

Read-only on purpose: the OCR output is evidence, not a draft. Editing it would
make "copy" and "export" quietly disagree with what the engine produced. Copy
and Save are plain buttons rather than hidden shortcuts so they are discoverable.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

PLACEHOLDER = "Extracted text will appear here."


class ResultPanel(QFrame):
    """A card holding the result header, actions and read-only text."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")

        title = QLabel("Extracted text", self)
        title.setObjectName("SectionTitle")

        self._meta = QLabel("", self)
        self._meta.setObjectName("Meta")

        self.copy_button = QPushButton("Copy", self)
        self.copy_button.setToolTip("Copy the whole document to the clipboard")
        self.copy_button.setMinimumWidth(74)
        self.save_button = QPushButton("Save…", self)
        self.save_button.setToolTip("Write the document to a file")
        self.save_button.setMinimumWidth(96)

        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(title)
        header.addWidget(self._meta)
        header.addStretch(1)
        header.addWidget(self.copy_button)
        header.addWidget(self.save_button)

        self._text = QPlainTextEdit(self)
        self._text.setReadOnly(True)
        self._text.setPlaceholderText(PLACEHOLDER)
        self._text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._text.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self._text, 1)

        self.set_actions_enabled(False)

    # -- content ---------------------------------------------------------- #
    def set_content(self, text: str) -> None:
        self._text.setPlainText(text)

    def content(self) -> str:
        return self._text.toPlainText()

    def set_meta(self, text: str) -> None:
        self._meta.setText(text)

    def set_actions_enabled(self, enabled: bool) -> None:
        for button in (self.copy_button, self.save_button):
            button.setEnabled(enabled)

    def clear(self) -> None:
        self._text.clear()
        self._meta.clear()
        self.set_actions_enabled(False)


__all__ = ["PLACEHOLDER", "ResultPanel"]
