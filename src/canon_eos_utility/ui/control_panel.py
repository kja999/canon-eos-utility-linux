"""Camera property controls (ISO, shutter speed, aperture, white balance)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..constants import PROPERTY_NAMES, VALUE_MAPS, PropertyCode, property_value_label

_CONTROLS = (
    PropertyCode.APERTURE,
    PropertyCode.SHUTTER_SPEED,
    PropertyCode.ISO,
    PropertyCode.WHITE_BALANCE,
)


class ControlPanel(QGroupBox):
    propertyChangeRequested = Signal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Camera controls", parent)
        self._updating = False
        self._combos: dict[int, QComboBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 12)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        for row, code in enumerate(_CONTROLS):
            label = QLabel(PROPERTY_NAMES.get(code, f"0x{code:04X}"))
            label.setProperty("class", "muted")
            combo = QComboBox()
            combo.setMinimumWidth(140)
            combo.currentIndexChanged.connect(lambda _index, c=code: self._on_changed(c))
            grid.addWidget(label, row, 0)
            grid.addWidget(combo, row, 1)
            self._combos[code] = combo

            for native, text in VALUE_MAPS.get(code, ()):  # type: ignore[arg-type]
                combo.addItem(text, int(native))

        grid.setColumnStretch(2, 1)
        layout.addLayout(grid)
        self.set_connected(False)

    # -- public API --------------------------------------------------------

    def set_connected(self, connected: bool) -> None:
        for combo in self._combos.values():
            combo.setEnabled(connected)

    def update_allowed_values(self, code: int, values: list[int]) -> None:
        combo = self._combos.get(code)
        if combo is None:
            return

        current = combo.currentData()
        self._updating = True
        try:
            combo.clear()
            for native in values:
                combo.addItem(property_value_label(code, native), int(native))
            self._select(combo, current)
        finally:
            self._updating = False

    def update_property(self, code: int, value: int) -> None:
        combo = self._combos.get(code)
        if combo is None:
            return
        self._updating = True
        try:
            if combo.findData(value) == -1:
                combo.addItem(property_value_label(code, value), int(value))
            self._select(combo, value)
        finally:
            self._updating = False

    # -- internals ---------------------------------------------------------

    def _select(self, combo: QComboBox, value) -> None:
        if value is None:
            return
        index = combo.findData(value)
        if index != -1:
            combo.setCurrentIndex(index)

    def _on_changed(self, code: int) -> None:
        if self._updating:
            return
        combo = self._combos[code]
        data = combo.currentData()
        if data is not None:
            self.propertyChangeRequested.emit(int(code), int(data))
