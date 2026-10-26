"""Installing mods into a profile and setting up overhauls: the engine interface the Mods page's install dialog, Take
over and the overhaul menu call. The work itself lives in modules.mods.service and modules.mods.profile_mods. Facts and
actions only: the words (the dialog's, the confirms') are the client's.

shortcut: an open install nobody closes (a client that went away) keeps its unpacked copy until the engine ends; give
them a time to live with the first remote client."""

from __future__ import annotations

import itertools
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic_core import to_jsonable_python

from bayle.adapters.archives import extract as mod_extract
from bayle.adapters.overhauls import basic
from bayle.adapters.system import logging as run_logging
from bayle.adapters.system.threads import assert_not_ui_thread
from bayle.errors import OperationError
from bayle.modules.games.locate import Locations
from bayle.modules.mods import mod_configs, profile_mods
from bayle.modules.mods import service as mod_service
from bayle.modules.mods.mod_configs import SetupValues, logged, stamp
from bayle.work.jobs import JobManager

LOADED = ("game", "regulation", "dll", "files")  # something of these must stay ticked


def drop_staging(plan: dict) -> None:
    if plan.get("staging"):
        shutil.rmtree(plan["staging"], ignore_errors=True)


def setup_notes(config, folder: Path) -> list[str]:
    """What making the setup's steps left out or dropped (entries a newer download no longer has, ...): the notes the
    preview shows. Reads the whole download: not for the UI thread."""
    from bayle.modules.settings import layout

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


def option_of(plan: dict) -> str:
    """What the download is for the overhaul option: plain | suggested | matched | refused."""
    found = plan.get("overhaul")
    if found and found.get("refusal"):
        return "refused"
    if found:
        return "matched"
    return "suggested" if plan.get("overhaul_hint") else "plain"


def plan_facts(plan: dict) -> dict[str, Any]:
    """The plan as JSON-clean facts (paths as text), with its overhaul option."""
    return {**to_jsonable_python(plan, fallback=str), "option": option_of(plan)}


# ----------------------------------------------------------------------------- facts
@dataclass(frozen=True)
class Sources:
    usable: tuple[str, ...]  # folders, .zip / .7z / .rar archives and DLL mods
    skipped: tuple[str, ...]


@dataclass(frozen=True)
class OpenedInstall:
    install_id: str
    plan: dict[str, Any]  # plan_facts
    overhaul_on: bool  # the Settings switch: the overhaul option is offered
    stamp: tuple[int, int] | None  # of the profile; install checks it


@dataclass(frozen=True)
class Handoff:
    unpacked: str
    profiles: tuple[str, ...]
    staging: str | None


@dataclass(frozen=True)
class InstallChoices:
    """What the player set in the install dialog. exclude: the names of the plan's contents left unticked. place_last:
    regulation.bin goes last instead of before the package that must stay last. overhaul: the option is ticked.
    setup: the setup form's values when the player changed them (None: as proposed or saved)."""

    name: str
    id: str = ""
    variant: str | None = None
    exclude: tuple[str, ...] = ()
    place_last: bool = False
    rebuild: bool = True
    after_last: bool = False
    library_choice: str = ""  # here | everywhere (a new version of a Shared mod); separate | share (identical copies)
    overhaul: bool = False
    setup: SetupValues | None = None


@dataclass(frozen=True)
class OverhaulPreview:
    """What installing the open download as an overhaul would do. mode: matched (a config describes it) or setup.
    natives, files and texts are the setup form's rows (empty for a verified config); a texts row with no table
    chosen is also a refusal."""

    mode: str
    lines: tuple[str, ...]
    notes: tuple[str, ...]
    refusals: tuple[str, ...]
    natives: tuple[dict, ...] = ()
    files: tuple[dict, ...] = ()
    texts: tuple[dict, ...] = ()
    editable: bool = False  # the setup form applies (not a verified config)


