"""Themed confirmation and message dialogs.

Qt's ``QMessageBox`` keeps its platform icon and spacing even under a style
sheet, which looks out of place in this app.  These small dialogs are built from
regular widgets so they follow the theme consistently.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .theme import apply_widget_theme


class ConfirmDialog(QDialog):
    """A themed Yes/No confirmation, with an optional checkbox."""

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        detail: str = "",
        checkbox_text: str | None = None,
        destructive: bool = False,
        yes_text: str = "Yes",
        no_text: str = "No",
        force_yes_when_checked: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.checkbox_checked = False
        self._force_yes = force_yes_when_checked

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        heading = QLabel(title)
        heading.setObjectName("panelTitle")
        layout.addWidget(heading)

        body = QLabel(message)
        body.setWordWrap(True)
        body.setObjectName("dialogMessage")
        layout.addWidget(body)

        if detail:
            detail_label = QLabel(detail)
            detail_label.setWordWrap(True)
            detail_label.setProperty("class", "muted")
            detail_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(detail_label)

        self.checkbox: QCheckBox | None = None
        if checkbox_text:
            self.checkbox = QCheckBox(checkbox_text)
            self.checkbox.toggled.connect(self._on_checkbox)
            layout.addWidget(self.checkbox)

        layout.addSpacing(4)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)

        self.no_button = QPushButton(no_text)
        self.no_button.clicked.connect(self.reject)
        buttons.addWidget(self.no_button)

        self.yes_button = QPushButton(yes_text)
        self.yes_button.setProperty("class", "danger" if destructive else "primary")
        self.yes_button.setDefault(True)
        self.yes_button.clicked.connect(self.accept)
        buttons.addWidget(self.yes_button)
        layout.addLayout(buttons)

        apply_widget_theme(self)

    def _on_checkbox(self, checked: bool) -> None:
        self.checkbox_checked = checked
        if self._force_yes and checked:
            # Only Yes is allowed once "always" is chosen.
            self.no_button.setEnabled(False)
        else:
            self.no_button.setEnabled(True)

    @classmethod
    def ask(
        cls,
        parent: QWidget | None,
        title: str,
        message: str,
        **kwargs,
    ) -> tuple[bool, bool]:
        """Show the dialog; returns ``(confirmed, checkbox_checked)``."""
        dialog = cls(parent, title, message, **kwargs)
        result = dialog.exec()
        confirmed = result == QDialog.Accepted
        if dialog._force_yes and dialog.checkbox_checked:
            confirmed = True
        return confirmed, dialog.checkbox_checked


class MessageDialog(QDialog):
    """A themed informational/warning message with a single OK button."""

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        detail: str = "",
        rich: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        heading = QLabel(title)
        heading.setObjectName("panelTitle")
        layout.addWidget(heading)

        body = QLabel(message)
        body.setWordWrap(True)
        body.setObjectName("dialogMessage")
        if rich:
            body.setTextFormat(Qt.RichText)
            body.setOpenExternalLinks(True)
        layout.addWidget(body)

        if detail:
            detail_label = QLabel(detail)
            detail_label.setWordWrap(True)
            detail_label.setProperty("class", "muted")
            detail_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(detail_label)

        layout.addSpacing(4)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        ok = QPushButton("OK")
        ok.setProperty("class", "primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

        apply_widget_theme(self)

    @classmethod
    def show_message(
        cls,
        parent: QWidget | None,
        title: str,
        message: str,
        **kwargs,
    ) -> None:
        cls(parent, title, message, **kwargs).exec()
