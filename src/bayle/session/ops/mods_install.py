"""The Install mod dialog as a draft the session holds: open a download (it is unpacked and planned), edit it (name, id,
variant, ticks, the overhaul option, an overhaul's DLL options, Files table and text tables), replan and preview as
the edits ask (the heavy reads), and finish as a logged job. A draft has an id; clients keep only the id and the view
(plain data) the operations return. See ops/mods.py for the conventions.

shortcut: a draft nobody closes (a client that went away) keeps its unpacked copy until the session ends; give drafts a
time to live with the first remote client."""

from __future__ import annotations

import itertools
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from bayle.mods import extract as mod_extract
from bayle.overhauls import basic
from bayle.platform import logging as run_logging
from bayle.platform.text import tr
from bayle.platform.threads import assert_not_ui_thread
from bayle.services import mod_configs, profile_mods
from bayle.services import mods as mod_service
from bayle.services.errors import OperationError
from bayle.session.operations import Call, Params, Result, Session, operation
from bayle.session.ops.mods import ProfileRef, idle, run_logged_job
from bayle.views.file_actions import shown_path
from bayle.views.mod_install import InstallDraft


def drop_staging(plan: dict) -> None:
    if plan.get("staging"):
        shutil.rmtree(plan["staging"], ignore_errors=True)


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


