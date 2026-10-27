"""`bayle --backend`: bind 127.0.0.1:0, print one JSON handshake line when ready, stop when stdin reaches EOF. It
serves the engine's feature interfaces (runtime.features) on the engine's jobs and activity log, as the window
uses them (runtime.bootstrap).

It holds the data folder's window name (runtime.instance.WINDOW) while it runs, so the Qt window and a front end on
this backend never use the same data folder at once. Exit codes before any handshake: 2 when the BAYLE_API_*
settings are invalid (the token is missing or under 16 characters), 3 when that data folder is already in use; a
line on stderr says which."""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import threading

import uvicorn
from pydantic import ValidationError

from bayle import __version__
from bayle.api.app import create_app
from bayle.api.models import CONTRACT_VERSION
from bayle.api.settings import ApiSettings
from bayle.runtime import features, instance


async def serve(engine, settings: ApiSettings) -> None:
    services = features.build(engine.jobs, engine.activity, lambda: engine.locations).services()
    app = create_app(settings, jobs=engine.jobs, services=services)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]  # now: a server that stops at once (stdin already closed) has closed the socket
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=2))
    loop = asyncio.get_running_loop()

    def watch_stdin() -> None:
        sys.stdin.buffer.read()  # returns when the parent closes the pipe or dies
        loop.call_soon_threadsafe(setattr, server, "should_exit", True)

    threading.Thread(target=watch_stdin, daemon=True).start()
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started and not serving.done():  # lifespan runs before the socket accepts; wait for started
        await asyncio.sleep(0.02)
    if server.started and not server.should_exit:  # a parent that already left gets no handshake
        print(json.dumps({"port": port, "version": __version__, "contract": CONTRACT_VERSION}), flush=True)
    await serving


def main(engine) -> int:
    """engine: runtime.bootstrap.create_engine(storage=False)."""
    try:
        settings = ApiSettings()  # type: ignore[call-arg]  # the token comes from BAYLE_API_TOKEN
    except ValidationError as e:
        for err in e.errors():
            name = "BAYLE_API_" + "_".join(str(part) for part in err["loc"]).upper()
            print(f"bayle --backend: {name}: {err['msg']}", file=sys.stderr)
        return 2
    hold = instance.acquire(instance.WINDOW)
    if hold is None:
        print("bayle --backend: this data folder is in use by another Bayle window; close it first", file=sys.stderr)
        return 3
    try:
        asyncio.run(serve(engine, settings))
    finally:
        hold.release()
    return 0
