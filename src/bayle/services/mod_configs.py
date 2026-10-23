"""Mod Configs (technical specification §8.10): which of a profile's mods have settings files, reading and saving them
as a form or as text, attaching a file to a mod, and Seamless Co-op's own panel (password, difficulty, language, and
sharing the settings with a friend). Facts and actions only: the words are the Mod Configs presenter's.

Every write goes through mods.configs.write with the fingerprint read with the file, so a file changed on disk in
the meantime (the Co-op page, the mod itself, an editor) is never overwritten; only the edited values' characters
change (formats.config_model). Saving while the game runs is allowed: the mods read their files at launch (owner,
E1 A)."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, get_args

from bayle.coop import ini as coop_ini
from bayle.coop import scaling as coop_scaling
from bayle.coop import share as coop_share
from bayle.errors import Cancelled, OperationError
from bayle.formats import config_model
from bayle.mods import configs, profile_edit
from bayle.platform.threads import assert_not_ui_thread
from bayle.services.mods import overhaul_setup_of, profile_entries
from bayle.work.jobs import JobManager
from bayle.work.runner import run_job_result, run_logged

if TYPE_CHECKING:
    from bayle.config.settings import LauncherSettings
    from bayle.game.locate import Locations

SEAMLESS = "seamless"
README = "readme"  # a mod's README: shown as formatted text, Edit as text opens it in the editor
OVERHAUL = (
    "overhaul"  # the node of the profile's overhaul setup; its first file is the setup itself (how == "overhaul")
)


def stamp(path: Path) -> tuple[int, int] | None:
    """Modification time and size: what tells that a file changed under the page (None when it is gone)."""
    try:
        st = Path(path).stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def logged[T](title: str, loc: Locations, work: Callable[[], T]) -> T:
    """work() as a logged job of its own (log file, jobs-index record, Undo record), on this worker thread. Raises
    OperationError when it failed (a plain failure is code "failed"), Cancelled when it was stopped."""

    def job(_launch, loc: Locations) -> T:
        with run_logged(title, loc.game.key):
            return work()

    done = run_job_result(job, None, loc, title)
    if done.state == "done":
        return done.result
    if done.state == "cancelled":
        raise Cancelled()
    raise OperationError.from_info(done.error)


@dataclass(frozen=True)
class ConfigFile:
    path: Path
    how: str  # found (beside the mod) | attached | seamless | overhaul (the overhaul's setup itself)
    exists: bool
    kind: str  # seamless | form | markdown | text


@dataclass(frozen=True)
class ModNode:
    """One mod with settings files. key: stable across reads (seamless, or kind:path); target: what a file is attached
    to (a DLL, or a package's folder); loaded: Seamless only: the profile loads it."""

    key: str
    name: str
    kind: str  # seamless | overhaul | native | package
    enabled: bool
    loaded: bool
    target: Path | None
    files: tuple[ConfigFile, ...] = ()
    setup: dict | None = None  # overhaul only: services.mods.overhaul_setup_of


def _kind(path: Path, seamless_ini: str | None) -> str:
    if seamless_ini and path.name.lower() == seamless_ini.lower():
        return SEAMLESS
    if config_model.lang_of(path.name):
        return "form"
    if configs.README_NAME.match(path.stem) and path.suffix.lower() in configs.README_SUFFIXES:
        return README
    return "markdown" if path.suffix.lower() == ".md" else "text"


def tree(profile, *, loc: Locations, settings: LauncherSettings) -> list[ModNode]:
    """The profile's mods with settings files, Seamless Co-op first (also when the profile doesn't load it, so the
    page can say how to), then DLLs and packages in the profile's order."""
    assert_not_ui_thread("mod_configs.tree")
    prof = Path(profile)
    game = loc.game
    entries = profile_entries(prof)
    out: list[ModNode] = []
    ini = coop_ini.coop_ini_for(str(prof), game) if game.coop_ini else None
    skip = {configs.key_for(ini)} if ini else set()
    if game.coop_dll and game.coop_ini:
        entry = next(
            (e for e in entries if e["kind"] == "native" and Path(e["path"]).name.lower() == game.coop_dll), None
        )
        files = (ConfigFile(ini, SEAMLESS, True, SEAMLESS),) if ini else ()
        out.append(
            ModNode(SEAMLESS, game.coop_dll, SEAMLESS, bool(entry and entry["enabled"]), ini is not None, None, files)
        )
    node = _overhaul_node(prof, loc)
    if node is not None:
        out.append(node)
    for e in entries:
        if not e.get("path") or (
            e["kind"] == "native" and game.coop_dll and Path(e["path"]).name.lower() == game.coop_dll
        ):
            continue
        where = profile_edit.resolve(prof, e["path"])
        if e["kind"] == "native":
            found = configs.files_for(settings, where, skip=skip)
        else:
            found = _package_files(settings, where)
        found = [*found, *({"path": r, "how": "found", "exists": True} for r in _readmes_of(e["kind"], where))]
        if not found:
            continue
        files = tuple(
            ConfigFile(
                Path(f["path"]),
                "attached" if f["how"] == "tied" else "found",
                f["exists"],
                _kind(Path(f["path"]), game.coop_ini),
            )
            for f in found
        )
        out.append(ModNode(f"{e['kind']}:{where}", e["name"], e["kind"], bool(e["enabled"]), True, where, files))
    return out


def _overhaul_node(profile: Path, loc: Locations) -> ModNode | None:
    """The profile's overhaul setup, when it has one: the setup itself, then the settings files its builds keep for
    the player (in the library's overhauls/<id>/)."""
    from bayle.mods import library

    try:
        setup = overhaul_setup_of(profile, loc=loc)
    except Exception:  # a config or record that does not read: no node
        return None
    if setup is None or setup["path"] is None:
        return None
    config = setup["config"]
    files = [ConfigFile(Path(setup["path"]), "overhaul", True, OVERHAUL)]
    lib = library.ProfileFolder.of(profile)
    kept = [s.to for b in config.builds for s in b.steps if s.do == "config"]
    for name in dict.fromkeys(kept):
        f = lib.overhaul(config.id) / name
        if f.is_file():
            files.append(ConfigFile(f, "found", True, _kind(f, loc.game.coop_ini)))
    return ModNode(OVERHAUL, config.label, OVERHAUL, True, True, None, tuple(files), setup)


def _readmes_of(kind: str, where: Path) -> list[Path]:
    if kind != "native":
        return configs.readmes(where)
    shared = sum(1 for k in where.parent.iterdir() if k.suffix.lower() == ".dll") > 1 if where.parent.is_dir() else True
    return configs.readmes(where.parent, shared)


def _package_files(settings: LauncherSettings, folder: Path) -> list[dict]:
    """A package's settings files: attached ones, and settings-looking files at the top of its folder."""
    out, seen = [], set()
    attached = configs.tied(settings, folder)
    top = sorted(k for k in folder.iterdir() if configs.looks_like_settings(k)) if folder.is_dir() else []
    for how, paths in (("tied", attached), ("found", top)):
        for p in paths:
            if configs.key_for(p) not in seen:
                seen.add(configs.key_for(p))
                out.append({"path": p, "how": how, "exists": p.is_file()})
    return out


def attach(settings: LauncherSettings, target: Path, file: Path) -> dict:
    """Attach file to the mod (settings.native_configs, never the .me3); returns the new value, saved."""
    from bayle.config.settings import save_settings

    ties = configs.with_tie(settings, target, file)
    save_settings(native_configs=ties)
    settings.native_configs = ties
    return ties


def detach(settings: LauncherSettings, target: Path, file: Path) -> dict:
    from bayle.config.settings import save_settings

    ties = configs.without_tie(settings, target, file)
    save_settings(native_configs=ties)
    settings.native_configs = ties
    return ties


# ----------------------------------------------------------------------------- one file
@dataclass
class Opened:
    """A file as read: its text (line breaks as \\n), how to write it back, its fingerprint, and the form when the
    file is one the form reads (doc is None for text and Markdown)."""

    path: Path
    text: str
    encoding: str
    crlf: bool
    sha: str
    doc: config_model.Document | None = None


def open_file(path: Path, form: bool = True) -> Opened:
    """Raises configs.ConfigError for a file too big or not text, OSError when it can't be read. form False: as text
    only (an overhaul config's TOML has tables of tables the form does not read)."""
    got = configs.read(Path(path))
    lang = config_model.lang_of(Path(path).name)
    doc = config_model.parse(got["text"], lang) if lang and form else None
    return Opened(Path(path), got["text"], got["encoding"], got["crlf"], got["sha"], doc)


def parse_doc(name: str, text: str) -> config_model.Document | None:
    """The form of a settings file's text (None for a file the form does not read)."""
    lang = config_model.lang_of(name)
    return config_model.parse(text, lang) if lang else None


def merged_text(opened: Opened, changes: dict[tuple[str | None, str], str]) -> str:
    """The file's text with these values ((section, key) -> value) changed, nothing else. Raises ValueError for a
    setting the file no longer has or only text can change."""
    doc = config_model.parse(opened.text, config_model.lang_of(opened.path.name) or config_model.INI)
    for (section, key), value in changes.items():
        if not doc.set(key, value, section):
            raise ValueError(f"{key} is no longer in {opened.path.name}")
    return doc.text()


def save_values(opened: Opened, changes: dict[tuple[str | None, str], str]) -> Path:
    """Write the changed values, nothing else; returns the .bak. Raises ConfigError when the file changed on disk
    since it was read, ValueError for a setting only text can change."""
    return configs.write(opened.path, merged_text(opened, changes), opened.encoding, opened.crlf, expect=opened.sha)


def save_text(opened: Opened, text: str) -> Path:
    return configs.write(opened.path, text, opened.encoding, opened.crlf, expect=opened.sha)


def reset_value(setting: config_model.Setting) -> tuple[str, str]:
    """(value, where it comes from: default | disk) for one setting's Reset."""
    if setting.default is not None:
        return setting.default, "default"
    return setting.value, "disk"


# ----------------------------------------------------------------------------- the Overhaul setup form
def file_rows(basic_config, folder, game: str) -> list[dict]:
    """The Files table: one row per file the setup takes, {file, kind, action (what happens now), choices (the
    actions it can have), target (the game path of a placed file)}, in path order. basic_config: an
    overhauls.config.Basic; folder: the mod's folder (the launcher's copy of its download)."""
    from bayle.game import catalog as games
    from bayle.game import config as game_config
    from bayle.overhauls import basic

    folders = set(game_config.load(game).mod_folders)
    regulation = games.BY_KEY[game].regulation.lower() if game in games.BY_KEY else games.REGULATION
    files = basic.files_of(folder)
    root = basic.package_root(files, folders, regulation)
    rows = []
    texts_from = {v.lower() for t in basic_config.texts for v in t.texts.values()}  # used for texts, not a step
    for f in files:
        if f.lower() in texts_from:
            continue
        kind = basic.file_kind(f, folders, regulation, root)
        act = basic.action_of(f, kind, basic_config)
        rows.append(
            {
                "file": f,
                "kind": kind,
                "action": "place" if act.startswith("place:") else act,
                "choices": list(basic.KINDS[kind]),
                "target": act[6:] if act.startswith("place:") else "",
            }
        )
    return rows


def overhaul_choices(setup: dict, game_dir=None) -> dict:
    """What the basic form offers: {natives: the DLLs as set, files: file_rows, texts: for each texts entry its
    file, table as set and the tables of the download's copy of the binder}. Empty lists without the mod's folder
    (the launcher's copy of its download). game_dir: the game's folder (a compressed copy is opened with its Oodle)."""
    from bayle.game import config as game_config
    from bayle.overhauls import basic

    config, folder = setup["config"], setup["folder"]
    b = config.basic
    if b is None or folder is None:
        return {"natives": [], "files": [], "texts": []}
    folders = set(game_config.load(config.game).mod_folders)
    texts = [
        {"file": t.file, "table": t.table, "tables": basic.text_tables(folder, t, folders, game_dir)} for t in b.texts
    ]
    return {
        "natives": [n.model_dump() for n in b.natives],
        "files": file_rows(b, folder, config.game),
        "texts": texts,
    }


def initial_values(choices: dict, config) -> dict[str, Any]:
    """The form's working values for a setup: the choices the mod's files give, as the config has them."""
    from bayle.overhauls import basic

    return {
        "natives": choices["natives"],
        "files": {r["file"]: basic.encode_action(r["action"], r["target"]) for r in choices["files"]},
        "tables": {t["file"]: t["table"] for t in choices["texts"]},
        "health": health_form(config),
    }


PatchKind = Literal["early", "after", "init", "file", "target", "table", "health"]


@dataclass(frozen=True)
class FormPatch:
    """One edit of the Overhaul setup form: kind (early | after | init: a DLL's option; file: a Files table
    action; target: the game path of a placed file; table: a texts entry's table; health: one of the log check's
    texts), name (the DLL, file or field it is about) and the new value (a bool as "true"/"false")."""

    kind: PatchKind
    name: str
    value: str

    @staticmethod
    def of(key: str, value: str) -> FormPatch | None:
        """The patch for the page's "kind:name" key; None for a kind the form does not have."""
        kind, _, name = key.partition(":")
        return FormPatch(kind, name, value) if kind in get_args(PatchKind) else None  # type: ignore[arg-type]


def patch_values(values: dict[str, Any], patch: FormPatch) -> bool:
    """Apply one edit to the form's working values (initial_values) in place; False when it names nothing there."""
    from bayle.overhauls import basic

    name, value = patch.name, patch.value
    native = next((n for n in values["natives"] if n["file"] == name), None)
    if patch.kind in ("early", "after", "init"):
        if native is None:
            return False
        if patch.kind == "early":
            native["load_early"] = value == "true"
        elif patch.kind == "after":
            native["after_others"] = value == "true"
        else:
            native["initializer"] = value.strip() or None
    elif patch.kind == "file":  # a choice of the Files table; placing keeps the path typed before
        target = basic.decode_action(values["files"].get(name, ""))[1]
        values["files"][name] = basic.encode_action(value, target)
    elif patch.kind == "table":
        values["tables"][name] = value
    elif patch.kind == "target":
        values["files"][name] = basic.encode_action("place", value.strip())
    elif patch.kind == "health":
        if name not in values["health"]:
            return False
        values["health"][name] = value
        values["health_touched"] = True
    return True


def files_to_store(rows: list[dict], values: dict[str, str]) -> dict[str, str] | None:
    """The Files table's choices that differ from what the setup does by itself: values maps a file to its action,
    a placed one as place:<game path>. None when there are no rows (the mod's folder is gone): nothing was shown, so
    nothing was chosen (with_basic then keeps the saved lists and files)."""
    if not rows:
        return None
    return {r["file"]: values[r["file"]] for r in rows if values.get(r["file"], r["choices"][0]) != r["choices"][0]}


def health_form(config) -> dict[str, str]:
    """The log check as the form's three texts (log file, failure text, started text); the first entry the config
    declares under [basic], else empty. Several failure patterns show as one "re:" alternation."""
    entries = config.basic.health if config.basic is not None else []
    if not entries:
        return {"log": "", "fail": "", "ok": ""}
    e = entries[0]
    fail = e.fail[0] if len(e.fail) == 1 else "|".join(e.fail)
    return {"log": e.log, "fail": _plain(fail, len(e.fail) == 1), "ok": _plain(e.ok or "", True)}


def _plain(pattern: str, single: bool) -> str:
    """A pattern as the form shows it: plain text when it is only escaped text, else "re:" and the pattern."""
    plain = re.sub(r"\\(.)", r"\1", pattern)
    return plain if single and re.escape(plain) == pattern else f"re:{pattern}"


def _pattern(text: str) -> str:
    text = text.strip()
    return text[3:] if text.startswith("re:") else re.escape(text)


def health_of_form(form: dict[str, str]) -> list:
    """The Health entries the form's texts describe (none while the log file or the failure text is empty). Raises
    ValueError when "re:" text is not a regular expression."""
    from bayle.overhauls.config import Health

    log, fail, ok = form["log"].strip(), form["fail"].strip(), form["ok"].strip()
    if not log or not fail:
        return []
    return [Health(log=log, fail=[_pattern(fail)], ok=_pattern(ok) if ok else None)]


def with_basic(
    config,
    *,
    natives: list[dict],
    files: dict[str, str] | None,
    tables: dict[str, str] | None = None,
    health: list | None = None,
):
    """The config with the form's values (overhauls.config.Basic) in place of its basic part. The Files table
    replaces the older keep, not_merged, place and skip lists, which are folded into it; files None (no table was
    shown) keeps them and the saved files as they are."""
    from bayle.overhauls.config import Basic, BasicNative

    old = config.basic
    texts = [t.model_copy(update={"table": (tables or {}).get(t.file) or t.table}) for t in old.texts] if old else []
    for t in texts:
        if not t.table:
            raise ValueError(f"Choose the table of {t.file.replace('{each}', '<language>')} that the texts are set in.")
    if files is None and old is not None:
        keep = {"natives": [BasicNative(**n) for n in natives], "texts": texts}
        if health is not None:
            keep["health"] = health
        return config.model_copy(update={"basic": old.model_copy(update=keep)})
    new = Basic(
        version=old.version if old is not None else None,
        natives=[BasicNative(**n) for n in natives],
        files=files or {},
        texts=texts,
        health=(old.health if old is not None else []) if health is None else health,
    )
    return config.model_copy(update={"basic": new})


def step_lines(config) -> list[str]:
    """What the config's builds do, one plain line per step (the advanced level shows them read-only)."""
    words = {
        "copy_tree": "Copy the folder",
        "copy": "Copy",
        "config": "Keep your copy of",
        "params": "Combine the parameters in",
        "merge": "Merge",
        "text": "Add the texts to",
        "hook": "Add a script fragment to",
        "remove": "Leave out",
    }
    out = []
    for b in config.builds:
        for s in b.steps:
            d = s.model_dump(by_alias=True, exclude_unset=True)
            what = d.get("file") or d.get("from") or d.get("glob") or d.get("folder") or ""
            out.append(f"{words.get(s.do, s.do)} {what}".strip())
    return out


def parse_overhaul_text(text: str):
    """The config a TOML text describes. Raises ValueError (the text or the model says what is wrong)."""
    import tomllib

    from bayle.overhauls.config import OverhaulConfig

    return OverhaulConfig.model_validate(tomllib.loads(text))


def mods_to_set_up(profile) -> list[dict]:
    """The profile's mods an overhaul setup can be made for: {name, id, folder} (a package's folder, or the folder
    of a DLL), in profile order."""
    prof = Path(profile)
    out = []
    for e in profile_entries(prof):
        if not e.get("path"):
            continue
        where = profile_edit.resolve(prof, e["path"])
        folder = where if e["kind"] == "package" else where.parent
        if folder.is_dir():
            out.append({"name": e["name"], "id": e["id"] or "", "folder": folder})
    return out


# ----------------------------------------------------------------------------- Seamless Co-op
@dataclass(frozen=True)
class Seamless:
    ini: Path
    password: str | None  # None: the file has no password (Nightreign's)
    spec: coop_scaling.ScalingSpec | None
    scaling: tuple[int, ...] | None
    preset: str
    languages: tuple[str, ...]  # "" (the game's language) and each translation in its locale folder
    language: str
    settings: list = field(default_factory=list)  # the other sections, as coop_ini.read_settings_meta gives them


LANGUAGE_KEY = "mod_language_override"


def seamless(ini: Path) -> Seamless:
    ini = Path(ini)
    spec = coop_scaling.scaling_spec(ini)
    values = coop_scaling.read_scaling(ini, spec) if spec else None
    locale = ini.parent / "locale"
    langs = sorted(p.stem for p in locale.glob("*.json")) if locale.is_dir() else []
    current = coop_ini.read_keys(ini, [LANGUAGE_KEY]).get(LANGUAGE_KEY, "").strip()
    if current and current not in langs:
        langs.append(current)  # a value the folder doesn't have stays choosable as it is
    return Seamless(
        ini,
        coop_ini.read_password(ini) if coop_ini.has_password(ini) else None,
        spec,
        values,
        coop_scaling.preset_of(values, spec) if values else coop_scaling.CUSTOM,
        ("", *langs),
        current,
        [s for s in coop_ini.read_settings_meta(ini) if s["section"].upper() not in ("PASSWORD", "SCALING")],
    )


def save_seamless(ini: Path, values: dict[str, str]) -> list[str]:
    """Write these keys (the password, the difficulty values, any setting) in place; returns the keys the file does
    not have (nothing is appended). An empty password is refused (OperationError, code password_empty)."""
    if "cooppassword" in values and not str(values["cooppassword"]).strip():
        raise OperationError("password_empty", "The Seamless Co-op password cannot be empty.")
    return coop_ini.write_keys(Path(ini), values)


def share_text(ini: Path) -> str:
    """Every setting as ini lines, comments left out, the password included (a friend needs it to join; owner,
    E3 A): what Copy settings and Save settings give."""
    out = []
    for section, values in coop_share.read_all_settings(Path(ini)).items():
        if section:
            out.append(f"[{section}]")
        out.extend(f"{k} = {v}" for k, v in values.items())
        out.append("")
    return "\n".join(out).rstrip() + "\n"


_LINE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$")


def parse_share(text: str) -> dict[str, str]:
    """{key: value} from shared settings: ini lines, or the JSON export older launchers wrote (read for one release,
    coordinator 2026-10-14). Raises ValueError when the text holds no settings."""
    if text.lstrip().startswith(("{", "//")):
        return coop_share.parse_settings_json(text)
    out = {}
    for line in text.splitlines():
        if line.strip().startswith((";", "#", "[")):
            continue
        m = _LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    if not out:
        raise ValueError("no settings in that text")
    return out


def plan_merge(
    opened: Opened, incoming: dict[tuple[str | None, str], str]
) -> tuple[dict[tuple[str, str], tuple[str, str]], list[str]]:
    """Shared values ({(section or None, key): value}) against the file as read: (changes {(section, key): (yours,
    theirs)}, keys left out because the file lacks them or the form can't change them). Nothing is written and
    keys are never added. Seamless Paste and profile import both go through here."""
    doc = opened.doc or config_model.parse(opened.text, config_model.lang_of(opened.path.name) or config_model.INI)
    changes: dict[tuple[str, str], tuple[str, str]] = {}
    left_out: list[str] = []
    for (section, key), value in incoming.items():
        item = doc.find(key, section)
        if item is None or item.readonly:
            left_out.append(key)
        elif item.value != str(value):
            changes[(item.section, item.key)] = (item.value, str(value))
    return changes, left_out


def plan_paste(ini: Path, text: str):
    """(changes {key: (yours, theirs)}, keys your file doesn't have, the file as read) for shared settings; nothing
    written. Hand the file to apply_paste."""
    opened = open_file(ini)
    changes, left_out = plan_merge(opened, {(None, k): v for k, v in parse_share(text).items()})
    return {key: pair for (_s, key), pair in changes.items()}, sorted(left_out), opened


def apply_paste(opened: Opened, changes: dict[str, tuple[str, str]]) -> Path:
    if "cooppassword" in changes and not changes["cooppassword"][1].strip():
        raise OperationError("password_empty", "The Seamless Co-op password cannot be empty.")
    return save_values(opened, {(None, k): new for k, (_old, new) in changes.items()})


class ModConfigsService:
    """The Mod configs page for one engine: jobs is its JobManager, locations the current game's Locations (None: no game
    selected). Returns data and OperationError codes, never wording: the Qt page words them."""

    def __init__(self, jobs: JobManager, locations: Callable[[], Locations | None]) -> None:
        self._jobs, self._locations = jobs, locations