# ----------------------------------------------------------------------------- one open draft
@dataclass
class DraftState:
    draft: InstallDraft
    profile: Path
    planned: tuple = ()  # (name, id, variant) the plan is for
    previewed: tuple = ()  # (mode, name, variant) the preview is for
    preview: Any = None  # the overhaul_install.InstallPreview the dialog shows
    config: Any = None  # the setup's config as the player has set its DLLs; (name, variant) it is for:
    config_for: tuple = ()
    edited: bool = False  # the player changed the DLL options or the Files table of a matched setup
    via_setup: bool = False  # so it is installed as a setup of its own (its config saved with the changes)
    gen: int = 0  # counts the edits that ask for a new plan: a heavy read answers only for the one it started with
    lock: threading.Lock = field(default_factory=threading.Lock)  # short: never held while a download is read

    def key(self) -> tuple:
        d = self.draft
        return (d.name_text.strip(), d.id_text.strip(), d.variant)

    # ---- edits: cheap, in memory; True when a replan or a new preview is needed
    def edit(self, e: InstallEdit) -> bool:
        d = self.draft
        with self.lock:
            again = True
            if e.field == "name":
                d.set_name(e.text)
            elif e.field == "id":
                d.set_id(e.text)
            elif e.field == "variant":
                d.variant = e.text
            elif e.field == "overhaul":
                d.overhaul = e.on
            elif e.field == "native":
                again = self._set_native(e.key, e.kind, e.text)
            elif e.field == "table":
                again = self._set_table(e.key, e.text)
            elif e.field == "file":
                again = self._set_file(e.key, e.text)
            else:
                again = False
                if e.field == "tick":
                    d.ticks[e.key] = e.on
                elif e.field == "place_last":
                    d.place_last = e.on
                elif e.field == "rebuild":
                    d.rebuild = e.on
                elif e.field == "after_last":
                    d.set_after_last(e.on)
                elif e.field == "library":
                    d.library_choice = e.text
            if again:
                d.busy = True  # Install waits for the plan of what was typed
                self.gen += 1
            return again

    def _set_native(self, file: str, kind: str, value: str) -> bool:
        """A DLL option of the setup (kind early | after | init): the preview is worked out again with it."""
        d, cfg = self.draft, self.config
        if cfg is None or cfg.basic is None:
            return False
        for n in d.natives:
            if n["file"] == file:
                n.update({"early": {"load_early": value == "true"}, "after": {"after_others": value == "true"},
                          "init": {"initializer": value.strip() or None}}[kind])  # fmt: skip
        from bayle.overhauls.config import BasicNative

        new = cfg.basic.model_copy(update={"natives": [BasicNative(**n) for n in d.natives]})
        self.config = cfg.model_copy(update={"basic": new})
        self.previewed, self.edited = (), True
        return True

    def _set_table(self, file: str, table: str) -> bool:
        """The table a texts entry sets its strings in (chosen among the tables of the download's copy)."""
        d, cfg = self.draft, self.config
        if cfg is None or cfg.basic is None:
            return False
        for t in d.texts:
            if t["file"] == file:
                t["table"] = table
        texts = [t.model_copy(update={"table": table if t.file == file else t.table}) for t in cfg.basic.texts]
        self.config = cfg.model_copy(update={"basic": cfg.basic.model_copy(update={"texts": texts})})
        self.previewed, self.edited = (), True
        return True

    def _set_file(self, file: str, value: str) -> bool:
        """A choice of the Files table (an action, or place:<game path>): the preview is worked out again with it."""
        d, cfg = self.draft, self.config
        if cfg is None or cfg.basic is None:
            return False
        row = next((r for r in d.files if r["file"] == file), None)
        if row is None:
            return False
        action, target = basic.decode_action(value)
        row["action"], row["target"] = action, target or (row["target"] if action == "place" else "")
        kept = {r["file"]: basic.encode_action(r["action"], r["target"]) for r in d.files}
        stored = {f: a for f, a in kept.items() if a != next(r for r in d.files if r["file"] == f)["choices"][0]}
        self.config = cfg.model_copy(update={"basic": cfg.basic.model_copy(update={"files": stored})})
        self.previewed, self.edited = (), True
        return True

    # ---- the heavy reads: the session's caller runs them off the UI thread
    def needs_preview(self) -> bool:
        mode = self.draft.overhaul_mode
        return bool(mode) and (mode, self.key()[0], self.key()[2]) != self.previewed

    def replan(self, loc) -> None:
        """Plan again for the typed name, id and variant (nothing is unpacked again); a variant that cannot be read is
        said in draft.problem and the last good plan stays. An edit made meanwhile drops this answer (it asks again)."""
        assert_not_ui_thread("install draft: replan")
        with self.lock:
            d, key = self.draft, self.key()
            if key == self.planned:
                if self.needs_preview():
                    d.problem = ""  # a preview is coming: the last problem is old
                else:
                    d.busy = False
                return
            gen, plan, old = self.gen, d.plan, self.planned
        try:
            new, problem = (
                mod_service.replan_mod_install(self.profile, plan, key[0] or None, key[1] or None, key[2], loc=loc),
                "",
            )
        except Exception as e:
            new, problem = None, str(e)
        with self.lock:
            if gen != self.gen:
                return
            d.problem = problem
            if new is None:
                d.busy = False
                return
            d.new_plan(new, variant_changed=key[2] != old[2])
            self.planned = key
            d.busy = self.needs_preview()

    def refresh_preview(self, loc) -> None:
        """Work out the overhaul preview (and the setup's DLL options, Files table and text tables) when that option
        is on; the Files table reads the whole download. An edit made meanwhile drops this answer."""
        assert_not_ui_thread("install draft: preview")
        with self.lock:
            d = self.draft
            if d.problem or not self.needs_preview():
                d.busy = False
                return
            key, mode, profile, gen, cur = self.key(), d.overhaul_mode, self.profile, self.gen, d.plan
            config_in = self.config if self.config_for == (key[0], key[2]) else None
            edited = self.edited and config_in is not None
            have_files = bool(d.files)
        out: dict = {"preview": None}

        def rows(config, folder) -> None:
            if not have_files or out.get("fresh"):
                out["rows"] = mod_service.setup_file_rows(config, folder)
            setup = {"config": config, "folder": Path(folder)}
            out["texts"] = mod_configs.overhaul_choices(setup, loc.game_dir())["texts"]
            out["setup_notes"] = setup_notes(config, Path(folder))

        try:
            if mode == "matched":
                pv = mod_service.preview_overhaul_install(profile, cur["unpacked"], loc=loc)
                saved = pv.found.config if mod_service.setup_is_editable(pv.found.config) else None
                out["preview"], out["folder"] = pv, pv.found.folder
                if saved is not None and edited:  # changed in the dialog: installed as a setup, config saved
                    out["config"], out["fresh"], out["edited"] = config_in, False, True
                    out["preview"] = mod_service.preview_overhaul_setup(profile, pv.found.folder, config_in, loc=loc)
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
        with self.lock:
            if gen != self.gen:
                return
            self._apply(out, key, mode)
            d.busy = False

    def _apply(self, out: dict, key: tuple, mode: str) -> None:
        d = self.draft
        if not (out.get("preview") is not None or out.get("refusal")):
            return
        pv = out.get("preview")
        self.preview = pv
        d.preview = (
            {"lines": list(pv.lines), "notes": list(pv.notes), "refusals": list(pv.refusals)}
            if pv is not None
            else {"lines": [], "notes": [], "refusals": [out["refusal"]]}
        )
        self.previewed = (mode, key[0], key[2])
        self.via_setup = bool(out.get("edited"))
        if out.get("fresh"):  # a config proposed again: the player's earlier changes were to another one
            self.edited = False
        if out.get("config") is not None:
            self.config, self.config_for = out["config"], (key[0], key[2])
            d.natives = [n.model_dump() for n in out["config"].basic.natives]
            if out.get("rows") is not None:
                d.files = out["rows"]
            d.texts = out.get("texts") or []
            d.preview["notes"] += out.get("setup_notes") or []
            if any(not t["table"] for t in d.texts):  # said once per file below, not by the backend too
                d.preview["refusals"] = [r for r in d.preview["refusals"] if not r.startswith("Choose the table of ")]
            for t in d.texts:
                if not t["table"]:
                    d.preview["refusals"].append(
                        tr("Choose the table for the texts added to {file} before installing.").format(
                            file=shown_path(t["file"])
                        )
                    )


