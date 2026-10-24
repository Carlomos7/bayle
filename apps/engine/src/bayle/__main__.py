"""`python -m bayle`: the engine's command line without a window (--worker, --backend, --play, --check,
--check-storage). The desktop app is `python -m bayle_qt`."""

import sys

from bayle.cli import main

sys.exit(main())
