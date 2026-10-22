"""The Install mod dialog's adapter (technical specification §8.2): the QObject InstallModDialog.qml binds to, held
by the Mods adapter. It picks or takes the mods to install, unpacks and plans each in the background, replans as the
name, id or variant is edited, keeps several drops in a queue (one dialog after another, the next once the
previous install has finished), and runs the install as a logged job of the host. Words and state come from
InstallDraft (ui/pages/mods/install.py); what an install does is mods/install.py and services/."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

from bayle.mods import extract as mod_extract
from bayle.overhauls import basic
from bayle.platform import logging as run_logging
from bayle.platform.text import tr
from bayle.services import mod_configs, profile_mods
from bayle.services import mods as mod_service
from bayle.ui.notifications import Notifier
from bayle.views.file_actions import shown_path
from bayle.views.mod_install import InstallDraft
from bayle.views.mod_install import words as install_words


def setup_notes(config, folder: Path) -> list[str]:
    """What making the setup's steps left out or dropped (entries a newer download no longer has, ...): the notes the
    preview shows. Reads the whole download: not for the UI thread."""
    from bayle.config import layout

    notes: list[str] = []
    if config.basic is None:
        return notes
    try:
        basic.make(
            id=config.id,
            label=config.label,
            game=config.game,
            basic=config.basic,
            folder=folder,
            short_label=config.short_label,
            reserved=layout.reserved_names(),
            notes=notes,
            unset_tables=True,
        )
    except ValueError:
        pass  # the preview itself says why it can't be set up
    return notes


def _drop_staging(plan: dict) -> None:
    if plan.get("staging"):
        shutil.rmtree(plan["staging"], ignore_errors=True)


class InstallAdapter(QObject):
    viewChanged = Signal()
    openRequested = Signal()  # show the dialog

    def __init__(self, host: Any, notifier: Notifier, parent=None):
        super().__init__(parent)
        self.host = host
        self.notifier = notifier
        self._queue: list[Path] = []
        self._draft: InstallDraft | None = None
        self._planning = False  # a source is being unpacked
        self._generation = 0  # a result for an older edit is dropped
        self._planned: tuple = ()  # (name, id, variant) the plan is for
        self._previewed: tuple = ()  # (mode, name, variant) the preview is for
        self._preview: Any = None  # the overhaul_install.InstallPreview the dialog shows
        self._config: Any = None  # the setup's config as the player has set its DLLs; (name, variant) it is for:
        self._config_for: tuple = ()
        self._edited = False  # the player changed the DLL options or the Files table of a matched setup
        self._via_setup = False  # so it is installed as a setup of its own (its config saved with the changes)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._refresh)

    view = Property(dict, lambda self: self._view(), notify=viewChanged)
    words = Property(dict, lambda self: install_words(), constant=True)

    def _view(self) -> dict:
        return self._draft.view() if self._draft else {}

    # ---- taking the sources
    @Slot(bool)
    def pick(self, from_folder: bool) -> None:
        if self._profile() is None:
            return
        if from_folder:
            src = self.host.pick_folder(tr("Install a mod: pick its folder"))
        else:
            src = self.host.pick_file(
                tr("Install a mod: pick an archive or DLL"),
                tr("Mod archive or DLL (*.zip *.7z *.rar *.dll);;All files (*)"),
            )
        if src:
            self._add([Path(src)])

    @Slot(list)
    def dropped(self, urls: list) -> None:
        paths = [Path(QUrl(u).toLocalFile()) for u in urls if QUrl(u).isLocalFile()]
        if paths and self._profile() is not None:
            self._add(paths)

    def _add(self, paths: list[Path]) -> None:
        """Folders, .zip / .7z / .rar archives and DLL mods can be installed; the rest is skipped, with a toast."""
        kinds = (*mod_extract.ARCHIVE_EXTENSIONS, ".dll")
        usable = [x for x in paths if x.is_dir() or x.suffix.lower() in kinds]
        skipped = [x for x in paths if x not in usable]
        if skipped:
            self.notifier.toast(
                tr("Skipped {names}: not an archive (.zip, .7z, .rar), a .dll or a folder.").format(
                    names=", ".join(x.name for x in skipped[:4])
                )
            )
        self._queue += usable
        self._next()

    def _profile(self) -> Path | None:
        profile = self.host.profile
        if profile is None or not Path(profile).is_file():
            self.notifier.toast(tr("Pick a profile first."), error=True)
            return None
        if self.host.busy:
            self.notifier.toast(tr("Wait for the current job to finish."), error=True)
            return None
        return Path(profile)

    def after_job(self) -> None:
        """The page has read the profile again (an install finished, or anything else): open the next queued mod."""
        self._next()

    # ---- one source at a time
    def _next(self) -> None:
        if self._draft is not None or self._planning or not self._queue or self.host.busy:
            return
        profile = self.host.profile
        if profile is None or not Path(profile).is_file():
            self._queue = []
            return
        src = self._queue.pop(0)
        loc = self.host.locations
        self._planning = True

        def work():
            try:
                plan = mod_service.plan_mod_install(profile, src, loc=loc)
            except Exception as e:  # an archive that can't be read
                return src, None, str(e), False
            return src, plan, "", mod_service.overhaul_preview_on(loc)

        self.host.run_in_background(work, self._planned_source)

    def _planned_source(self, got) -> None:
        self._planning = False
        src, plan, error, overhaul_on = got
        profile = self.host.profile
        if plan is None:
            self.notifier.toast(tr("Could not read {name}: {why}").format(name=src.name, why=error), error=True)
        elif plan.get("error"):
            self.notifier.toast(
                tr("{name} is not a mod Bayle can install: {why}").format(name=src.name, why=plan["error"]),
                error=True,
            )
            _drop_staging(plan)
        elif (
            plan.get("in_place") and plan.get("already_listed") and len(plan["already_listed"]) == len(plan["entries"])
        ):
            self.notifier.toast(
                tr("Nothing to do: {name} is already installed and listed in the profile.").format(name=plan["name"])
            )
            _drop_staging(plan)
        elif profile is None:
            _drop_staging(plan)
        else:
            self._draft = InstallDraft(plan, Path(profile), overhaul_on=overhaul_on)
            self._config, self._config_for, self._edited, self._via_setup = None, (), False, False
            self._planned = self._key()
            self._previewed = ()
            self._preview = None
            if self._draft.overhaul_mode:
                self._refresh()  # the preview of the option that starts ticked
            self.viewChanged.emit()
            self.openRequested.emit()
            return
        QTimer.singleShot(0, self._next)

    # ---- edits (the dialog calls these as the player types and ticks)
    def _key(self) -> tuple:
        d = self._draft
        assert d is not None
        return (d.name_text.strip(), d.id_text.strip(), d.variant)

    def _changed(self, replan: bool = False) -> None:
        if self._draft is None:
            return
        if replan:
            self._draft.busy = True  # Install waits for the plan of what was typed
            self._timer.start()
        self.viewChanged.emit()

    @Slot(str)
    def setName(self, text: str) -> None:
        if self._draft:
            self._draft.set_name(text)
            self._changed(True)

    @Slot(str)
    def setId(self, text: str) -> None:
        if self._draft:
            self._draft.set_id(text)
            self._changed(True)

    @Slot(str)
    def setVariant(self, name: str) -> None:
        if self._draft:
            self._draft.variant = name
            self._changed(True)

    @Slot(str, bool)
    def setTick(self, name: str, on: bool) -> None:
        if self._draft:
            self._draft.ticks[name] = on
            self._changed()

    @Slot(bool)
    def setPlaceLast(self, last: bool) -> None:
        if self._draft:
            self._draft.place_last = last
            self._changed()

    @Slot(bool)
    def setRebuild(self, on: bool) -> None:
        if self._draft:
            self._draft.rebuild = on
            self._changed()

    @Slot(bool)
    def setAfterLast(self, on: bool) -> None:
        if self._draft:
            self._draft.set_after_last(on)
            self._changed()

    @Slot(str)
    def setLibraryChoice(self, key: str) -> None:
        if self._draft:
            self._draft.library_choice = key
            self._changed()

    @Slot(bool)
    def setOverhaul(self, on: bool) -> None:
        if self._draft:
            self._draft.overhaul = on
            self._changed(True)

    @Slot(str, str, str)
    def setNative(self, file: str, kind: str, value: str) -> None:
        """A DLL option of the setup (kind early | after | init): the preview is worked out again with it."""
        d, cfg = self._draft, self._config
        if d is None or cfg is None or cfg.basic is None:
            return
        for n in d.natives:
            if n["file"] == file:
                n.update({"early": {"load_early": value == "true"}, "after": {"after_others": value == "true"},
                          "init": {"initializer": value.strip() or None}}[kind])  # fmt: skip
        from bayle.overhauls.config import BasicNative

        basic = cfg.basic.model_copy(update={"natives": [BasicNative(**n) for n in d.natives]})
        self._config = cfg.model_copy(update={"basic": basic})
        self._previewed, self._edited = (), True
        self._changed(True)

    @Slot(str, str)
    def setTable(self, file: str, table: str) -> None:
        """The table a texts entry sets its strings in (chosen among the tables of the download's copy)."""
        d, cfg = self._draft, self._config
        if d is None or cfg is None or cfg.basic is None:
            return
        for t in d.texts:
            if t["file"] == file:
                t["table"] = table
        texts = [t.model_copy(update={"table": table if t.file == file else t.table}) for t in cfg.basic.texts]
        self._config = cfg.model_copy(update={"basic": cfg.basic.model_copy(update={"texts": texts})})
        self._previewed, self._edited = (), True
        self._changed(True)

    @Slot(str, str)
    def setFile(self, file: str, value: str) -> None:
        """A choice of the Files table (an action, or place:<game path>): the preview is worked out again with it."""
        d, cfg = self._draft, self._config
        if d is None or cfg is None or cfg.basic is None:
            return
        row = next((r for r in d.files if r["file"] == file), None)
        if row is None:
            return
        action, target = basic.decode_action(value)
        row["action"], row["target"] = action, target or (row["target"] if action == "place" else "")
        kept = {r["file"]: basic.encode_action(r["action"], r["target"]) for r in d.files}
        stored = {f: a for f, a in kept.items() if a != next(r for r in d.files if r["file"] == f)["choices"][0]}
        self._config = cfg.model_copy(update={"basic": cfg.basic.model_copy(update={"files": stored})})
        self._previewed, self._edited = (), True
        self._changed(True)

    def _refresh(self) -> None:
        """Plan again for the typed name, id and variant, and work out the overhaul preview when that option is on;
        in the background, the newest edit wins."""
        d = self._draft
        if d is None:
            return
        self._generation += 1
        gen, profile, loc, plan = self._generation, self.host.profile, self.host.locations, d.plan
        key, mode = self._key(), d.overhaul_mode
        config_in = self._config if self._config_for == (key[0], key[2]) else None
        edited = self._edited and config_in is not None
        have_files = bool(d.files)
        replan, preview = key != self._planned, bool(mode) and (mode, key[0], key[2]) != self._previewed
        if not (replan or preview):
            d.busy = False
            self.viewChanged.emit()
            return
        d.busy = True
        self.viewChanged.emit()

        def work():
            out: dict = {"plan": None, "preview": None, "problem": ""}
            cur = plan

            def rows(config, folder) -> None:  # the Files table reads the whole download: not on the UI thread
                if not have_files or out.get("fresh"):
                    out["rows"] = mod_service.setup_file_rows(config, folder)
                setup = {"config": config, "folder": Path(folder)}
                out["texts"] = mod_configs.overhaul_choices(setup, loc.game_dir())["texts"]
                out["setup_notes"] = setup_notes(config, Path(folder))

            try:
                if replan:
                    out["plan"] = cur = mod_service.replan_mod_install(
                        profile, plan, key[0] or None, key[1] or None, key[2], loc=loc
                    )
            except Exception as e:  # an unreadable variant: say so, keep the last good plan
                out["problem"] = str(e)
                return gen, key, mode, out
            if preview:
                try:
                    if mode == "matched":
                        pv = mod_service.preview_overhaul_install(profile, cur["unpacked"], loc=loc)
                        saved = pv.found.config if mod_service.setup_is_editable(pv.found.config) else None
                        out["preview"], out["folder"] = pv, pv.found.folder
                        if saved is not None and edited:  # changed in the dialog: installed as a setup, config saved
                            out["config"], out["fresh"], out["edited"] = config_in, False, True
                            out["preview"] = mod_service.preview_overhaul_setup(
                                profile, pv.found.folder, config_in, loc=loc
                            )
                        elif saved is not None:  # a saved setup: its options, ready to change
                            out["config"], out["fresh"] = saved, True
                        if "config" in out:
                            rows(out["config"], pv.found.folder)
                    else:
                        config = config_in or mod_service.propose_overhaul_setup(cur["root"], key[0], loc=loc)
                        out["config"], out["fresh"], out["folder"] = config, config_in is None, cur["root"]
                        rows(config, cur["root"])
                        out["preview"] = mod_service.preview_overhaul_setup(profile, cur["root"], config, loc=loc)
                except Exception as e:  # not one the launcher can set up: the dialog says why
                    out["refusal"] = str(e)
            return gen, key, mode, out

        self.host.run_in_background(work, self._refreshed)

    def _refreshed(self, got) -> None:
        gen, key, mode, out = got
        d = self._draft
        if d is None or gen != self._generation:
            return
        d.busy = False
        d.problem = out["problem"]
        if out["plan"] is not None:
            d.new_plan(out["plan"], variant_changed=key[2] != self._planned[2])
            self._planned = key
        if not d.problem and (out.get("preview") is not None or out.get("refusal")):
            pv = out.get("preview")
            self._preview = pv
            d.preview = (
                {"lines": list(pv.lines), "notes": list(pv.notes), "refusals": list(pv.refusals)}
                if pv is not None
                else {"lines": [], "notes": [], "refusals": [out["refusal"]]}
            )
            self._previewed = (mode, key[0], key[2])
            self._via_setup = bool(out.get("edited"))
            if out.get("fresh"):  # a config proposed again: the player's earlier changes were to another one
                self._edited = False
            if out.get("config") is not None:
                self._config, self._config_for = out["config"], (key[0], key[2])
                d.natives = [n.model_dump() for n in out["config"].basic.natives]
                if out.get("rows") is not None:
                    d.files = out["rows"]
                d.texts = out.get("texts") or []
                if d.preview is not None:
                    d.preview["notes"] += out.get("setup_notes") or []
                    if any(not t["table"] for t in d.texts):  # said once per file below, not by the backend too
                        d.preview["refusals"] = [
                            r for r in d.preview["refusals"] if not r.startswith("Choose the table of ")
                        ]
                    for t in d.texts:
                        if not t["table"]:
                            d.preview["refusals"].append(
                                tr("Choose the table for the texts added to {file} before installing.").format(
                                    file=shown_path(t["file"])
                                )
                            )
        self.viewChanged.emit()

    # ---- ending
    @Slot(result=bool)
    def accept(self) -> bool:
        """Install; True closes the dialog."""
        d = self._draft
        if d is None or self._timer.isActive() or not d.can_install():
            return False
        profile = self._profile()
        if profile is None:
            return False
        loc, mode, preview = self.host.locations, d.overhaul_mode, self._preview
        plan = d.finish()
        if mode == "matched" and self._via_setup:
            mode = "setup"
        self._draft, self._preview = None, None
        self.viewChanged.emit()
        if mode:
            self._install_overhaul(plan, preview, mode, loc)
        else:
            self._install_mod(profile, plan, loc)
        return True

    def _install_mod(self, profile: Path, plan: dict, loc) -> None:
        def job(_launch, job_loc):
            run_logging.start_log(f"launcher: install mod {plan['name']}", job_loc.game.key)
            try:
                out = profile_mods.install_and_record(profile, plan, loc=loc)
                run_logging.log(f"done: {'updated' if out['update'] else 'installed'} {plan['name']}")
            except Exception as e:
                run_logging.log(f"error: {e}")
                raise SystemExit(1) from e

        self.host.run_job(job, tr("Installing {name}...").format(name=plan["name"]))

    def _install_overhaul(self, plan: dict, preview: Any, mode: str, loc) -> None:
        setup = mode == "setup"

        def job(_launch, job_loc):
            run_logging.start_log(f"launcher: install overhaul {preview.label}", job_loc.game.key)
            try:
                (mod_service.install_overhaul_setup if setup else mod_service.install_overhaul)(preview, loc=loc)
            except Exception as e:
                run_logging.log(f"error: {e}")
                raise SystemExit(1) from e
            finally:
                _drop_staging(plan)

        self.host.run_job(job, tr("Installing {name} as an overhaul...").format(name=preview.label))

    @Slot(result=bool)
    def importInstead(self) -> bool:
        """The download ships .me3 profiles: the Export / Import page takes over its unpacked folder and clears the
        staging folder itself, so it is not dropped here. True closes the dialog."""
        d = self._draft
        if d is None or not d.plan.get("profiles_inside"):
            return False
        plan = d.plan
        self._draft = None
        self.viewChanged.emit()
        self.host.open_profile_import(Path(plan["unpacked"]), plan["profiles_inside"], plan.get("staging"))
        return True

    @Slot()
    def dialogClosed(self) -> None:
        """The dialog closed: a cancel (an install already took the draft) drops the unpacked copy."""
        d, self._draft = self._draft, None
        self._generation += 1
        self._timer.stop()
        if d is not None:
            _drop_staging(d.plan)
            self.viewChanged.emit()
        QTimer.singleShot(0, self._next)
