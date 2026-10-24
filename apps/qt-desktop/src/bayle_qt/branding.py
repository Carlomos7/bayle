"""Which logo and window icon the window shows (the Logo setting stays in the engine's settings)."""

from pathlib import Path

from bayle_qt.resources import ASSETS_DIR


def logo_kind(theme_dark: bool, logo: str = "auto") -> str:
    """Which mark to show: crimson, ice or gold. auto follows the window theme (crimson dark, ice light)."""
    if logo in ("crimson", "ice", "gold"):
        return logo
    return "crimson" if theme_dark else "ice"


def logo_path(theme_dark: bool, logo: str = "auto") -> Path:
    """The emblem for the top bar."""
    return ASSETS_DIR / f"logo-{logo_kind(theme_dark, logo)}.png"


def app_icon_path(theme_dark: bool, logo: str = "auto") -> Path:
    """The tile for the window and taskbar."""
    return ASSETS_DIR / f"app-{logo_kind(theme_dark, logo)}.png"
