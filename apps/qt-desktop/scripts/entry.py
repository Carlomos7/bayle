"""PyInstaller entry point: the same two lines as bayle_qt/__main__.py, kept as a file outside the package.

PyInstaller is given a script file to freeze. Handing it the package's own __main__.py would freeze that file as the
program's __main__ module and collect the package around it as a side effect; a script outside the package imports
bayle_qt like any caller, so the frozen program and `python -m bayle_qt` start the same way. The
console script (pyproject.toml's [project.scripts]) does not exist inside a frozen exe, hence a file.
"""

import sys

from bayle_qt.entry import main

sys.exit(main())