class InstallDrafts:
    """The drafts open in a session, by id."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._drafts: dict[str, DraftState] = {}
        self._ids = itertools.count(1)

    def add(self, state: DraftState) -> str:
        with self._lock:
            draft_id = f"d{next(self._ids)}"
            self._drafts[draft_id] = state
        return draft_id

    def get(self, draft_id: str) -> DraftState:
        with self._lock:
            state = self._drafts.get(draft_id)
        if state is None:
            raise OperationError("unknown_draft", tr("That install is no longer open."), {"draft_id": draft_id})
        return state

    def pop(self, draft_id: str) -> DraftState:
        state = self.get(draft_id)
        with self._lock:
            self._drafts.pop(draft_id, None)
        return state


def drafts(session: Session) -> InstallDrafts:
    return session.service("install_drafts", InstallDrafts)


# ----------------------------------------------------------------------------- the operations
class SourcesParams(Params):
    paths: list[str]


class Sources(Result):
    usable: list[str]  # folders, .zip / .7z / .rar archives and DLL mods
    skipped: list[str]  # the rest (their names go in the page's note)


@operation("mods.install_sources", params=SourcesParams, result=Sources)
def install_sources(call: Call, p: SourcesParams) -> Sources:
    """Which of the picked or dropped paths can be installed."""
    kinds = (*mod_extract.ARCHIVE_EXTENSIONS, ".dll")
    paths = [Path(x) for x in p.paths]
    usable = [x for x in paths if x.is_dir() or x.suffix.lower() in kinds]
    return Sources(usable=[str(x) for x in usable], skipped=[str(x) for x in paths if x not in usable])


class InstallView(Result):
    draft_id: str
    view: dict[str, Any]  # what the dialog shows (views.mod_install.InstallDraft.view)
    pending: bool = False  # a replan or a preview is still to be asked for (replan, then preview)


def _view(draft_id: str, state: DraftState, pending: bool) -> InstallView:
    with state.lock:
        return InstallView(draft_id=draft_id, view=state.draft.view(), pending=pending)


class OpenParams(ProfileRef):
    source: str  # a folder, an archive or a DLL


@operation("mods.install_open", params=OpenParams, result=InstallView, kind="command", writes=True)
def install_open(call: Call, p: OpenParams) -> InstallView:
    """Unpack and plan a download; the draft stays open until finish or close. Heavy: not for the UI thread. Refusals:
    unreadable (the archive can't be read), not_installable (the download has nothing to install), already_listed."""
    assert_not_ui_thread("mods.install_open")
    loc = call.session.locations()
    src = Path(p.source)
    try:
        plan = mod_service.plan_mod_install(p.profile, src, loc=loc)
    except Exception as e:  # an archive that can't be read
        raise OperationError("unreadable", str(e), {"name": src.name}) from e
    if plan.get("error"):
        drop_staging(plan)
        raise OperationError("not_installable", str(plan["error"]), {"name": src.name})
    if plan.get("in_place") and plan.get("already_listed") and len(plan["already_listed"]) == len(plan["entries"]):
        drop_staging(plan)
        raise OperationError("already_listed", plan["name"], {"name": plan["name"]})
    draft = InstallDraft(plan, Path(p.profile), overhaul_on=mod_service.overhaul_preview_on(loc))
    state = DraftState(draft, Path(p.profile))
    state.planned = state.key()
    draft.busy = bool(draft.overhaul_mode)  # the preview of the option that starts ticked is asked for next
    draft_id = drafts(call.session).add(state)
    return _view(draft_id, state, pending=bool(draft.overhaul_mode))


class DraftRef(Params):
    draft_id: str


class InstallEdit(DraftRef):
    """One edit. field: name | id | variant | overhaul | tick | place_last | rebuild | after_last | library | native |
    table | file. key: the file or tick; text: the new text or choice; on: the check; kind: early | after | init."""

    field: Literal[
        "name",
        "id",
        "variant",
        "overhaul",
        "tick",
        "place_last",
        "rebuild",
        "after_last",
        "library",
        "native",
        "table",
        "file",
    ]
    key: str = ""
    text: str = ""
    on: bool = False
    kind: str = ""


@operation("mods.install_edit", params=InstallEdit, result=InstallView, kind="command", writes=True)
def install_edit(call: Call, p: InstallEdit) -> InstallView:
    """Change the draft in memory (cheap). pending: ask for the replan and the preview (after the client's pause)."""
    state = drafts(call.session).get(p.draft_id)
    return _view(p.draft_id, state, pending=state.edit(p))


@operation("mods.install_replan", params=DraftRef, result=InstallView, kind="command", writes=True)
def install_replan(call: Call, p: DraftRef) -> InstallView:
    """Plan again for the typed name, id and variant. Heavy: not for the UI thread."""
    state = drafts(call.session).get(p.draft_id)
    state.replan(call.session.locations())
    return _view(p.draft_id, state, pending=state.needs_preview() and not state.draft.problem)


@operation("mods.install_preview", params=DraftRef, result=InstallView, kind="command", writes=True)
def install_preview(call: Call, p: DraftRef) -> InstallView:
    """Work out the overhaul preview, its DLL options, Files table and text tables. Heavy: not for the UI thread."""
    state = drafts(call.session).get(p.draft_id)
    state.refresh_preview(call.session.locations())
    return _view(p.draft_id, state, pending=False)


class Closed(Result):
    draft_id: str


@operation("mods.install_close", params=DraftRef, result=Closed, kind="command", writes=True)
def install_close(call: Call, p: DraftRef) -> Closed:
    """The dialog was cancelled: the unpacked copy is dropped."""
    state = drafts(call.session).pop(p.draft_id)
    drop_staging(state.draft.plan)
    return Closed(draft_id=p.draft_id)


class Handoff(Result):
    unpacked: str
    profiles: list[str]
    staging: str | None


@operation("mods.install_import", params=DraftRef, result=Handoff, kind="command", writes=True)
def install_import(call: Call, p: DraftRef) -> Handoff:
    """The download ships .me3 profiles: the Export / Import page takes over its unpacked folder (and clears the
    staging folder itself), so the draft ends without dropping it."""
    state = drafts(call.session).get(p.draft_id)
    plan = state.draft.plan
    if not plan.get("profiles_inside"):
        raise OperationError("no_profiles", tr("This download ships no profiles."))
    drafts(call.session).pop(p.draft_id)
    return Handoff(
        unpacked=str(plan["unpacked"]), profiles=list(plan["profiles_inside"]), staging=plan.get("staging") or None
    )


def _finishing(call: Call, p: DraftRef) -> DraftState:
    state = drafts(call.session).get(p.draft_id)
    with state.lock:
        if not state.draft.can_install():
            raise OperationError("not_ready", tr("The install is not ready yet."), {"draft_id": p.draft_id})
    return state


def _check_finish(call: Call, p: DraftRef) -> None:
    idle(call.session)
    _finishing(call, p)


def _finish_title(call: Call, p: DraftRef) -> str:
    state = drafts(call.session).get(p.draft_id)
    with state.lock:
        d = state.draft
        if d.overhaul_mode and state.preview is not None:
            return tr("Installing {name} as an overhaul...").format(name=state.preview.label)
        return tr("Installing {name}...").format(name=d.plan["name"])


class Installed(Result):
    name: str
    overhaul: bool
    update: bool = False


@operation(
    "mods.install_finish",
    params=DraftRef,
    result=Installed,
    kind="job",
    writes=True,
    title=_finish_title,
    check=_check_finish,
)
def install_finish(call: Call, p: DraftRef) -> Installed:
    """Install what the draft says, as one logged job with its Undo in Activity. The draft ends."""
    state = _finishing(call, p)
    d, preview, loc = state.draft, state.preview, call.session.locations()
    mode = d.overhaul_mode
    plan = d.finish()
    if mode == "matched" and state.via_setup:
        mode = "setup"
    drafts(call.session).pop(p.draft_id)
    if mode:
        return _install_overhaul(plan, preview, mode, loc)
    return _install_mod(state.profile, plan, loc)


def _install_mod(profile: Path, plan: dict, loc) -> Installed:
    def body(jloc):
        out = profile_mods.install_and_record(profile, plan, loc=jloc)
        run_logging.log(f"done: {'updated' if out['update'] else 'installed'} {plan['name']}")
        return out

    out = run_logged_job(
        loc, tr("Installing {name}...").format(name=plan["name"]), f"launcher: install mod {plan['name']}", body
    )
    return Installed(name=plan["name"], overhaul=False, update=bool(out["update"]))


def _install_overhaul(plan: dict, preview: Any, mode: str, loc) -> Installed:
    install = mod_service.install_overhaul_setup if mode == "setup" else mod_service.install_overhaul

    def body(jloc):
        try:
            return install(preview, loc=jloc)
        finally:
            drop_staging(plan)

    out = run_logged_job(
        loc,
        tr("Installing {name} as an overhaul...").format(name=preview.label),
        f"launcher: install overhaul {preview.label}",
        body,
    )
    return Installed(name=preview.label, overhaul=True, update=bool(out.get("update")))
