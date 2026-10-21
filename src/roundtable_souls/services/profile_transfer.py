"""Export / Import profile (technical specification, "Export / Import profile"): a profile's mods, options, order,
settings and the settings files of its mods, as a share list (one JSON file) or a full export (a zip that also holds
the mods), and the other way round: read a file someone sent, show what importing would change file by file, and
apply the ticked files as one undoable operation. Facts and actions only: the words are the page presenter's.

A share list goes into the current profile: its mods are matched to the player's (a package by id, else by folder
name; a DLL by file name), options and relative order are taken over for the matches, and a mod the player lacks is
listed and skipped. A full export is the S3g bundled-profile import with a manifest on top: the mods are copied in
and the profile is made (a new profile by default), then the manifest's settings and settings files are applied to
the copies. Everything the file says is untrusted (mods.profile_share): a settings file is only ever written inside
the folder of a mod the profile has, under a settings-looking name, and a save in a zip is never written.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import shutil
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from roundtable_souls.formats import config_model, me3_profile
from roundtable_souls.mods import configs, naming, operations, profile_edit, profile_import, profile_share, shared_mods
from roundtable_souls.mods import order as mod_order
from roundtable_souls.mods import profile as profile_tools
from roundtable_souls.mods.profile_edit import ModError
from roundtable_souls.mods.profile_writer import ProfileWriter
from roundtable_souls.platform import data_folder
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.platform.threads import assert_not_ui_thread
from roundtable_souls.services import mod_configs

if TYPE_CHECKING:
    from roundtable_souls.config.settings import LauncherSettings
    from roundtable_souls.game.locate import Locations

MAX_README = 256 * 1024
PROFILE_CARD = "profile"
# Formats that are already compressed or encrypted: deflating them costs minutes for almost no size gain.
STORED_SUFFIXES = frozenset(".dcx .bdt .dds .zip .7z .rar .png .jpg .jpeg .ogg .mp3 .mp4 .wem .bk2 .bik .fsb".split())
CHUNK = 4 * 1024 * 1024
# shortcut: the thresholds and speed are one set of constants; MB/s measured 2026-10-20 (see exportux/critique.md)
LARGE_MOD = 1024**3  # a mod this big is marked in the checklist
LARGE_EXPORT = 2 * 1024**3  # an export this big warns and asks once
EXPORT_MBPS = 150  # a conservative disk-bound guess for the time estimate


class ExportCancelled(Exception):
    """The player stopped a full export; the partial zip is already gone."""


SETTING_LABELS = {k: v[0] for k, v in profile_tools.SETTING_TEXT.items()}


# ============================================================================= export
@dataclass
class Item:
    """One entry of the profile as an export sees it."""

    key: str  # stable id on the page
    entry: dict  # formats.me3_profile.entries row
    where: Path  # the mod's folder (package) or DLL (native), resolved
    folder: str  # the name the file gives it
    copy: Path  # the folder a full export copies
    only: list[Path] | None  # a DLL sharing a folder: just these files
    size: int
    inside: bool  # lives in the launcher's library (the profile's mods folders)
    row: dict = field(default_factory=dict)


def _folder_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for base, _dirs, names in os.walk(path):
        for n in names:
            try:
                total += (Path(base) / n).stat().st_size
            except OSError:
                pass
    return total


def _dep(d: dict) -> dict:
    return {"id": d["id"], "optional": bool(d.get("optional", True))}


def items(profile: Path, *, full: bool) -> list[Item]:
    """The profile's entries in file order. full: folders are named for a zip (unique, one per mod)."""
    assert_not_ui_thread("profile_transfer.items")
    profile = Path(profile)
    text = me3_profile.read_text(profile)
    found = [e for e in me3_profile.entries(text) if e["path"]]
    pk_root, nt_root = profile_edit.roots(profile, text)
    by_parent: dict[Path, int] = {}
    for e in found:
        if e["kind"] == "native":
            parent = profile_edit.resolve(profile, e["path"]).parent
            by_parent[parent] = by_parent.get(parent, 0) + 1
    taken: set[str] = set()
    out: list[Item] = []
    for n, e in enumerate(found):
        where = profile_edit.resolve(profile, e["path"])
        shared = e["kind"] == "native" and (where.parent == nt_root or by_parent.get(where.parent, 0) > 1)
        stored = e["kind"] == "package" and shared_mods.record_of(
            where
        )  # a Shared mod: named for the mod, not its version
        if e["kind"] == "package":
            name, copy, only = (stored.name if stored else where.name), where, None
        elif shared:
            name, copy, only = where.stem, where.parent, [where, *configs.found(where)]
        else:
            name, copy, only = where.parent.name, where.parent, None
        if full:
            name = naming.unique(name, taken)
            taken.add(name.lower())
        size = (
            sum(p.stat().st_size for p in only if p.is_file()) if only else (_folder_size(copy) if copy.exists() else 0)
        )
        root = pk_root if e["kind"] == "package" else nt_root
        inside = where == root or root in where.parents or bool(stored)
        row: dict[str, Any] = {"kind": e["kind"], "folder": name, "enabled": e["enabled"]}
        if e["kind"] == "package":
            row["id"] = e["id"]
        else:
            row.update(
                file=where.name,
                optional=e["optional"],
                load_early=e["load_early"],
                initializer=e["initializer"],
                finalizer=e["finalizer"],
            )
        row["load_after"] = [_dep(d) for d in e["load_after"]]
        row["load_before"] = [_dep(d) for d in e["load_before"]]
        out.append(Item(f"{e['kind']}:{n}", e, where, name, copy, only, size, inside, row))
    return out


