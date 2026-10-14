"""The desktop's own colours, so the app can follow them ("sync with desktop theme", Fixer Upper S4).

A browser page cannot see the Windows accent colour or the wallpaper, but this engine runs on the same PC and can.
Three things are read, all read-only and all optional:

* the accent colour Windows draws title bars and buttons with (the DWM ``AccentColor`` value),
* whether apps are set to dark or light mode,
* the average colour of the wallpaper (or the solid background colour when there is no picture).

Every reader is a small function that is handed in, so tests run without Windows, a registry or a real wallpaper. On any
other system, or if something is missing, a field is simply ``None``; this module never raises and never guesses.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional, Tuple


def _hex(r: int, g: int, b: int) -> str:
    return f"#{r & 255:02x}{g & 255:02x}{b & 255:02x}"


def accent_from_dword(value: int) -> str:
    """Windows stores the accent as 0xAABBGGRR (alpha, blue, green, red); the page wants #rrggbb."""
    return _hex(value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF)


def _read_registry(path: str, name: str) -> Optional[Any]:  # pragma: no cover - needs Windows
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except Exception:
        return None


def average_color(path: str) -> Optional[str]:  # pragma: no cover - needs Pillow and a real image
    """Mean colour of a picture, found by shrinking it to one pixel (cheap, and good enough for a tint)."""
    try:
        from PIL import Image

        with Image.open(path) as image:
            r, g, b = image.convert("RGB").resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
        return _hex(r, g, b)
    except Exception:
        return None


def solid_background(text: Any) -> Optional[str]:
    """The Control Panel stores the plain desktop colour as "R G B" (decimal)."""
    try:
        r, g, b = (int(part) for part in str(text).split())
        return _hex(r, g, b)
    except Exception:
        return None


def read_desktop_theme(
    reader: Callable[[str, str], Optional[Any]] = _read_registry,
    average: Callable[[str], Optional[str]] = average_color,
    is_windows: Optional[bool] = None,
) -> Dict[str, Any]:
    """What the desktop looks like right now. ``available`` is False off Windows; fields it cannot read are None."""
    windows = (os.name == "nt") if is_windows is None else is_windows
    result: Dict[str, Any] = {"available": windows, "accent": None, "dark": None, "wallpaper_color": None}
    if not windows:
        return result
    accent = reader(r"Software\Microsoft\Windows\DWM", "AccentColor")
    if isinstance(accent, int):
        result["accent"] = accent_from_dword(accent)
    light = reader(r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "AppsUseLightTheme")
    if isinstance(light, int):
        result["dark"] = light == 0
    picture = reader(r"Control Panel\Desktop", "WallPaper")
    if isinstance(picture, str) and picture and os.path.isfile(picture):
        result["wallpaper_color"] = average(picture)
    if result["wallpaper_color"] is None:
        result["wallpaper_color"] = solid_background(reader(r"Control Panel\Colors", "Background"))
    return result
