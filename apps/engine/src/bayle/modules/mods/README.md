# mods

me3 profiles (`.me3`, TOML, schema v1) and the mods they list.

| Module | Role |
| --- | --- |
| `profile.py` | Top-level profile settings (`savefile`, `start_online`, `disable_arxan`, `mem_patch`, ...), package rows, effective load order and the later-wins conflict scan. |
| `profile_edit.py` | Editing a profile: entries, per-mod options, profile create / delete (the text edits themselves are `adapters/formats/me3_text.py`). |
| `profile_writer.py` | The one writer every profile change goes through: read once, edited in memory, planned under the rules (plug-ins of one interface: unchanged since read, history copy and `.bak`, the mod that must stay last, shared dependencies, what me3 refuses, declared dependencies, paths), written once or as a step of an operation's journal. |
| `install.py` | What a download or folder contains, the install plan, copying a mod in and adding its entries, adding mods already on disk. |
| `checks.py` | What a profile's mod folders hold (the package tree, folders and DLLs no entry loads) and the entry problems me3 would refuse. |
| `remove.py` | Taking a mod's entry out of a profile, its folder optionally to the Recycle Bin, with what undo needs to put both back. |
| `naming.py` | The launcher's names for the folders it makes (`mod_id`: lowercase kebab-case ASCII without version tokens or Nexus suffixes), Windows-unsafe names, its reserved names, unique ids (`-2`, `-3`) and the one path-length limit (220 characters) the profile writer's Paths rule uses. |
| `library.py` | The launcher's own mod folder for one game, `rs-<game>` in me3's profiles folder: `ModLibrary` says where profiles, packages, natives, overhauls, their sources by role, per-profile builds and the hidden `.roundtable/` go, makes folders only when asked (`ensure`), and `scan()` lists what is there and which profiles use what (worked out from the profiles' entries, never stored). Per-profile launcher choices there go to `.roundtable/settings.json`, not to the `roundtable.json` that `profile_settings.py` keeps beside today's profiles. Installs don't use it yet (3.21). |
| `records.py` | The library's records as versioned Pydantic models (`OverhaulRecord`, `SourcesRecord`, `BuildRecord`, `SideEffectsRecord`): files that travel with their folder, unknown keys refused, older versions moved forward on read, schemas generated into `resources/schemas/library-*.schema.json`. |
| `models.py` | The install plan's shape, validated before the window sees it. |

## Rules

- A folder with game asset folders (`parts`, `chr`, `msg`, ...) or `regulation.bin` is a package; a folder with DLLs and no assets is a native; a `.me3` inside means a whole profile. Loose game files at an archive root are sorted into the folder the game serves them from.
- Profile edits are text-level so comments, order and line endings survive. New blocks go at the end, options rewrite only the keys inside one block, and inline-array profiles are converted to blocks first.
- Nothing writes a profile but `profile_writer.ProfileWriter` (the journal's byte restores in `operations.py` carry its check). A profile that changed on disk since it was read is never overwritten: the write is refused with "the profile changed outside the launcher; reload and try again".
- A mod already inside the profile folder is registered in place, never copied over itself. A path already listed is not added twice.

| `ports.py` | The tool backends' contract (`Tool`, `Recipe`, `EngineHost`) and the port the runtime binds to the concrete backends and the recipe engine (`adapters/overhauls`). |

The feature's typed interfaces, which the window and the HTTP routers call: `service.py` and `mods_page.py` (the Mods
page: rows, install plans, me3 facts, profile settings), `mod_install.py` (the install dialog, overhaul setups, Take
over, leftovers), `mod_configs.py`, `shared_mods_page.py` (the Library), `profile_mods.py`, `profile_rename_page.py`,
`profile_transfer.py` and `transfer_resources.py`. Unpacking downloads is `adapters/archives/extract.py`.

Profiles, the load order, deployments (`operations.py`, `rebuild.py`) and recovery stay in this one feature: they
import each other inside functions (`tests/unit/test_mods_import_ratchet.py` counts those imports, and the count may
only go down), so separate packages would only import each other in a cycle.
