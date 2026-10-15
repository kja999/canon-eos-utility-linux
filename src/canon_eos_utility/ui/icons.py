"""Small, theme-coloured vector icons rendered from inline SVG.

Kept dependency-free (only Qt's SVG module) so the UI has consistent icons
without shipping bitmap assets or relying on platform icon themes.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_TRASH_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M3 6h18"/>'
    '<path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/>'
    '<path d="M6 6l1 14a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-14"/>'
    '<path d="M10 11v6"/>'
    '<path d="M14 11v6"/>'
    "</svg>"
)

_IMAGE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-6 -6 36 36" fill="none" '
    'stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="3" y="4" width="18" height="16" rx="2"/>'
    '<circle cx="8.5" cy="9" r="1.5"/>'
    '<path d="M21 16l-5-5L5 20"/>'
    "</svg>"
)

_MOVIE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-6 -6 36 36" fill="none" '
    'stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="3" y="5" width="18" height="14" rx="2"/>'
    '<path d="M10 9.5l5 2.5-5 2.5z"/>'
    "</svg>"
)

#: Application icon (an aperture), matching packaging/icons/*.svg.
_APP_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">'
    '<rect width="256" height="256" rx="56" fill="#1c1c1c"/>'
    '<circle cx="128" cy="128" r="72" fill="none" stroke="#c68e6e" stroke-width="10"/>'
    '<g stroke="#c68e6e" stroke-width="9" stroke-linecap="round" fill="none">'
    '<path d="M200 128 L92 190.35"/>'
    '<path d="M164 190.35 L56 128"/>'
    '<path d="M92 190.35 L92 65.65"/>'
    '<path d="M56 128 L164 65.65"/>'
    '<path d="M92 65.65 L200 128"/>'
    '<path d="M164 65.65 L164 190.35"/>'
    "</g>"
    '<circle cx="128" cy="128" r="16" fill="#c68e6e"/>'
    "</svg>"
)


def _render_pixmap(svg: str, size: int, color: str | None = None) -> QPixmap:
    text = svg.format(color=color) if color is not None else svg
    renderer = QSvgRenderer(QByteArray(text.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


def svg_icon(svg: str, color: str, size: int = 18) -> QIcon:
    """Render an SVG string to a square :class:`QIcon` in ``color``."""
    return QIcon(_render_pixmap(svg, size, color))


def trash_icon(color: str, size: int = 18) -> QIcon:
    return svg_icon(_TRASH_SVG, color, size)


def image_icon(color: str, size: int = 18) -> QIcon:
    return svg_icon(_IMAGE_SVG, color, size)


def movie_icon(color: str, size: int = 18) -> QIcon:
    return svg_icon(_MOVIE_SVG, color, size)


def app_icon() -> QIcon:
    """Multi-resolution application icon."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_render_pixmap(_APP_SVG, size))
    return icon


def app_logo(size: int = 160) -> QPixmap:
    """The application mark (an aperture), rendered crisply at ``size`` logical px."""
    screen = QGuiApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen is not None else 1.0
    pixmap = _render_pixmap(_APP_SVG, max(1, round(size * ratio)))
    pixmap.setDevicePixelRatio(ratio)
    return pixmap
