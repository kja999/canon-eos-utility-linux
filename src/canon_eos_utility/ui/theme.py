"""Application look and feel.

A modern, neutral dark theme inspired by RapidRAW's palette but with more
restrained corner radii.  Uses a Poppins → Inter → Noto Sans font stack so the
preferred font is picked up automatically when installed.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QWidget

# -- palette (neutral greys) ----------------------------------------------
BG = "#181818"
SURFACE = "#1c1c1c"
SURFACE_2 = "#232323"
SURFACE_3 = "#2b2b2b"
BORDER = "#2d2d2d"
BORDER_STRONG = "#3a3a3a"
TEXT = "#e8eaed"
MUTED = "#9e9e9e"
DANGER = "#e5544b"

#: The built-in accent, used when the system colour cannot be determined.
DEFAULT_ACCENT = "#c68e6e"
#: Accent-derived colours, updated by :func:`resolve_accent`.
ACCENT = DEFAULT_ACCENT
ACCENT_HOVER = "#d6a081"
ACCENT_PRESSED = "#b57d5f"
ON_ACCENT = "#1a1a1a"
SELECTION = "rgba(198, 142, 110, 0.28)"

#: Highlight colours used by Qt's built-in styles; not real system accents.
_STYLE_DEFAULT_HIGHLIGHTS = {"#308cc6", "#0078d7", "#3465a4", "#2a82da"}

#: GNOME's named accent colours (org.gnome.desktop.interface accent-color).
_GNOME_ACCENTS = {
    "blue": "#3584e4",
    "teal": "#2190a4",
    "green": "#3a944a",
    "yellow": "#c88800",
    "orange": "#ed5b00",
    "red": "#e62d42",
    "pink": "#d56199",
    "purple": "#9141ac",
    "slate": "#6f8396",
}

#: Preferred UI fonts, in order.  Poppins ships with the app (see ``ui/fonts``).
FONT_STACK = ("Poppins", "Inter", "Noto Sans", "Cantarell")

_FONT_DIR = Path(__file__).with_name("fonts")
_bundled_family: str | None = None
_bundled_loaded = False


def _load_bundled_fonts() -> str | None:
    """Register the Poppins files shipped in ``ui/fonts`` and return the family."""
    global _bundled_family, _bundled_loaded
    if _bundled_loaded:
        return _bundled_family
    if QApplication.instance() is None or not _FONT_DIR.is_dir():
        return None
    _bundled_loaded = True
    try:
        for path in sorted(_FONT_DIR.glob("*.ttf")):
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id == -1:
                continue
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families and _bundled_family is None:
                _bundled_family = families[0]
    except Exception:  # pragma: no cover - platform font issues
        _bundled_family = None
    return _bundled_family


def available_font() -> str:
    bundled = _load_bundled_fonts()
    if bundled:
        return bundled
    try:
        families = set(QFontDatabase.families())
    except Exception:  # pragma: no cover - no QApplication yet
        families = set()
    for family in FONT_STACK:
        if family in families:
            return family
    return "sans-serif"


# -- accent resolution -----------------------------------------------------


def set_accent(color: QColor) -> None:
    """Set the active accent (and derived colours) used by the stylesheet."""
    global ACCENT, ACCENT_HOVER, ACCENT_PRESSED, ON_ACCENT, SELECTION
    if not color.isValid():
        color = QColor(DEFAULT_ACCENT)
    ACCENT = color.name()
    ACCENT_HOVER = color.lighter(115).name()
    ACCENT_PRESSED = color.darker(118).name()
    ON_ACCENT = "#1a1a1a" if color.lightnessF() > 0.55 else "#ffffff"
    red, green, blue, _ = color.getRgb()
    SELECTION = f"rgba({red}, {green}, {blue}, 0.28)"


def resolve_accent(app: QApplication | None, value: str = "auto") -> QColor:
    """Return the accent colour to use.

    Precedence: an explicit ``value`` (hex) → the Qt platform theme's highlight
    (e.g. the GTK/KDE theme when ``QT_QPA_PLATFORMTHEME`` is set) → the active
    GTK theme's selected colour → GNOME's accent setting → the built-in accent.
    The chosen colour is applied via :func:`set_accent`.
    """
    text = (value or "auto").strip()
    if text and text.lower() != "auto":
        color = QColor(text)
        if color.isValid():
            set_accent(color)
            return color

    color = _platform_highlight(app) or _gtk_theme_color() or _gnome_accent()
    if color is None or not color.isValid():
        color = QColor(DEFAULT_ACCENT)
    set_accent(color)
    return color


def _platform_highlight(app: QApplication | None) -> QColor | None:
    if app is None:
        return None
    try:
        highlight = app.palette().color(QPalette.Highlight)
    except Exception:  # pragma: no cover
        return None
    if not highlight.isValid():
        return None
    name = highlight.name().lower()
    if name in _STYLE_DEFAULT_HIGHLIGHTS or name == ACCENT.lower():
        return None
    return highlight


def _gsettings_get(key: str) -> str | None:
    try:
        result = subprocess.run(
            ["gsettings", "get", *key.split()],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip().strip("'").strip('"') or None


def _gtk_theme_color() -> QColor | None:
    """Read the selected colour from the active GTK theme's CSS."""
    name = _gsettings_get("org.gnome.desktop.interface gtk-theme")
    if not name:
        name = os.environ.get("GTK_THEME", "")
    name = name.split(":")[0].strip()
    if not name:
        return None

    defines: dict[str, str] = {}
    for base in (os.path.expanduser("~/.themes"), "/usr/share/themes"):
        for sub in ("gtk-3.0", "gtk-4.0"):
            for css in ("gtk.css", "gtk-contained.css"):
                path = os.path.join(base, name, sub, css)
                if os.path.exists(path):
                    defines.update(_parse_gtk_defines(path))
    for key in (
        "theme_selected_bg_color",
        "accent_color",
        "accent_bg_color",
        "selected_bg_color",
    ):
        color = _resolve_gtk_define(defines, key)
        if color is not None and color.isValid():
            return color
    return None