def _config_texts(
    profile: Path, entries: list[Item], *, loc: Locations, settings: LauncherSettings, password: bool
) -> dict[str, str]:
    """{"folder/file": text} for the settings files of the profile's mods (found beside them or attached)."""
    by_where = {it.where: it for it in entries}
    coop = loc.game.coop_dll
    out: dict[str, str] = {}
    for node in mod_configs.tree(profile, loc=loc, settings=settings):
        if node.kind == mod_configs.SEAMLESS:
            item = next((it for it in entries if coop and it.where.name.lower() == coop), None)
        else:
            item = by_where.get(node.target) if node.target is not None else None
        if item is None:
            continue
        for f in node.files:
            key = f"{item.folder}/{f.path.name}"
            if key in out or not f.exists or not configs.settings_name(f.path.name):
                continue
            try:
                text = configs.read(f.path)["text"]
            except configs.ConfigError, OSError:
                continue
            out[key] = text if password or node.kind != mod_configs.SEAMLESS else profile_share.without_password(text)
    return out


def share_list(
    profile: Path,
    *,
    loc: Locations,
    settings: LauncherSettings,
    name: str,
    version: str = "",
    author: str = "",
    password: bool = False,
    include: Callable[[Item], bool] = lambda it: True,
    full: bool = False,
    extra: dict | None = None,
) -> tuple[dict, list[Item]]:
    """(the roundtable-profile document, the items it lists). password: keep the Seamless Co-op password in the
    settings texts (off by default)."""
    import datetime

    profile = Path(profile)
    every = items(profile, full=full)
    chosen = [it for it in every if include(it)]
    kept = {it.key for it in chosen}
    gone = {me3_profile.entry_ref(it.entry).lower() for it in every if it.key not in kept}
    rows = []
    for it in chosen:
        row = dict(it.row)
        for k in ("load_after", "load_before"):
            row[k] = [d for d in row[k] if d["id"].lower() not in gone]
        rows.append(row)
    target = mod_order.target(profile, loc)
    doc: dict[str, Any] = {
        "format": profile_share.FORMAT,
        "version": profile_share.VERSION,
        "game": loc.game.key,
        "name": name,
        "profile_version": version,
        "author": author,
        "exported": datetime.datetime.now().isoformat(timespec="seconds"),
        "settings": profile_tools.read_settings(me3_profile.read_text(profile)),
        "entries": rows,
        "stays_last": target["name"] if target else None,
        "configs": _config_texts(profile, chosen, loc=loc, settings=settings, password=password),
    }
    doc.update(extra or {})
    return doc, chosen