@dataclass(frozen=True)
class OverhaulPlan:
    """What an overhaul install, removal or take over would do: the client words it and sends stamp back to start it.
    asked: the shared dependencies the option switches back off."""

    label: str
    lines: tuple[str, ...]
    notes: tuple[str, ...]
    refusals: tuple[str, ...]
    asked: tuple[str, ...]
    update: bool
    stamp: tuple[int, int] | None

    @property
    def ok(self) -> bool:
        return not self.refusals


@dataclass(frozen=True)
class OverhaulChoices:
    """The changes an installer made that the player may also choose, by row (the order the next check uses)."""

    label: str
    rows: tuple[str, ...]
    ticked: tuple[int, ...] = ()  # the rows to offer ticked (take over: what the installer copied)


@dataclass(frozen=True)
class LeftoverFolder:
    path: str
    label: str
    size: int


@dataclass(frozen=True)
class Leftovers:
    folders: tuple[LeftoverFolder, ...]
    backups: tuple[LeftoverFolder, ...]  # the installers' profile backups: the only copy from before the overhaul


@dataclass
class _Open:
    plan: dict
    profile: Path
    overhaul_on: bool
    planned: tuple = ()  # (name, id, variant) the plan is for
    lock: threading.Lock = field(default_factory=threading.Lock)


