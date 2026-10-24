# Bayle engine

The engine of Bayle Modding Suite: mods, profiles, saves, merging and the game's files as typed Python interfaces (`bayle.services.features`), the work runner, persistence and a thin HTTP API (`bayle.api`). No Qt.

- `uv sync` then `uv run pytest` (Windows: `$env:QT_QPA_PLATFORM` is not needed here).
- `uv run python -m bayle --backend|--worker|--play|--check|--check-storage`: the headless modes.

The desktop program is `../qt-desktop`.
