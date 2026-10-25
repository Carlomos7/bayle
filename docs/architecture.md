# Architecture

Bayle is two Python applications in one repository, each its own uv project:

- `apps/engine` (distribution `bayle-engine`, import `bayle`): every feature, its rules and its infrastructure, the
  job runner and a local HTTP API. No Qt.
- `apps/qt-desktop` (distribution `bayle-qt`, import `bayle_qt`): the Qt Quick window, its presenters (all the
  wording, through `bayle_qt.text.tr`), the desktop controller (`bayle_qt.shell`), the updater and the build. It uses
  the engine directly, as an editable path dependency, never through HTTP.

## The engine

A feature-first modular monolith with ports and adapters:

```text
bayle/
├── modules/     the features: their models, rules and workflows
│   ├── activity, coop, games, launch, mods, overhauls, saves, settings
│   └── ports.py         the ports more than one feature needs
├── adapters/    concrete infrastructure (adapters/README.md)
├── work/        jobs, events, progress, cancellation, the CPU worker pool
├── api/         FastAPI routers over the features' typed interfaces
├── runtime/     composition: create_engine, bind_ports, startup, the instance guard
└── resources/   shipped read-only files: game definitions, schemas, item lists
```

Each feature exposes a typed interface (`modules/<feature>/service.py` or `*_page.py`, composed once in
`runtime/features.py`). The window and the HTTP routers call the same interfaces; work runs on one `JobManager`.

### The rules, and what enforces them

`uv run lint-imports` (apps/engine/pyproject.toml) checks every rule below on each CI run.

1. **The engine has no Qt and knows no app.** `PySide6`, `bayle_qt` and `velopack` are never imported, and the engine's
   environment does not install PySide6 (`tests/unit/test_engine_has_no_qt.py`, `scripts/ci/headless-smoke.py`).
2. **Adapters use the features' models and ports, never their workflows.** An adapter may import a feature's `ports`
   and `models`, and the value types named in the contract (the game catalog and config, `Locations`, the overhaul
   recipe models, the game folder pattern, the overhaul manifest names). It never imports a workflow, the runtime or
   the API.
3. **Features reach stateful infrastructure only through ports.** The database, the settings file, the data folder,
   the install's facts, other programs (me3, Steam, the desktop), finding the game on this machine and the tool
   backends are reached through Protocol ports that the runtime binds:
   - `modules/ports.py`: the data folder, the settings file, the install's facts, me3, Steam, the desktop and the
     database's record index;
   - `modules/games/ports.py`: finding the game, its saves and me3 on this machine;
   - `modules/mods/ports.py`: the tool backends and the recipe engine (and their contract: `Tool`, `Recipe`,
     `EngineHost`).

   `runtime.bootstrap.bind_ports()` binds the program and machine ports once per process. Each port function reads
   its slot when called, so a test that replaces a function of the bound adapter is seen, and a call before
   `bind_ports()` raises. The record index is bound per engine (it is off when storage is), like the other engine
   slots in `runtime.bootstrap._SLOTS`.

   **Called directly, as documented exceptions:** file formats (`adapters/formats`), the game's and saves' own file
   formats, merging, the filesystem primitives every save and profile write goes through (`adapters/filesystem`: the
   verified durable write is the integrity rule itself, and a port in front of it would hide nothing), the job log
   (`adapters/system/logging`) and the UI-thread guard (`adapters/system/threads`).
4. **The features are layered**, top to bottom: activity; the Settings page (`settings.service`, `settings.locations`);
   launch; saves; mods; coop; games; overhauls; the game folder pattern (`settings.layout`); the shared ports; the
   settings model (`settings.models`). The settings package spans both ends because its page composes other features
   while every feature reads its model.

   **Known coupling** (listed in the contract, so a new back-edge fails): one feature's page offering another's
   action. Moving Seamless Co-op into a profile writes it through the mods profile writer; the Mods pages use the checks
   before Play and the setups Play offers; the Saves page's Undo runs through Activity's undo.
5. **`work/` is generic job infrastructure.** It imports no feature and no adapter except the job log.
6. **The API translates HTTP to the features.** Routers call the features' typed interfaces and import no adapter.
7. **The adapter areas form no cycles.**

### Inside the mods feature

Profiles, the load order, deployments (`operations.py`, `rebuild.py`) and their recovery stay in one feature,
`modules/mods`. They import each other inside functions; separate `profiles/` and `deployments/` packages would only
import each other in a cycle. `tests/unit/test_mods_import_ratchet.py` counts those function-level imports (20), and
the count may only go down.

## Where this differs from the original specification

The specification's tree (`modules/`, `adapters/`, `work/`, `api/`, `runtime/`, `resources/`) is the tree above, with
these deliberate differences:

- **mods, profiles and deployments are one feature** (above). Revisit when the ratchet's count is low enough to split
  without cycles.
- **Alembic's migrations ship inside the package** (`adapters/persistence/migrations`), not in `apps/engine/alembic/`:
  the packaged program runs them by path at startup, so they must be in the build.
- **Filenames were kept** where a file moved whole, so `git log --follow` and blame follow it. New names were given
  only where a file split or would have repeated its package (`services/mods.py` became `modules/mods/service.py`).
- **The settings feature is called `settings`**, the code's own word, not `preferences`.
- **Ports exist where infrastructure is stateful**, not for every dependency (rule 3).
- **`adapters/formats` is one package** of codecs (FromSoftware formats, me3 profiles, config files), not split into
  `fromsoft/` and `configs/`.

Records of earlier decisions are in [decisions](decisions).
