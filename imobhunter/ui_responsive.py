"""Screen-aware sizing of independent desktop windows.

All Qt measurements use logical (DPI-adjusted) pixels. QApplication.screen()
availableGeometry excludes the Windows taskbar and system dock.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QWidget


def geometry_within_screen(
    available: QRect, preferred: QSize, minimum: QSize, margin: int = 12,
) -> QRect:
    """Fit a window entirely inside the usable monitor area.

    Minimum size is a preference, not a reason to extend behind the taskbar:
    on a low-resolution screen the content itself must be scrollable.
    """
    padding = max(0, int(margin))
    width = max(1, available.width() - padding * 2)
    height = max(1, available.height() - padding * 2)
    target_width = min(width, max(minimum.width(), preferred.width()))
    target_height = min(height, max(minimum.height(), preferred.height()))
    left = available.x() + (available.width() - target_width) // 2
    top = available.y() + (available.height() - target_height) // 2
    return QRect(left, top, target_width, target_height)


def fit_window_to_screen(
    window: QWidget, preferred: QSize, minimum: QSize, margin: int = 12,
) -> None:
    """Use the parent window's display, then the cursor display, then primary."""
    screen = None
    parent = window.parentWidget()
    if parent is not None:
        screen = parent.window().screen()
    if screen is None:
        screen = window.screen() or QGuiApplication.screenAt(QCursor.pos())
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is None:
        window.resize(preferred)
        return
    rectangle = geometry_within_screen(
        screen.availableGeometry(), preferred, minimum, margin,
    )
    window.setMinimumSize(
        min(minimum.width(), rectangle.width()),
        min(minimum.height(), rectangle.height()),
    )
    window.resize(rectangle.size())
    window.move(rectangle.topLeft())
