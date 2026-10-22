"""`bayle --backend`: bind 127.0.0.1:0, print one JSON handshake line when ready, stop when stdin reaches EOF."""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import threading

import uvicorn

from bayle import __version__
from bayle.api.app import create_app
from bayle.api.models import CONTRACT_VERSION
from bayle.session.shell.service import Shell


async def serve(shell: Shell | None = None) -> None:
    """shell: the program's one Shell, built by the caller (the entry point owns the context); its Session is the API's."""
    app = create_app(
        session=shell.session if shell else None
    )  # BAYLE_API_TOKEN missing -> raises before anything is printed
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=2))
    loop = asyncio.get_running_loop()

    def watch_stdin() -> None:
        sys.stdin.buffer.read()  # returns when the parent closes the pipe or dies
        loop.call_soon_threadsafe(setattr, server, "should_exit", True)

    threading.Thread(target=watch_stdin, daemon=True).start()
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started and not serving.done():  # lifespan runs before the socket accepts; wait for started
        await asyncio.sleep(0.02)
    if server.started:
        if shell:
            shell.startup()  # the recoveries, the game watch, me3 and update checks, once
        port = sock.getsockname()[1]
        print(json.dumps({"port": port, "version": __version__, "contract": CONTRACT_VERSION}), flush=True)
    await serving
    if shell:
        shell.stop()


def main(shell: Shell | None = None) -> int:
    asyncio.run(serve(shell))
    return 0
