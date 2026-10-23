"""Repair Elden Ring PC saves whose regulation block was overwritten (bayle.saves.regulation says how). Its job log
goes to the launcher's data folder like any other job's.

    uv run python scripts/repair_regulation.py [<save> ...] [--regulation <file>] [--force] [--dry-run] [-o OUT]
"""

from __future__ import annotations

from bayle.app import use_data_folder
from bayle.saves import regulation

if __name__ == "__main__":
    use_data_folder()
    regulation.main()
