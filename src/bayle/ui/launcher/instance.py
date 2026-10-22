"""One launcher at a time: the shell holds the window's name (platform/instance) and answers second starts over a
local socket: `show` brings the window forward, `play <game> [allow-without-backup]` (a Steam shortcut's --play while
the window is open) launches in this window. Only this user can connect."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer

from bayle.platform import instance


class InstanceServer(QObject):
    showRequested = Signal()
    playRequested = Signal(str)  # "<game key>" or "<game key> allow-without-backup"

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._hold: instance.Hold | None = None
        self._server: QLocalServer | None = None

    def take(self, hold: instance.Hold | None = None) -> None:
        """Hold the window's name (already held: hold) and answer second starts."""
        self._hold = hold or self._hold or instance.acquire(instance.WINDOW)
        if self._server is not None:
            return
        name = instance.server_name()
        QLocalServer.removeServer(name)  # only a crashed window's leftover (Linux): we hold the name, none is live
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        server.newConnection.connect(self._connected)
        if server.listen(name):
            self._server = server
        else:
            server.deleteLater()

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
            self._server = None
        if self._hold is not None:
            self._hold.release()
            self._hold = None

    def _connected(self) -> None:
        server = self._server
        while server is not None and (sock := server.nextPendingConnection()) is not None:
            buf = bytearray()

            def read(s=sock, b=buf):
                b.extend(bytes(s.readAll().data()))
                while b"\n" in b:
                    line, _, rest = bytes(b).partition(b"\n")
                    b[:] = rest
                    self.handle(line.decode("utf-8", "replace").strip())

            sock.readyRead.connect(read)
            sock.disconnected.connect(sock.deleteLater)
            if sock.bytesAvailable():
                read()

    def handle(self, message: str) -> None:
        word, _, arg = message.partition(" ")
        if word == "show":
            self.showRequested.emit()
        elif word == "play":
            self.showRequested.emit()
            self.playRequested.emit(arg)
