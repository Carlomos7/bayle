"""Where the pointer is on the window chrome row (Windows): the pure part of the WM_NCHITTEST answer, so it is testable
without a window. Coordinates are window-client pixels or points, as long as every argument uses the same unit."""

from typing import NamedTuple

HTCLIENT, HTCAPTION = 1, 2
HTMINBUTTON, HTMAXBUTTON, HTCLOSE = 8, 9, 20
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT, HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 10, 11, 12, 13, 14, 15, 16, 17


class Rect(NamedTuple):
    x: float
    y: float
    w: float
    h: float

    def has(self, px: float, py: float) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h


_EDGES = {  # (column, row) of the 3x3 grid over the window -> resize code
    (0, 0): HTTOPLEFT, (1, 0): HTTOP, (2, 0): HTTOPRIGHT,
    (0, 1): HTLEFT, (2, 1): HTRIGHT,
    (0, 2): HTBOTTOMLEFT, (1, 2): HTBOTTOM, (2, 2): HTBOTTOMRIGHT,
}  # fmt: skip


def hit_test(
    x: float,
    y: float,
    size: tuple[float, float],
    *,
    border: float,
    caption_h: float,
    buttons: dict[int, Rect],
    holes: list[Rect],
    maximized: bool,
) -> int:
    """The HT code for a point. Resize edges first (never when maximized), then the caption buttons (code -> rect),
    then the caption row: HTCAPTION (drag, double click, system menu) except over the `holes` (menus, logo), which
    stay client."""
    w, h = size
    if not maximized:
        col = 0 if x < border else 2 if x >= w - border else 1
        row = 0 if y < border else 2 if y >= h - border else 1
        if (col, row) in _EDGES:
            return _EDGES[col, row]
    for code, rect in buttons.items():
        if rect.has(x, y):
            return code
    if 0 <= y < caption_h and not any(r.has(x, y) for r in holes):
        return HTCAPTION
    return HTCLIENT
