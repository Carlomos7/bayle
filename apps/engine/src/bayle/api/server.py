"""`bayle --backend`: bind 127.0.0.1:0, print one JSON handshake line when ready, stop when stdin reaches EOF. It
serves the engine's feature interfaces (services.features) on the engine's jobs and activity log, as the window
uses them (runtime.bootstrap)."""

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
from bayle.services import features


async def serve(engine) -> None:
    services = features.build(engine.jobs, engine.activity, lambda: engine.locations).services()
    # BAYLE_API_TOKEN missing -> raises before anything is printed
    app = create_app(jobs=engine.jobs, services=services)
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
        port = sock.getsockname()[1]
        print(json.dumps({"port": port, "version": __version__, "contract": CONTRACT_VERSION}), flush=True)
    await serving


def main(engine) -> int:
    """engine: runtime.bootstrap.create_engine(storage=False)."""
    asyncio.run(serve(engine))
    return 0
