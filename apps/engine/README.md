# Bayle engine

The engine of Bayle Modding Suite: mods, profiles, saves, merging and the game's files as typed Python interfaces (`bayle.modules`, composed in `bayle.runtime.features`), the work runner, persistence and a thin HTTP API (`bayle.api`). No UI.

- `uv sync` then `uv run pytest`.
- `uv run python -m bayle --backend|--worker|--play|--check|--check-storage`: the headless modes.

The desktop app is `../desktop` (Tauri); it runs the frozen engine through its gateway.
