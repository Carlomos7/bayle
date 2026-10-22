"""`python -m bayle`. The frozen build starts from scripts/entry.py, the same two lines (it says why)."""

import sys

from bayle.entry import main

sys.exit(main())
