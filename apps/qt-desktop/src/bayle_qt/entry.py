"""The desktop program's entry: the engine's command line (bayle.cli) with the Qt window, message box, self-test and
the updater injected. Each hook imports its code only when called, so --worker, --update and the other headless
modes never load Qt."""

from __future__ import annotations

import sys
from pathlib import Path

from bayle.cli import WindowHooks
from bayle.cli import main as cli_main


def _shell_main(engine) -> int:
    from bayle_qt.launcher.window import main

    return main(engine)


def _ask(*args) -> int:
    from bayle_qt import message_box

    return message_box.ask(*args)


def _self_test(data: Path, out) -> int:
    from bayle_qt import self_test

    return self_test.run(data, out)


def _startup(argv: list[str]) -> int | None:
    """The updater's part of the start, where the engine's command line asks for it (data folder and logging set)."""
    if getattr(sys, "frozen", False):
        from bayle_qt.updater import apply as updates

        updates.velopack_startup()  # Velopack's install/update/uninstall hooks exit here
    if "--update" in argv:
        from bayle_qt.updater import headless

        return headless.update_headless([a for a in argv[1:] if a != "--update"])
    return None


def _ready(kind: str) -> None:
    from bayle_qt.updater import apply as updates

    updates.mark_ready(kind)


def _program() -> tuple[str, ...]:
    return (sys.executable,) if getattr(sys, "frozen", False) else (sys.executable, "-m", "bayle_qt")


HOOKS = WindowHooks(
    shell_main=_shell_main, ask=_ask, self_test=_self_test, startup=_startup, ready=_ready, program=_program()
)


def main() -> int:
    return cli_main(sys.argv, HOOKS)
