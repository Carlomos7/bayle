"""The Windows window chrome: the native frame stays (shadow, Snap Layouts, system menu, Aero snap), but the client
area is the whole window, so our one QML row (logo, menus, centred title, minimise/maximise/close) replaces the OS
caption row. The technique of Windows Terminal and qwindowkit:

- WM_NCCALCSIZE returns 0 with the client rect untouched (maximised: inset by the frame so nothing is clipped);
- WM_NCHITTEST answers from chrome_hit.hit_test over the rects of the QML items (found by objectName), so the
  maximise button is HTMAXBUTTON, which is what makes the Snap Layouts flyout appear, and empty row is HTCAPTION;
- those buttons then get only non-client mouse messages, so hover and click are handled here from WM_NC* and shown
  by QML through the window's `chromeHot` / `chromeDown` properties;
- DwmExtendFrameIntoClientArea keeps the shadow.
Only runs on Windows (the hit-testing itself is in chrome_hit and unit tested)."""

import ctypes
import sys
from ctypes import wintypes

import shiboken6
from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QPointF
from PySide6.QtQuick import QQuickItem, QQuickWindow

from bayle.ui.launcher import chrome_hit as ht

WM_NCCALCSIZE, WM_NCHITTEST = 0x83, 0x84
WM_NCMOUSEMOVE, WM_NCLBUTTONDOWN, WM_NCLBUTTONUP, WM_NCMOUSELEAVE = 0xA0, 0xA1, 0xA2, 0x2A2
WM_SYSCOMMAND = 0x112
SC_MINIMIZE, SC_MAXIMIZE, SC_CLOSE, SC_RESTORE = 0xF020, 0xF030, 0xF060, 0xF120
_NAMES = {ht.HTMINBUTTON: "min", ht.HTMAXBUTTON: "max", ht.HTCLOSE: "close"}  # also the QML objectName: chromeMin...
_HANDLED = {WM_NCCALCSIZE, WM_NCHITTEST, WM_NCMOUSEMOVE, WM_NCLBUTTONDOWN, WM_NCLBUTTONUP, WM_NCMOUSELEAVE}


def available() -> bool:
    return sys.platform == "win32"


class _TrackMouse(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("hwndTrack", wintypes.HWND),
        ("dwHoverTime", wintypes.DWORD),
    ]


def _item(win: QQuickWindow, name: str) -> QQuickItem | None:
    todo = [win.contentItem()]
    while todo:
        item = todo.pop()
        if item.objectName() == name:
            return item
        todo.extend(item.childItems())
    return None


