"""The frozen engine's entry point (build_engine.py): the engine's command line, as `bayle-engine` runs it."""

import sys

from bayle.cli import main

sys.exit(main())
