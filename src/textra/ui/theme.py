"""Two restrained themes.

The window has one job: show an image and the text that came out of it. The
stylesheets therefore stay small - a neutral surface, one accent for the primary
action, monospace only where text is the subject. Qt's Fusion style is selected
explicitly so the result looks the same on Windows, macOS and Linux instead of
inheriting three different native looks.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True, slots=True)
class Theme:
    window: str
    surface: str
    surface_alt: str
    border: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_text: str
    disabled: str
    selection: str


DARK = Theme(
    window="#14161a",
    surface="#1b1e24",
    surface_alt="#12141a",
    border="#2a2f38",
    text="#e8eaed",
    muted="#9aa3b2",
    accent="#3b82f6",
    accent_hover="#4b8ff8",
    accent_text="#ffffff",
    disabled="#666f7d",
    selection="#2f4b7c",
)

LIGHT = Theme(
    window="#f5f6f8",
    surface="#ffffff",
    surface_alt="#fbfbfd",
    border="#dde1e8",
    text="#1d222b",
    muted="#67707f",
    accent="#2563eb",
    accent_hover="#1d4ed8",
    accent_text="#ffffff",
    disabled="#a3aab6",
    selection="#cfe0ff",
)

THEMES = {"dark": DARK, "light": LIGHT}


def _stylesheet(theme: Theme) -> str:
    return f"""
    QMainWindow, QWidget#Root {{
        background: {theme.window};
        color: {theme.text};
    }}
    QLabel {{ color: {theme.text}; background: transparent; }}
    QLabel#AppTitle {{ font-size: 19px; font-weight: 600; letter-spacing: 0.2px; }}
    QLabel#Tagline {{ color: {theme.muted}; font-size: 12px; }}
    QLabel#SectionTitle {{ font-weight: 600; font-size: 13px; }}
    QLabel#Meta {{ color: {theme.muted}; font-size: 12px; }}
    QFrame#Card {{
        background: {theme.surface};
        border: 1px solid {theme.border};
        border-radius: 10px;
    }}
    QPushButton {{
        background: {theme.surface};
        color: {theme.text};
        border: 1px solid {theme.border};
        border-radius: 7px;
        padding: 7px 13px;
    }}
    QPushButton:hover {{ border-color: {theme.accent}; }}
    QPushButton:pressed {{ background: {theme.surface_alt}; }}
    QPushButton:disabled {{ color: {theme.disabled}; border-color: {theme.border}; }}
    QPushButton#Primary {{
        background: {theme.accent};
        border: 1px solid {theme.accent};
        color: {theme.accent_text};
        font-weight: 600;
        padding: 8px 20px;
    }}
    QPushButton#Primary:hover {{ background: {theme.accent_hover}; border-color: {theme.accent_hover}; }}
    QPushButton#Primary:disabled {{ background: {theme.border}; border-color: {theme.border}; color: {theme.disabled}; }}
    QComboBox {{
        background: {theme.surface_alt};
        color: {theme.text};
        border: 1px solid {theme.border};
        border-radius: 7px;
        padding: 5px 9px;
        min-width: 128px;
    }}
    QComboBox:hover {{ border-color: {theme.accent}; }}
    QComboBox QAbstractItemView {{
        background: {theme.surface};
        color: {theme.text};
        border: 1px solid {theme.border};
        selection-background-color: {theme.selection};
        selection-color: {theme.text};
        outline: none;
    }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QPlainTextEdit {{
        background: {theme.surface_alt};
        color: {theme.text};
        border: 1px solid {theme.border};
        border-radius: 8px;
        padding: 10px;
        selection-background-color: {theme.selection};
        selection-color: {theme.text};
        font-family: "Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono", monospace;
        font-size: 13px;
    }}
    QPlainTextEdit:focus {{ border-color: {theme.accent}; }}
    QCheckBox {{ color: {theme.muted}; spacing: 7px; }}
    QCheckBox::indicator {{
        width: 15px; height: 15px;
        border: 1px solid {theme.border};
        border-radius: 4px;
        background: {theme.surface_alt};
    }}
    QCheckBox::indicator:checked {{
        background: {theme.accent};
        border-color: {theme.accent};
    }}
    QStatusBar {{
        background: {theme.window};
        color: {theme.muted};
        border-top: 1px solid {theme.border};
        font-size: 12px;
    }}
    QStatusBar::item {{ border: none; }}
    QProgressBar {{
        background: {theme.border};
        border: none;
        border-radius: 3px;
        max-height: 6px;
        min-width: 120px;
    }}
    QProgressBar::chunk {{ background: {theme.accent}; border-radius: 3px; }}
    QSplitter::handle {{ background: transparent; width: 12px; }}
    QToolTip {{
        background: {theme.surface};
        color: {theme.text};
        border: 1px solid {theme.border};
        padding: 5px;
    }}
    QMessageBox {{ background: {theme.surface}; }}
    """


def _palette(theme: Theme) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(theme.window))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(theme.text))
    palette.setColor(QPalette.ColorRole.Base, QColor(theme.surface_alt))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(theme.surface))
    palette.setColor(QPalette.ColorRole.Text, QColor(theme.text))
    palette.setColor(QPalette.ColorRole.Button, QColor(theme.surface))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(theme.text))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(theme.accent))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(theme.accent_text))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(theme.surface))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(theme.text))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(theme.muted))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(theme.disabled))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(theme.disabled)
    )
    return palette


def apply_theme(app: QApplication, name: str) -> Theme:
    """Apply ``name`` (``dark`` or ``light``) to the whole application."""
    theme = THEMES.get(name, DARK)
    app.setStyle("Fusion")
    app.setPalette(_palette(theme))
    app.setStyleSheet(_stylesheet(theme))
    return theme


__all__ = ["DARK", "LIGHT", "THEMES", "Theme", "apply_theme"]