def write_share_list(doc: dict, out_dir: Path) -> Path:
    """The share list as <name>.json in out_dir (temp file, then rename)."""
    out = _out_path(out_dir, doc["name"], ".json")
    tmp = out.with_name(out.name + ".part")
    tmp.write_text(profile_share.dump(doc), encoding="utf-8")
    os.replace(tmp, out)
    return out


def _out_path(out_dir: Path, name: str, suffix: str) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = naming.mod_id(name or "profile")
    out = out_dir / (stem + suffix)
    n = 2
    while out.exists():
        out = out_dir / f"{stem}-{n}{suffix}"
        n += 1
    return out


def default_readme(name: str, version: str, author: str, chosen: list[Item]) -> str:
    lines = [f"# {name or 'Profile'}", ""]
    if version or author:
        lines += [
            " · ".join(x for x in (f"Version {version}" if version else "", f"by {author}" if author else "") if x),
            "",
        ]
    lines += ["## Mods", ""]
    lines += [f"- {it.entry['name']}" + ("" if it.entry["enabled"] else " (off)") for it in chosen]
    return "\n".join(lines) + "\n"


def save_candidate(profile: Path, *, loc: Locations) -> Path | None:
    """The save file this profile plays on (its savefile setting, else the game's default), if there is one."""
    assert_not_ui_thread("profile_transfer.save_candidate")
    wanted = profile_tools.read_settings(me3_profile.read_text(Path(profile))).get("savefile") or (
        loc.game.save_names[0] if loc.game.save_names else ""
    )
    return next((p for p in loc.save_files() if p.name.lower() == str(wanted).lower()), None)


