"""The window chrome's hit test (Windows WM_NCHITTEST answers), pure."""

import pytest

from bayle_qt.launcher import chrome_hit as ht
from bayle_qt.launcher.chrome_hit import Rect

SIZE = (1000, 700)
BUTTONS = {ht.HTMINBUTTON: Rect(868, 0, 44, 32), ht.HTMAXBUTTON: Rect(912, 0, 44, 32), ht.HTCLOSE: Rect(956, 0, 44, 32)}
HOLES = [Rect(12, 0, 300, 32)]  # logo and menus


def at(x, y, maximized=False):
    return ht.hit_test(x, y, SIZE, border=6, caption_h=32, buttons=BUTTONS, holes=HOLES, maximized=maximized)


@pytest.mark.parametrize(
    ("x", "y", "want"),
    [
        (500, 16, ht.HTCAPTION),  # empty row: drag, double click, system menu
        (500, 12, ht.HTCAPTION),
        (100, 16, ht.HTCLIENT),  # over a menu
        (930, 16, ht.HTMAXBUTTON),  # the Snap Layouts flyout
        (880, 16, ht.HTMINBUTTON),
        (970, 16, ht.HTCLOSE),
        (500, 100, ht.HTCLIENT),
        (500, 33, ht.HTCLIENT),
        (0, 300, ht.HTLEFT),
        (999, 300, ht.HTRIGHT),
        (500, 2, ht.HTTOP),
        (500, 699, ht.HTBOTTOM),
        (2, 2, ht.HTTOPLEFT),
        (997, 2, ht.HTTOPRIGHT),
        (2, 697, ht.HTBOTTOMLEFT),
        (997, 697, ht.HTBOTTOMRIGHT),
    ],
)
def test_hit_codes(x, y, want):
    assert at(x, y) == want


def test_a_maximised_window_has_no_resize_edges():
    assert at(500, 1, maximized=True) == ht.HTCAPTION
    assert at(1, 300, maximized=True) == ht.HTCLIENT
    assert at(999, 1, maximized=True) == ht.HTCLOSE
