"""`python -m bayle_qt`: the desktop program. The frozen build starts from scripts/entry.py, the same two lines."""

import sys

from bayle_qt.entry import main

sys.exit(main())