def full_export(
    profile: Path,
    *,
    loc: Locations,
    settings: LauncherSettings,
    name: str,
    version: str,
    author: str,
    readme: str,
    changelog: str,
    chosen: set[str],
    out_dir: Path,
    password: bool = False,
    with_configs: bool = True,
    with_save: bool = False,
    progress: Callable[[int, int, str, int, int], None] = lambda *_: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> Path:
    """The zip: manifest.json, <name>.me3 pointing at mods/<folder> and dlls/<folder>/<dll>, those folders,
    README.md, CHANGELOG.md and the save under save/ when asked. Written to a temp file and renamed; never into a
    folder of the profile or of a mod it copies."""
    profile, out_dir = Path(profile), Path(out_dir).resolve()
    doc, picked = share_list(
        profile,
        loc=loc,
        settings=settings,
        name=name,
        version=version,
        author=author,
        password=password,
        include=lambda it: it.key in chosen,
        full=True,
    )
    if not picked:
        raise ModError("Pick at least one mod to export.")
    for it in picked:
        if out_dir == it.copy.resolve() or it.copy.resolve() in out_dir.parents or out_dir == profile.parent.resolve():
            raise ModError("Choose an output folder outside the profile and the mods.")
    if not with_configs:
        doc["configs"] = {}
    save = save_candidate(profile, loc=loc) if with_save else None
    me3_name = naming.mod_id(name or "profile") + ".me3"
    doc["full"] = {"profile": me3_name, "mods": [it.folder for it in picked], "save": save.name if save else None}
    text = profile_import.NEW_PROFILE.format(game=loc.game.key)
    for key, value in doc["settings"].items():
        text = profile_tools.set_setting(text, key, value)
    for it in picked:
        rel = f"mods/{it.folder}" if it.entry["kind"] == "package" else f"dlls/{it.folder}/{it.where.name}"
        row = {**it.row, "path": rel, "id": it.row.get("id") or ""}
        text += "\n" + "".join(me3_profile.entry_lines(it.entry["kind"], row, "\n"))
    out = _out_path(out_dir, name, ".zip")
    tmp = out.with_name(out.name + ".part")
    files: list[tuple[Path, str]] = []
    for it in picked:
        base = "mods" if it.entry["kind"] == "package" else "dlls"
        if it.only is not None:
            files += [(p, f"{base}/{it.folder}/{p.name}") for p in it.only if p.is_file()]
        else:
            for root, _dirs, names in os.walk(it.copy):
                files += [
                    (Path(root) / n, f"{base}/{it.folder}/{(Path(root) / n).relative_to(it.copy).as_posix()}")
                    for n in names
                    if n not in profile_import.JUNK
                ]
    if save is not None:
        files.append((save, f"save/{save.name}"))
    total = sum(p.stat().st_size for p, _ in files if p.is_file()) or 1
    done = 0
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", profile_share.dump(doc))
            z.writestr(me3_name, text)
            z.writestr("README.md", readme)
            z.writestr("CHANGELOG.md", changelog)
            for n, (path, arc) in enumerate(files, 1):
                if path.is_file() and not path.is_symlink():
                    info = zipfile.ZipInfo.from_file(path, arc)
                    info.compress_type = (
                        zipfile.ZIP_STORED if path.suffix.lower() in STORED_SUFFIXES else zipfile.ZIP_DEFLATED
                    )
                    with path.open("rb") as src, z.open(info, "w") as dst:
                        while chunk := src.read(CHUNK):
                            if cancelled():
                                raise ExportCancelled
                            dst.write(chunk)
                            done += len(chunk)
                            progress(done, total, arc, n, len(files))
        os.replace(tmp, out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return out


# ============================================================================= import: reading
@dataclass
class Incoming:
    kind: str  # json | zip
    path: Path
    share: profile_share.Share
    unpacked: Path | None = None  # zip: the skeleton of its folders in the launcher's temp folder (small files only)
    source: profile_import.ZipSource | None = None  # zip: where the mods are read from when applying
    readme: str = ""
    changelog: str = ""


def read(path: Path, *, loc: Locations) -> Incoming:
    """Open a file someone sent: a share list (.json) or a full export (.zip: only its .me3 and settings files are
    unpacked into the launcher's temp folder; the mods stay in the zip until apply). Raises profile_share.ShareError / ModError with a sentence for the player; nothing else is touched."""
    path = Path(path)
    if path.suffix.lower() != ".zip":
        if path.stat().st_size > profile_share.MAX_JSON:
            raise profile_share.ShareError("That file is too big to be a profile (over 8 MB).")
        return Incoming("json", path, profile_share.parse(path.read_bytes(), loc.game.key))
    try:
        with zipfile.ZipFile(path) as z:
            try:
                info = z.getinfo("manifest.json")
            except KeyError:
                raise profile_share.ShareError("That zip is not a profile export (it has no manifest.json).") from None
            if info.file_size > profile_share.MAX_JSON:
                raise profile_share.ShareError("That zip's manifest is too big to be real.")
            share = profile_share.parse(z.read(info), loc.game.key)

            def text(name: str) -> str:
                try:
                    i = z.getinfo(name)
                except KeyError:
                    return ""
                return z.read(i)[:MAX_README].decode("utf-8", errors="replace") if i.file_size <= MAX_README else ""

            readme, changelog = text("README.md"), text("CHANGELOG.md")
    except zipfile.BadZipFile as e:
        raise profile_share.ShareError("That file is not a readable zip.") from e
    unpacked = data_folder.temp(f"profile-import-{uuid.uuid4().hex[:8]}")
    try:
        source = profile_import.ZipSource(path, unpacked)
        source.skeleton(lambda name: name.lower().endswith(".me3") or configs.settings_name(name.rsplit("/", 1)[-1]))
    except zipfile.BadZipFile as e:
        shutil.rmtree(unpacked, ignore_errors=True)
        raise profile_share.ShareError("That file is not a readable zip.") from e
    except BaseException:
        shutil.rmtree(unpacked, ignore_errors=True)
        raise
    return Incoming("zip", path, share, unpacked, source, readme, changelog)


def discard(incoming: Incoming) -> None:
    """Remove what read() unpacked."""
    if incoming.unpacked is not None:
        shutil.rmtree(incoming.unpacked, ignore_errors=True)


# ============================================================================= import: previewing
@dataclass
class Card:
    """One file the import writes. key: PROFILE_CARD or "folder/name". data / expect: the new bytes and the
    fingerprint of the file as the preview read it ("missing": it is created)."""

    key: str
    title: str
    path: Path
    lines: list[str]
    left_out: list[str] = field(default_factory=list)
    new: bool = False
    data: bytes | None = None
    expect: str | None = None


@dataclass
class Preview:
    incoming: Incoming
    profile: Path  # the profile written (the current one, or the new one for a zip)
    new: bool
    cards: list[Card] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)
    writer: ProfileWriter | None = None
    plan: Any = None
    zip_preview: profile_import.ImportPreview | None = None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _deps_text(deps: list[dict]) -> str:
    return ", ".join(d["id"] for d in deps) or "none"


def _on(value: bool) -> str:
    return "on" if value else "off"


def _plan_options(
    writer: ProfileWriter, share: profile_share.Share, out: Preview
) -> tuple[list[str], list[tuple[int, dict, dict]]]:
    """Match the share list's entries to the profile's, set the options that differ, and reorder the matches (F1).
    Returns the lines for the .me3 card and the matches (the file's position, its entry, the profile's entry)."""
    lines: list[str] = []
    mine = writer.entries()
    pairs: list[tuple[int, dict, dict]] = []  # (the file's position, its entry, the profile's entry)
    used: set[int] = set()
    for pos, s in enumerate(share.entries):
        label = s.get("id") or s.get("file") or s.get("folder")
        hit = None
        for e in mine:
            if e["index"] in used or e["kind"] != s["kind"]:
                continue
            if s["kind"] == "native":
                if Path(e["path"]).name.lower() == s["file"].lower():
                    hit = e
            elif s["id"] and e["id"].lower() == s["id"].lower():
                hit = e
            if hit:
                break
        if hit is None and s["kind"] == "package" and s["folder"]:
            hit = next(
                (
                    e
                    for e in mine
                    if e["index"] not in used
                    and e["kind"] == "package"
                    and Path(e["path"]).name.lower() == s["folder"].lower()
                ),
                None,
            )
        if hit is None:
            out.skipped.append(f"{label}: not in this profile, skipped (with its options and settings files)")
            continue
        used.add(hit["index"])
        pairs.append((pos, s, hit))
    refmap = {}
    for _pos, s, e in pairs:
        sender = s.get("id") or s.get("folder") if s["kind"] == "package" else s["file"]
        refmap[str(sender).lower()] = me3_profile.entry_ref(e)
        if s["kind"] == "package" and s.get("folder"):
            refmap.setdefault(s["folder"].lower(), me3_profile.entry_ref(e))
    old_order = {k: [e["name"] for e in mine if e["kind"] == k] for k in ("package", "native")}
    for _pos, s, e in pairs:
        wanted: dict[str, Any] = {"enabled": s["enabled"]}
        dropped = []
        for k in ("load_after", "load_before"):
            got = []
            for d in s[k]:
                if d["id"].lower() in refmap:
                    got.append({"id": refmap[d["id"].lower()], "optional": d["optional"]})
                else:
                    dropped.append(d["id"])
            wanted[k] = got
        if s["kind"] == "native":
            wanted.update({k: s[k] for k in ("optional", "load_early", "initializer", "finalizer")})
        now = writer.options(e["index"])
        changed = {}
        for k, v in wanted.items():
            cur = now.get(k)
            if k in ("load_after", "load_before"):
                same = [(d["id"].lower(), d["optional"]) for d in cur or []] == [
                    (d["id"].lower(), d["optional"]) for d in v
                ]
            else:
                same = (cur or None) == (v or None) if k in ("initializer", "finalizer") else cur == v
            if not same:
                changed[k] = v
                if k == "enabled":
                    lines.append(f"{e['name']}: {_on(cur)} → {_on(v)}")
                elif k in ("load_after", "load_before"):
                    lines.append(f"{e['name']}: {k.replace('_', ' ')} {_deps_text(cur)} → {_deps_text(v)}")
                else:
                    lines.append(f"{e['name']}: {k.replace('_', ' ')} changes")
        if changed:
            writer.set_options(e["index"], changed)
        for d in dropped:
            out.skipped.append(f"{e['name']}: waits for {d}, which is not in this profile, so that is left out")
    # F1: within the slots the matches already hold, they take the file's relative order
    for kind in ("package", "native"):
        group = [(pos, e["index"]) for pos, s, e in pairs if s["kind"] == kind]
        slots = sorted(i for _p, i in group)
        wanted_order = [i for _p, i in sorted(group)]
        if slots == wanted_order:
            continue
        block_lines = {b["index"]: list(b["lines"]) for b in me3_profile.blocks(writer.as_blocks())}
        for slot, source in zip(slots, wanted_order, strict=True):
            chunk = block_lines[source]
            nl = "\r\n" if "\r\n" in writer.text else "\n"
            if chunk and not chunk[-1].endswith("\n"):
                chunk[-1] += nl
            if chunk and chunk[-1].strip():  # a blank line keeps it apart from the next block
                chunk.append(nl)
            writer.replace_block(slot, chunk)
        after = [e["name"] for e in writer.entries() if e["kind"] == kind]
        for n, name in enumerate(after):
            if (
                name in old_order[kind]
                and old_order[kind].index(name) != n
                and name in {e["name"] for _, _, e in pairs}
            ):
                lines.append(f"{name}: moves from {old_order[kind].index(name) + 1} to {n + 1}")
    return lines, pairs


def _plan_settings(writer: ProfileWriter, settings: dict, out: Preview) -> list[str]:
    ok, left = profile_share.usable_settings(settings)
    out.skipped += left
    now = profile_tools.read_settings(writer.text)
    lines = []
    for key, value in ok.items():
        old = now.get(key)
        if old == value or (key == "start_online" and old is None and value is False):
            continue
        writer.set_setting(key, value)
        lines.append(f"{SETTING_LABELS.get(key, key)}: {old if old is not None else 'not set'} → {value}")
        if key == "savefile":
            out.notes.append(
                f"If the save {value} does not exist yet, me3 starts it as a copy of your current save when the "
                "game first uses it."
            )
    return lines


def _incoming_values(text: str, name: str) -> dict[tuple[str | None, str], str]:
    doc = config_model.parse(text, config_model.lang_of(name) or config_model.INI)
    return {(sec.name, it.key): it.value for sec in doc.sections for it in sec.settings}


def _file_card(key: str, name: str, text: str, existing: Path | None, shown: Path) -> Card | None:
    """The card for one settings file: values merged into the player's file when it is a form file, else the text
    replaces it; a file that is not there is created. None: nothing would change."""
    if existing is not None and existing.is_file():
        opened = mod_configs.open_file(existing)
        if opened.doc is not None and config_model.lang_of(name):
            changes, left = mod_configs.plan_merge(opened, _incoming_values(text, name))
            if not changes:
                return None
            new_text = mod_configs.merged_text(opened, {k: new for k, (_old, new) in changes.items()})
            lines = [f"{k}: {old} → {new}" for (_s, k), (old, new) in changes.items()]
            left_out = [f"{k}: not in your file, left out" for k in left]
        else:
            if text == opened.text:
                return None
            new_text = text
            diff = [
                l
                for l in difflib.unified_diff(opened.text.splitlines(), text.splitlines(), lineterm="", n=0)
                if l[:1] in "+-" and l[:3] not in ("+++", "---")
            ]
            lines = [*diff[:12], *([f"... and {len(diff) - 12} more lines"] if len(diff) > 12 else [])]
            left_out = []
        data = configs.encode(name, new_text, opened.encoding, opened.crlf)
        return Card(key, name, shown, lines, left_out, False, data, opened.sha)
    return Card(key, name, shown, ["New file"], [], True, configs.encode(name, text, "utf-8", False), "missing")


def _config_cards(
    share: profile_share.Share, place: Callable[[str, str], tuple[Path | None, Path] | str], out: Preview
):
    """place(folder, name) -> (the player's existing file or None, where it would be) or why it is skipped."""
    for (folder, name), text in share.configs.items():
        key = f"{folder}/{name}"
        got = place(folder, name)
        if isinstance(got, str):
            out.skipped.append(f"{key}: {got}")
            continue
        try:
            card = _file_card(key, name, text, got[0], got[1])
        except (configs.ConfigError, OSError, ValueError) as e:
            out.skipped.append(f"{key}: {e}")
            continue
        if card is not None:
            out.cards.append(card)


def _node_folder(node: mod_configs.ModNode) -> str:
    if node.kind == mod_configs.SEAMLESS:
        return node.files[0].path.parent.name if node.files else ""
    if node.target is None:
        return ""
    return node.target.name if node.kind == "package" else node.target.parent.name


def preview(
    incoming: Incoming,
    current: Path,
    *,
    loc: Locations,
    settings: LauncherSettings,
    new_name: str | None = None,
    me3: str | None = None,
    choices: dict[str, str] | None = None,
) -> Preview:
    """What importing does, file by file, with nothing written. new_name: a zip makes a new profile of this name
    (None: it goes into the current profile). me3: which profile of a zip (default the one the manifest names).
    choices: the player's pick per clashing mod (profile_import.CHOICES)."""
    current = Path(current)
    share = incoming.share
    out = Preview(incoming, current, False, skipped=list(share.skipped))
    if incoming.kind == "zip":
        return _preview_zip(out, incoming, current, loc=loc, new_name=new_name, me3=me3, choices=choices)
    writer = ProfileWriter(current, loc)
    out.writer = writer
    lines, pairs = _plan_options(writer, share, out)
    lines += _plan_settings(writer, share.settings, out)
    # the settings files: each goes where the matching mod of this profile keeps its own
    matched: dict[str, Path] = {}
    for _pos, s, e in pairs:
        p = profile_edit.resolve(current, e["path"])
        matched.setdefault(s["folder"].lower(), p if e["kind"] == "package" else p.parent)
    tree = mod_configs.tree(current, loc=loc, settings=settings)

    def place(folder: str, name: str):
        dest = matched.get(folder.lower())
        if dest is None:
            return "not in this profile, skipped"
        existing = next(
            (
                f.path
                for n in tree
                if _node_folder(n).lower() == dest.name.lower()
                for f in n.files
                if f.path.name.lower() == name.lower()
            ),
            None,
        )
        return existing, existing or dest / name

    _config_cards(share, place, out)
    out.plan = writer.plan("before importing a shared profile")
    out.refusals = [r.message for r in out.plan.refusals]
    if writer.changes:
        out.cards.insert(0, Card(PROFILE_CARD, current.name, current, lines or ["Order and settings"]))
    return out


def _preview_zip(
    out: Preview,
    incoming: Incoming,
    current: Path,
    *,
    loc: Locations,
    new_name: str | None,
    me3: str | None,
    choices: dict[str, str] | None,
) -> Preview:
    share, unpacked = incoming.share, incoming.unpacked
    assert unpacked is not None
    inside = profile_import.bundled(unpacked)
    pick = me3 or next((m for m in inside if Path(m).name == share.full.get("profile")), inside[0] if inside else None)
    if pick is None:
        out.refusals.append("That zip holds no profile (.me3).")
        return out
    ok, left = profile_share.usable_settings(share.settings)
    out.skipped += left

    def tune(writer: ProfileWriter) -> None:
        for key, value in ok.items():
            if not (
                key == "start_online" and value is False and profile_tools.read_settings(writer.text).get(key) is None
            ):
                writer.set_setting(key, value)
        if "savefile" in ok:
            out.notes.append(
                f"If the save {ok['savefile']} does not exist yet, me3 starts it as a copy of your current save "
                "when the game first uses it."
            )

    prev = profile_import.preview_import(
        unpacked,
        pick,
        current,
        loc=loc,
        new_name=new_name,
        tune=tune,
        archive=incoming.source,
        choices=choices,
        download=incoming.path.name,
    )
    out.zip_preview, out.profile, out.new = prev, prev.profile, prev.new
    out.skipped += prev.skipped
    out.refusals += prev.refusals
    out.cards.append(Card(PROFILE_CARD, prev.profile.name, prev.profile, list(prev.lines)))

    def place(folder: str, name: str):
        for src, dest in prev.copies:
            if src.is_dir() and src.name.lower() == folder.lower():
                return (src / name if (src / name).is_file() else None), dest / name
        for src, _dest in prev.reused:
            if src.is_dir() and src.name.lower() == folder.lower():
                return "already installed and reused as it is, so its settings file is left alone"
        for src, _dest in prev.kept:
            if src.is_dir() and src.name.lower() == folder.lower():
                return "your installed copy is kept, so its settings file is left alone"
        return "not among the mods this zip copies, skipped"

    _config_cards(share, place, out)
    if share.full.get("save"):
        out.notes.append(
            f"The zip holds a save ({share.full['save']}). It is not imported: restore saves on the Saves page."
        )
    return out


# ============================================================================= import: applying
def apply(
    prev: Preview,
    skip: frozenset[str] | set[str] = frozenset(),
    progress: Callable[[int, int], None] = lambda done, total: None,
) -> dict:
    """Write the ticked cards as one operation, with an undo record (Undo import). Returns {operation, profile,
    new}. A file changed on disk since the preview refuses the whole import, and nothing is written. progress(done,
    total): bytes of the zip's mods unpacked so far."""
    if prev.refusals:
        raise ModError("; ".join(prev.refusals))
    out = _apply_zip(prev, skip, progress) if prev.zip_preview is not None else _apply_json(prev, skip)
    run_logging.set_undo(
        {
            "type": "profile-import",
            "profile": out["profile"],
            "name": Path(out["profile"]).name,
            "operation": out["operation"],
        }
    )
    run_logging.log(f"done: imported a shared profile into {Path(out['profile']).name}")
    return out


def _apply_json(prev: Preview, skip) -> dict:
    writer, plan = prev.writer, prev.plan
    assert writer is not None and plan is not None
    cards = [c for c in prev.cards if c.key != PROFILE_CARD and c.key not in skip and c.data is not None]
    do_profile = bool(writer.changes) and PROFILE_CARD not in skip
    if not do_profile and not cards:
        raise ModError("Nothing is ticked.")
    profile = prev.profile
    with operations.lock(profile):
        operations.recover(profile)
        op = operations.start(profile, f"import into {profile.name}")
        try:
            if do_profile:
                writer.commit(plan, operation=op)
            else:  # the profile stays, but is the operation's first step (an undo looks for it there)
                op.write_file(profile, writer.read, expect=_sha(writer.read))
            for c in cards:
                assert c.data is not None
                op.write_file(c.path, c.data, expect=c.expect)
            op.note(kind="profile-import", name=profile.name, new_profile=False, made={}, entries=[])
        except BaseException:
            op.discard()
            raise
        operations.commit(op)
    return {"operation": str(op.dir), "profile": str(profile), "new": False}


def _apply_zip(prev: Preview, skip, progress) -> dict:
    zp = prev.zip_preview
    assert zp is not None
    ticked = {c.key.lower(): c for c in prev.cards if c.key != PROFILE_CARD and c.key not in skip and c.data}
    by_dest = {dest: src.name for src, dest in zp.copies}

    def after_copy(dest: Path, staged: Path) -> None:
        for key, card in ticked.items():
            if by_dest.get(dest, "").lower() == key.split("/")[0] and card.data is not None:
                (staged / card.path.name).write_bytes(card.data)

    return profile_import.apply_import(zp, log=run_logging.log, after_copy=after_copy, progress=progress)