class ModInstallService:
    """Mod installs and overhaul setup for one engine: jobs is its JobManager, locations the current game's Locations (None: no game selected).
    Returns data and OperationError codes, never wording: the Qt page words them.

    An install is opened (the download is unpacked and planned; the engine holds it by install_id until install, close
    or hand_off), planned again for another name, id or variant, previewed as an overhaul and installed with the
    player's InstallChoices. The player's edits stay with the client: everything is sent again with the call that
    needs it. An install, removal or take over is a check (facts, writes nothing) and a start (with the profile's
    stamp the client confirmed; stale when it changed since); the starts are logged jobs with one Undo in Activity,
    their ids are returned and a failed or cancelled one leaves the profile and mod folders as they were."""

    def __init__(self, jobs: JobManager, locations: Callable[[], Locations | None]) -> None:
        self._jobs, self._locations = jobs, locations
        self._lock = threading.Lock()
        self._opens: dict[str, _Open] = {}
        self._ids = itertools.count(1)

    def _loc(self) -> Locations:
        try:
            loc = self._locations()
        except OperationError:
            loc = None
        if loc is None:
            raise OperationError("no_game", "No game is selected.")
        return loc

    @staticmethod
    def _profile(profile: str | Path) -> Path:
        if not profile or not Path(profile).is_file():
            raise OperationError("not_found", "That profile is not there.", {"profile": str(profile)})
        return Path(profile)

    @staticmethod
    def _expect(prof: Path, expect: tuple[int, int] | None) -> None:
        if stamp(prof) != (tuple(expect) if expect is not None else None):
            raise OperationError("stale", "The profile changed since you were asked. Ask again.")

    def _job(self, title: str, log_title: str, work: Callable[[Locations], dict]) -> str:
        """work(loc) as a logged job of its own inside a session job (writing: not while the game or another write
        runs); returns the session job's id."""
        loc = self._loc()
        return self._jobs.start(lambda _ctx: logged(log_title, loc, lambda: work(loc)), title=title, quiet=True)

    # ------------------------------------------------------------------------- the install dialog
    def sources(self, paths: list[str]) -> Sources:
        """Which of the picked or dropped paths can be installed."""
        kinds = (*mod_extract.ARCHIVE_EXTENSIONS, ".dll")
        found = [Path(x) for x in paths]
        usable = [x for x in found if x.is_dir() or x.suffix.lower() in kinds]
        return Sources(tuple(str(x) for x in usable), tuple(str(x) for x in found if x not in usable))

    def _get(self, install_id: str) -> _Open:
        with self._lock:
            state = self._opens.get(install_id)
        if state is None:
            raise OperationError("unknown_install", "That install is no longer open.", {"install_id": install_id})
        return state

    def _pop(self, install_id: str) -> _Open:
        state = self._get(install_id)
        with self._lock:
            self._opens.pop(install_id, None)
        return state

    def open(self, profile: str | Path, source: str | Path) -> OpenedInstall:
        """Unpack and plan a download; it stays open until install, close or hand_off. Heavy: not for the UI thread.
        Raises not_found (the profile or the source), unreadable (the archive can't be read), not_installable (the
        download has nothing to install), already_listed."""
        assert_not_ui_thread("mod_install.open")
        loc, prof, src = self._loc(), self._profile(profile), Path(source)
        if not src.exists():
            raise OperationError("not_found", "That download is not there.", {"name": src.name})
        try:
            plan = mod_service.plan_mod_install(prof, src, loc=loc)
        except Exception as e:  # an archive that can't be read
            raise OperationError("unreadable", str(e), {"name": src.name}) from e
        if plan.get("error"):
            drop_staging(plan)
            raise OperationError("not_installable", str(plan["error"]), {"name": src.name})
        if plan.get("in_place") and plan.get("already_listed") and len(plan["already_listed"]) == len(plan["entries"]):
            drop_staging(plan)
            raise OperationError("already_listed", plan["name"], {"name": plan["name"]})
        state = _Open(plan, prof, mod_service.overhaul_preview_on(loc))
        state.planned = (plan["name"], plan.get("id") or plan["name"], plan.get("variant") or None)
        with self._lock:
            install_id = f"i{next(self._ids)}"
            self._opens[install_id] = state
        return OpenedInstall(install_id, plan_facts(plan), state.overhaul_on, stamp(prof))

    def replan(self, install_id: str, name: str, id: str, variant: str | None) -> dict[str, Any]:
        """Plan again for the typed name, id and variant (nothing is unpacked again); returns the plan's facts. A
        variant that cannot be read raises cannot_plan and the last good plan stays. Heavy: not for the UI thread."""
        assert_not_ui_thread("mod_install.replan")
        state, loc = self._get(install_id), self._loc()
        key = (name.strip(), id.strip(), variant or None)
        with state.lock:
            if key != state.planned:
                try:
                    new = mod_service.replan_mod_install(
                        state.profile, state.plan, key[0] or None, key[1] or None, key[2], loc=loc
                    )
                except Exception as e:
                    raise OperationError("cannot_plan", str(e)) from e
                state.plan, state.planned = new, key
            return plan_facts(state.plan)

    def _mode(self, state: _Open, ticked: bool = True) -> str:
        """ "" (an ordinary install), "matched" (a config already describes it) or "setup" (set it up)."""
        option = option_of(state.plan)
        if not (state.overhaul_on and ticked) or option == "refused":
            return ""
        return "matched" if option == "matched" else "setup"

    def _with_form(self, config, folder: Path, form: SetupValues, loc: Locations):
        """The setup's config with the form's values. Raises ValueError (a texts entry with no table chosen, ...)."""
        choices = mod_configs.overhaul_choices({"config": config, "folder": folder}, loc.game_dir())
        return mod_configs.with_basic(
            config,
            natives=list(form.natives),
            files=mod_configs.files_to_store(choices["files"], form.files),
            tables=form.tables,
        )

    def _overhaul(self, state: _Open, name: str, form: SetupValues | None, loc: Locations):
        """(mode, InstallPreview or None, why not, config, folder) of installing the open download as an overhaul;
        config is the setup's when the form applies (else None). A setup that cannot be previewed is a why-not
        (the form's rows still go with it). Raises what the first read raises: not a download it can set up."""
        mode, plan = self._mode(state), state.plan
        if mode == "matched":
            pv = mod_service.preview_overhaul_install(state.profile, plan["unpacked"], loc=loc)
            folder = pv.found.folder
            config = pv.found.config if mod_service.setup_is_editable(pv.found.config) else None
            if config is not None and form is not None:  # changed in the dialog: installed as a setup, config saved
                config, mode = self._with_form(config, folder, form, loc), "setup"
                pv, why = self._preview_setup(state, folder, config, loc)
                return mode, pv, why, config, folder
            return mode, pv, "", config, folder
        folder = Path(plan["root"])
        config = mod_service.propose_overhaul_setup(folder, name, loc=loc)
        if form is not None:
            config = self._with_form(config, folder, form, loc)
        pv, why = self._preview_setup(state, folder, config, loc)
        return mode, pv, why, config, folder

    @staticmethod
    def _preview_setup(state: _Open, folder: Path, config, loc: Locations) -> tuple[Any, str]:
        try:
            return mod_service.preview_overhaul_setup(state.profile, folder, config, loc=loc), ""
        except Exception as e:  # not one the launcher can set up: the dialog says why
            return None, str(e)

    def check_overhaul(self, install_id: str, name: str, setup: SetupValues | None = None) -> OverhaulPreview:
        """The overhaul preview of the open download, its DLL options, Files table and text tables (the form's rows,
        with setup applied when the player changed them). One that cannot be set up is a refusal in the facts. Heavy:
        reads the whole download, not for the UI thread. Raises unknown_install, not_offered (the option is off or
        refused)."""
        assert_not_ui_thread("mod_install.check_overhaul")
        state, loc = self._get(install_id), self._loc()
        if not self._mode(state):
            raise OperationError("not_offered", "This download cannot be set up as an overhaul.")
        try:
            mode, pv, why, config, folder = self._overhaul(state, name.strip(), setup, loc)
        except Exception as e:  # not a download it can set up at all
            return OverhaulPreview(self._mode(state), (), (), (str(e),))
        lines, notes, refusals = (tuple(pv.lines), tuple(pv.notes), tuple(pv.refusals)) if pv else ((), (), (why,))
        if config is None or config.basic is None:
            return OverhaulPreview(mode, lines, notes, refusals)
        rows = mod_configs.overhaul_choices({"config": config, "folder": Path(folder)}, loc.game_dir())
        return OverhaulPreview(
            mode,
            lines,
            (*notes, *setup_notes(config, Path(folder))),
            refusals,
            tuple(rows["natives"]),
            tuple(rows["files"]),
            tuple(rows["texts"]),
            True,
        )

    def close(self, install_id: str) -> None:
        """The dialog was cancelled: the unpacked copy is dropped."""
        drop_staging(self._pop(install_id).plan)

    def hand_off(self, install_id: str) -> Handoff:
        """The download ships .me3 profiles: the Export / Import page takes over its unpacked folder (and clears the
        staging folder itself), so the install ends without dropping it. Raises unknown_install, no_profiles."""
        plan = self._get(install_id).plan
        if not plan.get("profiles_inside"):
            raise OperationError("no_profiles", "This download ships no profiles.")
        self._pop(install_id)
        return Handoff(
            str(plan["unpacked"]), tuple(plan["profiles_inside"]), plan.get("staging") and str(plan["staging"]) or None
        )

    @staticmethod
    def _not_ready(reason: str, **details: Any) -> OperationError:
        return OperationError("not_ready", "The install is not ready.", {"reason": reason, **details})

    def _check_ready(self, plan: dict, c: InstallChoices, mode: str, overhaul_on: bool) -> None:
        """Raises not_ready (details: reason) when the install cannot go ahead."""
        if plan.get("error"):
            raise self._not_ready("plan_error")
        if not c.name.strip():
            raise self._not_ready("name_blank")
        if mode:
            return
        if option_of(plan) == "refused" and overhaul_on:
            raise self._not_ready("overhaul_refused")
        found = plan.get("library") or {}
        if plan.get("name_problem"):
            raise self._not_ready("name_problem")
        if found.get("blocked"):
            raise self._not_ready("library_blocked")
        if plan["kind"] == "package":
            if not c.id.strip():
                raise self._not_ready("id_blank")
            if plan.get("id_taken"):
                raise self._not_ready("id_taken")
        contents = [] if plan.get("in_place") else plan.get("contents") or []
        if contents and not any(it["name"] not in c.exclude and it["group"] in LOADED for it in contents):
            raise self._not_ready("nothing_loaded")

    @staticmethod
    def _finish(plan: dict, c: InstallChoices, mode: str) -> dict:
        """The plan to install, with 'exclude' (names left out), 'merge', 'insert_before' and 'after_overlay' set."""
        p = dict(plan)
        contents = [] if p.get("in_place") else p.get("contents") or []
        names = [it["name"] for it in contents]
        p["exclude"] = [n for n in names if n in c.exclude]
        others = p.get("regulation_packages") or []
        target = p.get("merge_target") or (others[-1]["name"] if others else None)
        before = None if c.place_last else target
        regulation = p.get("kind") == "package" and "regulation.bin" in names and "regulation.bin" not in c.exclude
        offered = p.get("merge_offered") and regulation
        shown = bool(offered and (p.get("merge_combine") or p.get("already_listed") or before is not None))
        p["merge"] = shown and c.rebuild
        p["insert_before"] = before if regulation and not p.get("already_listed") else None
        p["after_overlay"] = bool(p.get("stay_last")) and c.after_last
        p["library_choice"] = c.library_choice if not mode else ""
        return p

    def install(self, install_id: str, choices: InstallChoices, expect: tuple[int, int] | None) -> str:
        """Install what the player chose, as a job with one Undo in Activity; returns its id. The result is {"name",
        "overhaul", "update"}; the install ends with the job (its unpacked copy is dropped, done or not). expect: the
        profile's stamp from open. Raises unknown_install, stale, cannot_plan, not_ready (details: reason, and
        refusals for an overhaul that cannot be set up), busy."""
        state, loc = self._get(install_id), self._loc()
        self._expect(state.profile, expect)
        c = choices
        if (c.name.strip(), c.id.strip(), c.variant or None) != state.planned:
            self.replan(install_id, c.name, c.id, c.variant)
        plan, mode = state.plan, self._mode(state, c.overhaul)
        self._check_ready(plan, c, mode, state.overhaul_on)
        if mode:
            try:
                mode, preview, why, _config, _folder = self._overhaul(state, c.name.strip(), c.setup, loc)
            except Exception as e:
                raise self._not_ready("overhaul_refused", refusals=[str(e)]) from e
            if preview is None or preview.refusals:
                raise self._not_ready("overhaul_refused", refusals=[why] if preview is None else list(preview.refusals))
            return self._start_overhaul(install_id, state, preview, mode)
        final = self._finish(plan, c, mode)

        def work(jloc: Locations) -> dict:
            self._pop(install_id)
            try:
                out = profile_mods.install_and_record(state.profile, final, loc=jloc)
                run_logging.log(f"done: {'updated' if out['update'] else 'installed'} {final['name']}")
            finally:
                drop_staging(plan)
            return {"name": final["name"], "overhaul": False, "update": bool(out["update"])}

        return self._job(
            "Installing {name}...".format(name=final["name"]), f"launcher: install mod {final['name']}", work
        )

    def _start_overhaul(self, install_id: str, state: _Open, preview: Any, mode: str) -> str:
        install = mod_service.install_overhaul_setup if mode == "setup" else mod_service.install_overhaul
        plan = state.plan

        def work(jloc: Locations) -> dict:
            self._pop(install_id)
            try:
                out = install(preview, loc=jloc)
            finally:
                drop_staging(plan)
            return {"name": preview.label, "overhaul": True, "update": bool(out.get("update"))}

        return self._job(
            f"Installing {preview.label} as an overhaul...",
            f"launcher: install overhaul {preview.label}",
            work,
        )

    # ------------------------------------------------------------------------- the overhaul menu
    def _overhaul_of(self, profile: str | Path) -> dict:
        """The overhaul the profile has: {label, legacy, takeover, ...}. Raises not_found, no_overhaul."""
        has = mod_service.profile_overhaul(self._profile(profile), loc=self._loc())
        if has is None:
            raise OperationError("no_overhaul", "This profile has no overhaul the launcher knows.")
        return has

    def _plan(self, prof: Path, label: str, pv: Any) -> OverhaulPlan:
        return OverhaulPlan(
            label,
            tuple(pv.lines),
            tuple(getattr(pv, "notes", ())),
            tuple(pv.refusals),
            tuple(str(e.entry) for e in getattr(pv, "asked", ())),
            bool(getattr(pv, "update", False)),
            stamp(prof),
        )

    def _install_preview(self, prof: Path, folder: str | Path):
        if not folder or not Path(folder).is_dir():
            raise OperationError("not_found", "That folder is not there.", {"folder": str(folder)})
        try:
            return mod_service.preview_overhaul_install(prof, folder, loc=self._loc())
        except Exception as e:  # not a download the launcher installs
            raise OperationError("unreadable", str(e), {"name": Path(folder).name}) from e

    def check_overhaul_install(self, profile: str | Path, folder: str | Path) -> OverhaulPlan:
        """What installing an overhaul from the folder it was unpacked into would do (writes nothing). Raises
        not_found, unreadable (not a download the launcher installs)."""
        prof = self._profile(profile)
        pv = self._install_preview(prof, folder)
        return self._plan(prof, pv.label, pv)

    def install_overhaul(self, profile: str | Path, folder: str | Path, expect: tuple[int, int] | None) -> str:
        """Install the overhaul as a job with one Undo; returns its id. Raises not_found, unreadable, stale,
        cannot_install (details: refusals), busy."""
        prof = self._profile(profile)
        pv = self._install_preview(prof, folder)
        if not pv.ok:
            raise OperationError("cannot_install", " ".join(pv.refusals), {"refusals": list(pv.refusals)})
        self._expect(prof, expect)
        verb = "update" if pv.update else "install"
        title = ("Updating {label}..." if pv.update else "Installing {label}...").format(label=pv.label)

        def work(jloc: Locations) -> dict:
            mod_service.install_overhaul(pv, loc=jloc)
            return {"note": f"installed {pv.label}"}

        return self._job(title, f"launcher: {verb} overhaul {pv.label}", work)

    def remove_choices(self, profile: str | Path) -> OverhaulChoices:
        """For an overhaul its own installer set up: the changes it made that can be put back (none to offer: no
        rows). Raises not_found, no_overhaul."""
        has = self._overhaul_of(profile)
        found = mod_service.legacy_overhaul_choices(Path(profile), loc=self._loc()) if has["legacy"] else []
        return OverhaulChoices(has["label"], tuple(text for text, _ in found))

    def _removal(self, prof: Path, chosen: list[int], revert: bool):
        has = self._overhaul_of(prof)
        found = mod_service.legacy_overhaul_choices(prof, loc=self._loc()) if has["legacy"] else []
        picked = [found[i][1] for i in chosen if 0 <= i < len(found)]
        try:
            return has["label"], mod_service.preview_overhaul_removal(
                prof, loc=self._loc(), revert_asked=revert, legacy_choices=picked
            )
        except Exception as e:
            raise OperationError("cannot_remove", str(e), {"label": has["label"]}) from e

    def check_overhaul_remove(self, profile: str | Path, chosen: list[int]) -> OverhaulPlan:
        """What removing the profile's overhaul would do (writes nothing); chosen: the rows of remove_choices to put
        back. Raises not_found, no_overhaul, cannot_remove."""
        prof = self._profile(profile)
        label, pv = self._removal(prof, chosen, False)
        return self._plan(prof, label, pv)

    def remove_overhaul(
        self, profile: str | Path, chosen: list[int], revert: bool, expect: tuple[int, int] | None
    ) -> str:
        """Remove the profile's overhaul as a job with one Undo; returns its id. revert: also switch the shared
        dependencies check_overhaul_remove named (asked) back off. Raises not_found, no_overhaul, stale,
        cannot_remove (details: refusals), busy."""
        prof = self._profile(profile)
        label, pv = self._removal(prof, chosen, revert)
        if not pv.ok:
            raise OperationError("cannot_remove", " ".join(pv.refusals), {"refusals": list(pv.refusals)})
        self._expect(prof, expect)

        def work(_loc: Locations) -> dict:
            mod_service.remove_overhaul(pv)
            return {"note": f"removed {label}"}

        return self._job(f"Removing {label}...", f"launcher: remove overhaul {label}", work)

    def take_over_choices(self, profile: str | Path) -> OverhaulChoices:
        """For Take over: what the player may also choose (a change to put back, or the installer's backups), the
        entries the installer copied offered ticked. Raises not_found, no_overhaul, no_takeover."""
        has = self._overhaul_of(profile)
        if not has.get("takeover"):
            raise OperationError("no_takeover", "The launcher made this setup, so there is nothing to take over.")
        found = mod_service.take_over_choices(Path(profile), loc=self._loc())
        ticked = tuple(i for i, c in enumerate(found) if getattr(c, "copied", False))
        return OverhaulChoices(has["label"], tuple(mod_service.choice_text(c) for c in found), ticked)

    def _take_over(self, prof: Path, chosen: list[int], revert: bool):
        has = self._overhaul_of(prof)
        found = mod_service.take_over_choices(prof, loc=self._loc())
        picked = [found[i] for i in chosen if 0 <= i < len(found)]
        try:
            return has["label"], mod_service.preview_take_over(
                prof, loc=self._loc(), chosen=picked, revert_asked=revert
            )
        except Exception as e:
            raise OperationError("cannot_take_over", str(e), {"label": has["label"]}) from e

    def check_take_over(self, profile: str | Path, chosen: list[int]) -> OverhaulPlan:
        """What taking over a setup its own installer made would do (writes nothing); chosen: the rows of
        take_over_choices. Raises not_found, no_overhaul, cannot_take_over."""
        prof = self._profile(profile)
        label, pv = self._take_over(prof, chosen, False)
        return self._plan(prof, label, pv)

    def take_over(self, profile: str | Path, chosen: list[int], revert: bool, expect: tuple[int, int] | None) -> str:
        """Take the setup over as a job with one Undo; returns its id. revert: as remove_overhaul. Raises not_found,
        no_overhaul, stale, cannot_take_over (details: refusals), busy."""
        prof = self._profile(profile)
        label, pv = self._take_over(prof, chosen, revert)
        if not pv.ok:
            raise OperationError("cannot_take_over", " ".join(pv.refusals), {"refusals": list(pv.refusals)})
        self._expect(prof, expect)

        def work(_loc: Locations) -> dict:
            mod_service.remove_overhaul(pv)
            return {"note": f"took over {label}"}

        return self._job(f"Taking over {label}...", f"launcher: take over overhaul {label}", work)

    def leftovers(self, profile: str | Path) -> Leftovers:
        """What overhauls' own installers left beside the profile that no profile uses any more."""
        left = mod_service.overhaul_leftovers(self._profile(profile), loc=self._loc())

        def rows(backups: bool) -> tuple[LeftoverFolder, ...]:
            return tuple(LeftoverFolder(str(x.path), x.label, x.size) for x in left if x.backups is backups)

        return Leftovers(rows(False), rows(True))

    def clean_leftovers(self, profile: str | Path, paths: list[str]) -> str:
        """Send the chosen leftovers (leftovers' own, nothing else) to the Recycle Bin as a job; returns its id.
        Raises not_found, nothing_chosen, busy."""
        if not paths:
            raise OperationError("nothing_chosen", "Nothing was chosen.")
        left = mod_service.overhaul_leftovers(self._profile(profile), loc=self._loc())
        listed = {str(x.path): x.path for x in left}
        missing = [p for p in paths if str(p) not in listed]
        if missing:
            raise OperationError("not_found", "That is not a leftover of this profile.", {"paths": missing})
        chosen = [listed[str(p)] for p in paths]

        def work(_loc: Locations) -> dict:
            mod_service.remove_overhaul_leftovers(chosen)
            return {"note": f"{len(chosen)} moved to the Recycle Bin"}

        return self._job(
            "Moving leftovers to the Recycle Bin...", "launcher: clean up overhaul installer leftovers", work
        )