def _parse_gtk_defines(path: str) -> dict[str, str]:
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            text = handle.read()
    except OSError:  # pragma: no cover
        return {}
    return {
        match.group(1): match.group(2).strip()
        for match in re.finditer(r"@define-color\s+([A-Za-z0-9_\-]+)\s+([^;]+);", text)
    }


def _resolve_gtk_define(defines: dict[str, str], key: str, depth: int = 0) -> QColor | None:
    value = defines.get(key)
    if value is None or depth > 5:
        return None
    if value.startswith("@"):
        return _resolve_gtk_define(defines, value[1:].strip(), depth + 1)
    return _parse_color(value)


def _parse_color(value: str) -> QColor | None:
    value = value.strip()
    rgb = re.match(r"rgba?\(([^)]+)\)", value)
    if rgb:
        parts = [p.strip() for p in rgb.group(1).split(",")]
        try:
            red, green, blue = (int(float(p)) for p in parts[:3])
            alpha = 255
            if len(parts) >= 4:
                alpha = int(float(parts[3]) * 255) if "." in parts[3] else int(parts[3])
            return QColor(red, green, blue, alpha)
        except (ValueError, IndexError):
            return None
    color = QColor(value)
    return color if color.isValid() else None


def _gnome_accent() -> QColor | None:
    name = _gsettings_get("org.gnome.desktop.interface accent-color")
    if not name:
        return None
    hex_value = _GNOME_ACCENTS.get(name.lower())
    return QColor(hex_value) if hex_value else None


