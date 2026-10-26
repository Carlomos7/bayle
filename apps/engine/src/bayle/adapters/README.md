# adapters

The engine's concrete infrastructure. Adapters implement the features' ports (`modules/ports.py`,
`modules/*/ports.py`) and use the features' models and value types; they never call a feature's workflow, the runtime or
the API. `lint-imports` enforces this, and that the areas below never import each other in a cycle.

| Area | What it holds |
| --- | --- |
| `formats/` | The file formats, read and written byte for byte: DCX, BND4, PARAM, FMG, ESD, TAE, HKS, regulation.bin, me3 profiles (`me3_profile.py` reads entries, `me3_text.py` edits the text in place) and editable config files (`config_model.py`). Pure: no files, no state. |
| `filesystem/` | The primitives every save, profile and record write goes through: `files.py` (atomic and durable writes, settled reads, merging one folder into another), `filelock.py` (the lock around read-change-write of the settings file), `trash.py` (the Recycle Bin), `hashing.py` and `tree_hash.py` (file and folder hashes, remembered by size and time), `build.py` (journaled build and operation folders, recovered at the next start) and `data_folder.py` (the launcher's own data folder: its root, bound at startup, the temp folder installs unpack into, the deleted-profiles folder). |
| `persistence/` | The launcher's SQLite database through SQLAlchemy, with its Alembic migrations (`migrations/`, shipped as files and run in code at startup) and data migrations; the record index (`mirror.py`) and `settings_file.py` (the settings file, read and written under its lock). |
| `games/` | The game on this machine: finding it, its saves and me3 (`discovery.py`, `paths.py`, `steam_paths.py`, `me3_paths.py`; Steam libraries, the Proton prefix, XDG paths), playing it (`session.py`: Steam started and signed in, the launch through me3, waiting for the exit, leftover shells cleared), its packed archives (`archives.py`), its Oodle library (`oodle.py`), its executable's version (`exe.py`) and what the launcher knows about how it reads what it is given (`knowledge.py`). |
| `saves/` | Save file formats: the BND4 container, the Elden Ring PC layout, Nightreign's encryption and checksums, and names for items the game does not define. The repairs that write saves are `modules/saves`. |
| `merging/` | Merging several mods' changes to one file: the merger and its rule per format, and what a build was made from. |
| `overhauls/` | Building overhauls: their configs read and written (`recipes.py`, `writer.py`), the basic engine (`basic.py`), script hooks, the Lua and HKS checks, the recipe engine (`engine.py`) and the tool backends that run other programs (`backends/`). |
| `archives/` | Unpacking `.zip`, `.7z` and `.rar` downloads (or using a folder where it is) into a staging folder. |
| `integrations/` | Steam and me3 as programs: whether Steam runs and is signed in, its shortcuts (`steam_shortcuts.py`, read and written byte for byte, only while Steam is closed, with a backup), me3's version, info and latest release. |
| `system/` | This machine: processes under a name (`proc.py`; Wine and Proton processes matched by their exe), dead game shells (`processes.py`, Windows only; also `scripts/clear_dead_shells.py`), the desktop's open handler, the install's facts (`app_paths.py`, `identity.py`), the run and job logs and the jobs index (`logging.py`) and the UI-thread guard (`threads.py`). |

Nothing here writes to disk except through `filesystem/`, the database, and the run log and lock files. A real game
instance uses gigabytes; anything under 100 MB with that image name is a leftover shell, not the game.