class WindowChrome(QAbstractNativeEventFilter):
    def __init__(self, win: QQuickWindow):
        super().__init__()
        self.win = win
        self.hwnd = 0
        self.down = ""
        self._items: dict[str, QQuickItem | None] = {}
        u = self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, *[ctypes.c_int] * 4, wintypes.UINT]
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.IsZoomed.argtypes = [wintypes.HWND]
        u.GetDpiForWindow.argtypes = [wintypes.HWND]
        u.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wintypes.UINT]
        u.TrackMouseEvent.argtypes = [ctypes.POINTER(_TrackMouse)]

    def install(self) -> None:
        """Call with the window built and not yet shown."""
        app = QCoreApplication.instance()
        if app is None:
            return
        self.win.create()
        self.hwnd = int(self.win.winId())
        app.installNativeEventFilter(self)
        margins = (ctypes.c_int * 4)(1, 1, 1, 1)  # a 1 px frame: the DWM shadow (and Windows 11's border) stay
        dwm = ctypes.WinDLL("dwmapi")
        dwm.DwmExtendFrameIntoClientArea.argtypes = [wintypes.HWND, ctypes.c_void_p]
        dwm.DwmExtendFrameIntoClientArea(self.hwnd, margins)
        # NOMOVE | NOSIZE | NOZORDER | NOACTIVATE | FRAMECHANGED: Windows asks WM_NCCALCSIZE again
        self.user32.SetWindowPos(self.hwnd, None, 0, 0, 0, 0, 0x2 | 0x1 | 0x4 | 0x10 | 0x20)

    def remove(self) -> None:
        app = QCoreApplication.instance()
        if app is not None:
            app.removeNativeEventFilter(self)

    # ---- geometry, in physical pixels of the client area
    def _rect(self, name: str) -> ht.Rect | None:
        item = self._items.get(name)
        if name not in self._items or (item is not None and not shiboken6.isValid(item)):
            item = self._items[name] = _item(self.win, name)  # found once: Windows asks on every mouse move
        if item is None:
            return None
        p, k = item.mapToScene(QPointF(0, 0)), self.win.devicePixelRatio()
        return ht.Rect(p.x() * k, p.y() * k, item.width() * k, item.height() * k)

    def _frame(self) -> int:
        dpi = self.user32.GetDpiForWindow(self.hwnd) or 96
        return self.user32.GetSystemMetricsForDpi(32, dpi) + self.user32.GetSystemMetricsForDpi(92, dpi)  # + padded

    def _hit(self, sx: int, sy: int) -> int:
        pt = wintypes.POINT(sx, sy)
        self.user32.ScreenToClient(self.hwnd, ctypes.byref(pt))
        rc = wintypes.RECT()
        self.user32.GetClientRect(self.hwnd, ctypes.byref(rc))
        row = self._rect("chromeRow")
        if row is None:
            return ht.HTCLIENT
        buttons = {code: r for code, n in _NAMES.items() if (r := self._rect("chrome" + n.capitalize()))}
        holes = [r for r in (self._rect("chromeMenus"),) if r]
        return ht.hit_test(
            pt.x, pt.y, (rc.right, rc.bottom), border=self._frame(), caption_h=row.h, buttons=buttons, holes=holes,
            maximized=bool(self.user32.IsZoomed(self.hwnd)),
        )  # fmt: skip

    def _show(self, hot: str = "") -> None:
        self.win.setProperty("chromeHot", hot)
        self.win.setProperty("chromeDown", self.down)

    def nativeEventFilter(self, eventType, message):
        if eventType != b"windows_generic_MSG":
            return False, 0
        msg = wintypes.MSG.from_address(int(message))
        if msg.hWnd != self.hwnd or msg.message not in _HANDLED:
            return False, 0
        m, code = msg.message, int(msg.wParam)
        if m == WM_NCCALCSIZE:
            if msg.wParam and self.user32.IsZoomed(self.hwnd):
                rect = ctypes.cast(msg.lParam, ctypes.POINTER(wintypes.RECT)).contents  # rgrc[0]
                f = self._frame()  # a maximised window overhangs the screen by the frame: pull it back in
                rect.left += f
                rect.right -= f
                rect.top += f
                rect.bottom -= f
            return True, 0
        if m == WM_NCHITTEST:
            x, y = msg.lParam & 0xFFFF, (msg.lParam >> 16) & 0xFFFF
            x, y = x - 0x10000 if x & 0x8000 else x, y - 0x10000 if y & 0x8000 else y  # signed: monitors left/above
            return True, self._hit(x, y)
        if m == WM_NCMOUSEMOVE:
            if code in _NAMES:
                self._show(_NAMES[code])
                track = _TrackMouse(ctypes.sizeof(_TrackMouse), 0x2 | 0x10, self.hwnd, 0)  # TME_LEAVE | TME_NONCLIENT
                self.user32.TrackMouseEvent(ctypes.byref(track))
            else:
                self._show()
            return False, 0
        if m == WM_NCMOUSELEAVE:
            self.down = ""
            self._show()
            return False, 0
        if code not in _NAMES:
            return False, 0
        if m == WM_NCLBUTTONDOWN:
            self.down = _NAMES[code]
            self._show(self.down)
            return True, 0  # swallowed: Windows would otherwise draw and track its own caption button
        pressed, self.down = self.down, ""
        self._show(_NAMES[code])
        if pressed == _NAMES[code]:
            maxed = bool(self.user32.IsZoomed(self.hwnd))
            sc = {"min": SC_MINIMIZE, "max": SC_RESTORE if maxed else SC_MAXIMIZE, "close": SC_CLOSE}[pressed]
            self.user32.PostMessageW(self.hwnd, WM_SYSCOMMAND, sc, 0)
        return True, 0
