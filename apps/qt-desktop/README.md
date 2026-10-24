# Bayle desktop

Bayle Modding Suite's desktop program: the Qt Quick window (`bayle_qt`), its controller (`bayle_qt.shell`) and the updater (`bayle_qt.updater`), on the engine in `../engine` (an editable path dependency).

- `uv sync` then `uv run python -m bayle_qt` opens the window.
- Tests: `$env:QT_QPA_PLATFORM="offscreen"; uv run pytest`.
- Build: `uv run python scripts/build.py` (see that file).
