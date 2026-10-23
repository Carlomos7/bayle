"""The window program's entry: the engine's command line (bayle.cli) with the Qt window, message box and self-test
injected. Each hook imports its Qt code only when called, so --worker, --update and the other headless modes never
load Qt."""

from __future__ import annotations

import sys
from pathlib import Path

from bayle.cli import WindowHooks
from bayle.cli import main as cli_main


def _shell_main(engine) -> int:
    from bayle.ui.launcher.window import main

    return main(engine)


def _ask(*args) -> int:
    from bayle.ui import message_box

    return message_box.ask(*args)


def _self_test(data: Path, out) -> int:
    from bayle.ui import self_test

    return self_test.run(data, out)


HOOKS = WindowHooks(shell_main=_shell_main, ask=_ask, self_test=_self_test)


def main() -> int:
    return cli_main(sys.argv, HOOKS)