def build_stylesheet(font_family: str = "Inter") -> str:
    return f"""
* {{
    font-family: "{font_family}", "Noto Sans", sans-serif;
    font-size: 13px;
    outline: none;
}}

QWidget {{
    background-color: {BG};
    color: {TEXT};
}}

QMainWindow, QDialog {{ background-color: {BG}; }}

QToolTip {{
    background-color: {SURFACE_2};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 5px;
    padding: 5px 8px;
}}

/* -- menus / status bar ------------------------------------------------ */
QMenuBar {{
    background-color: {SURFACE};
    border-bottom: 1px solid {BORDER};
    padding: 2px 6px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 6px 10px;
    border-radius: 5px;
}}
QMenuBar::item:selected {{ background-color: {SURFACE_3}; }}
QMenu {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 22px 7px 14px;
    border-radius: 5px;
}}
QMenu::item:selected {{ background-color: {ACCENT}; color: {ON_ACCENT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 6px 8px; }}

QStatusBar {{
    background-color: {SURFACE};
    color: {MUTED};
    border-top: 1px solid {BORDER};
}}
QStatusBar::item {{ border: none; }}

/* -- panels ------------------------------------------------------------ */
QGroupBox {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 14px;
    padding: 14px 12px 12px 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: {MUTED};
    font-size: 11px;
    text-transform: uppercase;
}}

QListWidget, QListView, QTreeView, QPlainTextEdit, QTextEdit {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px;
}}
QListWidget::item {{
    border-radius: 6px;
    padding: 6px;
    margin: 3px;
}}
QListWidget::item:hover {{ background-color: {SURFACE_2}; }}
QListWidget::item:selected {{
    background-color: {SELECTION};
    color: {TEXT};
}}

/* -- buttons ----------------------------------------------------------- */
QPushButton, QToolButton {{
    background-color: {SURFACE_2};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 7px 14px;
    min-height: 20px;
}}
QPushButton:hover, QToolButton:hover {{ background-color: {SURFACE_3}; }}
QPushButton:pressed, QToolButton:pressed {{ background-color: {BORDER_STRONG}; }}
QPushButton:disabled, QToolButton:disabled {{
    color: {MUTED};
    background-color: {SURFACE};
    border-color: {BORDER};
}}
QPushButton:checked, QToolButton:checked {{
    background-color: {ACCENT};
    color: {ON_ACCENT};
    border-color: {ACCENT};
}}

QPushButton[class="primary"], QToolButton[class="primary"] {{
    background-color: {ACCENT};
    color: {ON_ACCENT};
    border: 1px solid {ACCENT};
    font-weight: 600;
}}
QPushButton[class="primary"]:hover, QToolButton[class="primary"]:hover {{
    background-color: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton[class="primary"]:pressed, QToolButton[class="primary"]:pressed {{
    background-color: {ACCENT_PRESSED};
    border-color: {ACCENT_PRESSED};
}}
QPushButton[class="primary"]:disabled, QToolButton[class="primary"]:disabled {{
    background-color: {SURFACE_2};
    color: {MUTED};
    border-color: {BORDER};
}}

QPushButton[class="danger"], QToolButton[class="danger"] {{
    color: {DANGER};
    border-color: rgba(229, 84, 75, 0.45);
}}
QPushButton[class="danger"]:hover, QToolButton[class="danger"]:hover {{
    background-color: rgba(229, 84, 75, 0.16);
    border-color: {DANGER};
}}
QPushButton[class="danger"]:pressed, QToolButton[class="danger"]:pressed {{
    background-color: rgba(229, 84, 75, 0.28);
}}
QPushButton[class="danger"]:disabled, QToolButton[class="danger"]:disabled {{
    color: {MUTED};
    border-color: {BORDER};
}}

/* -- inputs ------------------------------------------------------------ */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 7px 10px;
    selection-background-color: {ACCENT};
    selection-color: {ON_ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit:disabled, QComboBox:disabled {{
    color: {MUTED};
    background-color: {SURFACE};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    selection-background-color: {ACCENT};
    selection-color: {ON_ACCENT};
    padding: 4px;
}}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid {BORDER_STRONG};
    background-color: {SURFACE_2};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

/* -- progress ---------------------------------------------------------- */
QProgressBar {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background-color: {ACCENT}; border-radius: 5px; }}

/* -- splitters / scrollbars ------------------------------------------- */
QSplitter::handle {{ background-color: {BG}; }}
QSplitter::handle:horizontal {{ width: 8px; }}
QSplitter::handle:vertical {{ height: 8px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {SURFACE_3};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {BORDER_STRONG}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {SURFACE_3};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* -- named panels ------------------------------------------------------ */
#connectionBar {{
    background-color: {SURFACE};
    border-bottom: 1px solid {BORDER};
}}
#toolRail {{
    background-color: {SURFACE};
    border-left: 1px solid {BORDER};
}}
#toolRail QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 8px 6px;
    min-width: 40px;
    font-size: 10px;
}}
#toolRail QToolButton:hover {{ background-color: {SURFACE_2}; }}
#toolRail QToolButton:checked {{
    background-color: {ACCENT};
    color: {ON_ACCENT};
}}
#panelTitle {{ font-size: 14px; font-weight: 600; }}
#dialogMessage {{ font-size: 14px; }}
#hintLabel, QLabel[class="muted"] {{ color: {MUTED}; }}
#liveView {{
    background-color: #0d0d0d;
    border: 1px solid {BORDER};
    border-radius: 8px;
    color: {MUTED};
}}
#previewBox {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 8px;
    font-family: monospace;
}}

/* -- splash ------------------------------------------------------------ */
#splashRoot {{ background: transparent; }}
#splashCard {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 18px;
}}
#splashCard QLabel {{ background: transparent; }}
#splashTitle {{
    color: {TEXT};
    font-size: 26px;
    font-weight: 600;
}}
#splashAuthor {{ color: {MUTED}; font-size: 13px; }}
#splashVersion {{ color: {MUTED}; font-size: 11px; }}
"""


STYLESHEET = build_stylesheet("Poppins")


def apply_theme(app: QApplication, accent: str = "auto") -> None:
    """Apply the palette and stylesheet to the whole application.

    ``accent`` is ``"auto"`` (follow the system/theme), or an explicit colour
    such as ``"#9141ac"``.
    """
    family = available_font()
    # Resolve the accent before we replace the palette, so we can read the
    # platform theme's highlight colour.
    resolve_accent(app, accent)
    app.setStyle("Fusion")
    app.setFont(QFont(family, 10))
    app.setPalette(_dark_palette())
    app.setStyleSheet(build_stylesheet(family))


def apply_widget_theme(widget: QWidget, accent: str = "auto") -> None:
    """Apply the stylesheet to a single widget tree (when there is no app)."""
    resolve_accent(QApplication.instance(), accent)
    widget.setStyleSheet(build_stylesheet(available_font()))


def _dark_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BG))
    palette.setColor(QPalette.WindowText, QColor(TEXT))
    palette.setColor(QPalette.Base, QColor(SURFACE))
    palette.setColor(QPalette.AlternateBase, QColor(SURFACE_2))
    palette.setColor(QPalette.Text, QColor(TEXT))
    palette.setColor(QPalette.Button, QColor(SURFACE_2))
    palette.setColor(QPalette.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor(ON_ACCENT))
    palette.setColor(QPalette.ToolTipBase, QColor(SURFACE_2))
    palette.setColor(QPalette.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.PlaceholderText, QColor(MUTED))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(MUTED))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(MUTED))
    return palette
