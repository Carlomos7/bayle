"""Repair Elden Ring PC saves whose regulation block was overwritten (bayle.modules.saves.regulation says how). Its job log
goes to the launcher's data folder like any other job's.

    uv run python scripts/repair_regulation.py [<save> ...] [--regulation <file>] [--force] [--dry-run] [-o OUT]
"""

from __future__ import annotations

from bayle.modules.saves import regulation
from bayle.runtime.bootstrap import use_data_folder

if __name__ == "__main__":
    use_data_folder()
    regulation.main()
