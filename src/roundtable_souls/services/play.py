"""Play: the setups a game can launch (me3 profiles, launchers' installation.json), the play session jobs (online,
offline, repair, cleanup), play without the window (--play, --check), and error reporting. Co-op, saves, mods,
settings and updates have services modules of their own."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from roundtable_souls import __version__, overhauls
from roundtable_souls.config.settings import (
    FROZEN,
    LauncherSettings,
    exe_dir,
    game_setting,
    launch_target,
    load_settings,
    save_game_settings,
)
from roundtable_souls.coop.ini import (
    coop_ini_for,
    has_password,
    read_keys,
    read_password,
)
from roundtable_souls.coop.scaling import (
    preset_of,
    read_scaling,
    scaling_spec,
)
from roundtable_souls.game import catalog as games
from roundtable_souls.game.locate import Locations, installed_dir
from roundtable_souls.mods import operations as mod_operations
from roundtable_souls.mods import profile as profile_tools
from roundtable_souls.mods import profile_edit as mod_manage
from roundtable_souls.mods import rebuild as mod_merge
from roundtable_souls.platform import desktop, me3_info, paths, steam
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.platform import session as me3_session
from roundtable_souls.platform.files import (
    atomic_write,
)
from roundtable_souls.resources import ASSETS_DIR
from roundtable_souls.saves import analyze as save_analyze
from roundtable_souls.saves import fix as save_fix
from roundtable_souls.saves import repair as save_repair
from roundtable_souls.services import game_checks
from roundtable_souls.services.saves import (
    save_info,
)


def report_exception(exc_type, exc, tb, where="launcher"):
    """Every uncaught error, in the UI thread or a worker: to logs/launcher.log with its traceback (and the running
    job's log), then a message box."""
    run_logging.log_crash(exc_type, exc, tb, where)
    if NOTIFY is not None:
        try:
            NOTIFY(TITLE, "Something went wrong:\n" + str(exc) + "\n\nDetails are in logs\\launcher.log")
        except Exception:
            pass


TITLE = "Roundtable Souls"
VERSION = __version__
EXE_NAME = "RoundtableSouls"
NOTIFY = None  # the window sets this to a function (title, message) that shows an error to the user


def logo_kind(theme_dark: bool, logo: str = "auto") -> str:
    """Which mark to show. auto follows the window theme; dark and light stay put."""
    if logo == "light":
        return "light"
    if logo == "dark":
        return "dark"
    return "dark" if theme_dark else "light"


def logo_path(theme_dark: bool, logo: str = "auto") -> Path:
    p = ASSETS_DIR / f"logo-{logo_kind(theme_dark, logo)}.png"
    return p if p.is_file() else ASSETS_DIR / "icon.ico"


class LaunchProfile:
    """What to launch and how. kind: 'me3' (installed me3, --game) or 'manifest' (an overhaul installer's manifest,
    installation.json, --exe).
    loc: where the game it launches is on this machine (its game is loc.game)."""

    def __init__(self, kind, profile, me3=None, exe=None, source=None, ini=None, *, loc: Locations):
        self.kind, self.profile, self.me3, self.exe, self.source = kind, str(profile), me3, exe, str(source or profile)
        self.loc = loc
        self._ini = ini

    @property
    def game(self) -> games.Game:
        return self.loc.game

    def locations(self) -> Locations:
        """The game's locations with the save files this setup uses (me3's savefile, Seamless Co-op's extension)."""
        names = profile_saves(self)
        return self.loc.with_profile_save_names({k: names[k] for k in ("standard", "coop")})

    @property
    def ini(self):
        """The Seamless Co-op ini this profile loads. Found on first use: discover() builds a Setup for every
        profile on disk, and reading each one there made every game-tab switch pay for inis nobody asked about."""
        if self._ini is None:
            self._ini = coop_ini_for(self.profile, self.game) or False  # False: looked, this profile has none
        return self._ini or None

    @property
    def label(self):
        name = Path(self.profile).name
        if self.kind == "manifest":
            return f"{name}  ·  installation.json"
        return name

    def me3_path(self):
        return Path(self.me3) if self.me3 else self.loc.me3_exe()

    def summary(self):
        me3 = self.me3_path()
        game = Path(self.exe).name if self.exe else f"{self.game.name} (Steam)"
        return f"me3: {me3 if me3 else 'not found'}    game: {game}"

    def problems(self):
        out = []
        if not Path(self.profile).is_file():
            out.append(f"profile missing: {self.profile}")
        elif self.kind == "me3":
            named = paths.profile_games(Path(self.profile))
            if named and self.game.key not in named:
                other = ", ".join(games.get(k).name if k in games.BY_KEY else k for k in named)
                out.append(f"this profile is for {other}, not {self.game.name}")
        if Path(self.profile).is_file():
            unfinished = mod_operations.problem(Path(self.profile))  # an incomplete managed setup: no Play anyway
            if unfinished:
                out.append(unfinished)
        if self.me3 and not Path(self.me3).is_file():
            out.append(f"me3 missing: {self.me3}")
        if not self.me3 and not self.loc.me3_exe():
            out.append("me3 is not installed on this PC (not on PATH, not in its default folder, not set in Settings)")
        if self.exe and not Path(self.exe).is_file():
            out.append(f"game exe missing: {self.exe}")
        custom = self.loc.overrides.game_exe
        if custom and not Path(custom).is_file():
            out.append(f"game exe set in Settings is missing: {custom}")
        return out

    def warnings(self):
        """What will not stop Play but leaves a mod out: a mod folder that is gone (me3 skips it)."""
        p = Path(self.profile)
        if self.kind != "me3" or not p.is_file():
            return []
        try:
            rows = profile_tools.package_rows(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return []
        return [f"{r['id']} folder is missing" for r in rows if not mod_manage.resolve(p, r["path"]).is_dir()]

    def launch_exe(self):
        """What me3 launches with --exe: the installation's own exe, else the custom exe from Settings, else Steam (--game)."""
        return self.exe or self.loc.overrides.game_exe or None


def launch_profile_from_installation(path: Path, loc: Locations) -> LaunchProfile | None:
    try:
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    if not cfg.get("profile"):
        return None
    ini = None
    if cfg.get("seamless"):
        cand = Path(cfg["seamless"]).parent / "ersc_settings.ini"
        if cand.is_file():
            ini = cand
    return LaunchProfile("manifest", cfg["profile"], cfg.get("me3"), cfg.get("game"), source=path, ini=ini, loc=loc)


def same_source(a, b) -> bool:
    """Whether two setup sources name the same file. Sources travel as strings (the combo list, the remembered
    setup in settings), so every comparison ignores case and slash direction the same way, here."""
    return bool(a) and bool(b) and os.path.normcase(str(a)) == os.path.normcase(str(b))


def launch_profile_from_path(p: str | Path, loc: Locations) -> LaunchProfile | None:
    """A setup for a picked file: a .me3 profile, or an overhaul's installer manifest (installation.json) for a game
    it has a config for."""
    p = Path(p)
    if p.name.lower() in {o.recognise.manifest.lower() for o in overhauls.load()}:
        manifests = {o.recognise.manifest.lower() for o in overhauls.load(loc.game.key)}
        return launch_profile_from_installation(p, loc) if p.name.lower() in manifests else None
    if p.suffix.lower() == ".me3" and p.is_file():
        return LaunchProfile("me3", p, loc=loc)
    return None


def discover(remembered: str | None, loc: Locations):
    """loc's game's me3 profiles (+ the remembered one), and every installation of an overhaul with a config for the
    game (data/overhauls) in its folder next to them or in the game folder (the overhaul is an Elden Ring mod
    despite its name)."""
    found, seen = [], set()
    places = [(o.recognise.folder, o.recognise.manifest) for o in overhauls.load(loc.game.key)]

    def add(s):
        key = os.path.normcase(s.source) if s else None
        if s and key not in seen:
            seen.add(key)
            found.append(s)

    if remembered:
        add(launch_profile_from_path(remembered, loc))
    for prof in loc.me3_profiles():
        if prof.name.lower().endswith(".offline.me3"):
            continue  # our own generated copies
        add(LaunchProfile("me3", prof, loc=loc))
        for folder, manifest in places:
            inst = prof.parent / folder / manifest
            if inst.is_file():
                add(launch_profile_from_installation(inst, loc))
    if not places:
        return found
    # an edition may install into the game folder itself (the overhaul's Standalone: Launch.cmd next to eldenring.exe)
    try:
        gd = loc.game_dir()
    except Exception:
        gd = None
    if gd:
        for folder, manifest in places:
            inst = Path(gd) / folder / manifest
            if inst.is_file():
                add(launch_profile_from_installation(inst, loc))
    return found


def overhauls_in(launch: LaunchProfile) -> list[str]:
    """The short labels of the overhauls a setup includes: launched from one's manifest, its folder beside the
    profile, or one of its entries in the profile. Every config is asked, whatever the setup's game, as before S3a."""
    from roundtable_souls.services.mods import read_profile_mods

    profile = Path(launch.profile)
    ids = {m["id"].lower() for m in read_profile_mods(profile)} if profile.is_file() else set()
    source = Path(launch.source).name.lower() if launch.source else ""
    out = []
    for o in overhauls.load():
        r = o.recognise
        if (
            (launch.kind == "manifest" and source == r.manifest.lower())
            or (profile.parent / r.folder).is_dir()
            or ids & {i.lower() for i in r.mod_ids}
        ):
            out.append(o.short_label)
    return out


def remembered_profile(settings: LauncherSettings | None, game: games.Game) -> str | None:
    """The setup Play last used for the game."""
    s = load_settings() if settings is None else settings
    return game_setting(s, game.key, "setup")


def remember_profile(source: str, game: games.Game) -> None:
    save_game_settings(game.key, setup=source)


def forget_profile(game: games.Game) -> None:
    """Drop the setup Play remembered for the game (its profile was deleted, say)."""
    save_game_settings(game.key, setup=None)


def profile_saves(launch: LaunchProfile | None, game: games.Game | None = None) -> dict:
    """The save files a setup plays on, by name in the account's save folder:

    standard  what the game writes: me3's per-profile savefile, else ER0000.sl2 (NR0000.sl2, ...).
    coop      what Seamless Co-op writes instead, when the setup loads it: the standard name with Seamless's
              save_file_extension (co2 unless changed in its ini). None without Seamless.
    active    the one Play uses (co-op when Seamless is loaded; Play offline always uses the standard one).
    why       role -> where the name comes from, for the Saves page.
    game: the game without a setup."""
    game = launch.game if launch else game
    if game is None:
        raise ValueError("setup or game required")
    standard = f"{game.save_stem}.sl2"
    why = {"standard": "the game's default"}
    if launch and Path(launch.profile).is_file():
        try:
            named = profile_tools.read_settings(Path(launch.profile).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            named = {}
        if named.get("savefile"):
            standard = str(named["savefile"])
            why["standard"] = f"savefile in {Path(launch.profile).name}"
    coop_name = None
    if launch and launch.ini and Path(launch.ini).is_file():
        ext = (read_keys(launch.ini, ["save_file_extension"]).get("save_file_extension") or "co2").strip().lstrip(".")
        coop_name = f"{Path(standard).stem}.{ext or 'co2'}"
        why["coop"] = f"save_file_extension in {Path(launch.ini).name}" if ext != "co2" else "Seamless Co-op's default"
    return {"standard": standard, "coop": coop_name, "active": coop_name or standard, "why": why}


PLAY_KEYS = (
    "play_update_merge",
    "build_merges",
    "play_backup_before",
    "play_repair_after",
    "play_repair_after_eldenring",
    "play_clear_before",
    "play_clear_after",
    "warn_dead_shells",
    "play_boot_boost",
    "play_show_logos",
    "play_diagnostics",
    "check_me3_updates",
)
PLAY_DEFAULTS = {k: LauncherSettings.model_fields[k].default for k in PLAY_KEYS}  # the settings' own defaults


FLAGS_SINCE = (0, 13, 0)  # --no-boot-boost / --show-logos / --diagnostics as used here exist from me3 0.13


def launch_extra_args(opts: dict, version: str | None = None) -> list:
    """me3 launch flags from the Play session options. A me3 older than 0.13 (a the overhaul bundle, say) gets none,
    so an unknown flag can never stop the launch; an unknown version is treated as current."""
    args = []
    if not opts.get("play_boot_boost", True):
        args.append("--no-boot-boost")
    if opts.get("play_show_logos"):
        args.append("--show-logos")
    if opts.get("play_diagnostics"):
        args.append("--diagnostics")
    v = me3_info.version_tuple(version)
    if args and v and v < FLAGS_SINCE:
        run_logging.log(
            f"me3 {version} is older than {'.'.join(map(str, FLAGS_SINCE))}: launch flags {' '.join(args)} skipped"
        )
        return []
    return args


def play_options(settings: LauncherSettings | None = None) -> dict:
    s = load_settings() if settings is None else settings
    return {k: bool(getattr(s, k)) for k in PLAY_DEFAULTS}  # a null in the file is the default (LauncherSettings)


class BackupBeforePlayFailed(RuntimeError):
    """'Back up saves before Play' is on and a save could not be backed up, so the game was not started.
    failed: [(save, why)]."""

    def __init__(self, failed: list[tuple[Path, str]]):
        self.failed = failed
        super().__init__("; ".join(f"{p.name}: {why}" for p, why in failed))


def backup_saves_before_play(loc: Locations, required: bool = False) -> list:
    """One dated copy of every save of loc's game, tagged 'Backup before Play'. required: raise
    BackupBeforePlayFailed when any save could not be backed up (the others are kept)."""
    made, failed = [], []
    for p in loc.save_files():
        try:
            made.append(save_fix.backup(p, {"action": "Before playing", "changes": []}))
            run_logging.log(f"backup: {made[-1]}")
        except OSError as e:
            run_logging.log(f"backup failed for {p.name}: {e}")
            failed.append((Path(p), str(e)))
    if failed and required:
        raise BackupBeforePlayFailed(failed)
    return made


# How Play treats 'Back up saves before Play' (when it is on). A failed backup never launches the game silently:
BACKUP_REQUIRED = "required"  # back up; when it fails, raise BackupBeforePlayFailed and don't start the game
BACKUP_ALLOW_FAILURE = "allow-failure"  # back up; when it fails, log it and start anyway (--allow-without-backup)
BACKUP_SKIP = "skip"  # the caller dealt with it: the window backed up already, or the player chose to go without


def _backup_before_play(opts: dict, loc: Locations, backup: str) -> None:
    if not opts["play_backup_before"]:
        return
    if backup == BACKUP_SKIP:
        return
    try:
        backup_saves_before_play(loc, required=True)
    except BackupBeforePlayFailed as e:
        if backup != BACKUP_ALLOW_FAILURE:
            run_logging.log(f"error: the game was not started: a backup before Play failed ({e})")
            raise
        run_logging.log(f"warning: starting without a backup of every save, as asked ({e})")


def places(launch, loc: Locations) -> dict:
    """Folders worth a button: me3, game, saves, this setup's profile and its mod folder. Missing ones are None."""
    out: dict[str, Path | None] = {"me3": None, "game": None, "saves": None, "profile": None, "mods": None}
    try:
        me3 = launch.me3_path() if launch else loc.me3_exe()
        if me3 and Path(me3).is_file():
            out["me3"] = Path(me3).parent
    except Exception:
        pass
    try:
        g = loc.game_dir()
        if g and Path(g).is_dir():
            out["game"] = Path(g)
    except Exception:
        pass
    try:
        saves = loc.save_files()
        if saves:
            out["saves"] = saves[0].parent
        else:
            roots = [r for r in loc.save_roots() if r.is_dir()]
            if roots:
                out["saves"] = roots[0]
    except Exception:
        pass
    if launch and Path(launch.profile).is_file():
        out["profile"] = Path(launch.profile).parent
        try:
            text = Path(launch.profile).read_bytes().decode("utf-8", "replace")
            pk, _nt = mod_manage.roots(Path(launch.profile), text)
            out["mods"] = pk if pk.is_dir() else out["profile"]
        except Exception:
            out["mods"] = out["profile"]
    return out


def repair_key(game) -> str:
    """The setting that turns the after-Play save repair on for this game. Elden Ring's has its own key (off by
    default: the game never reads the save's regulation copy back; only save editors do); Nightreign's re-signs
    sections me3 can leave unsigned and stays on by default."""
    return "play_repair_after_eldenring" if game is games.ELDEN_RING else "play_repair_after"


def _me3_said() -> None:
    """me3's own log of the launch just ended: what its fast loading failing means for the player (backlog M1)."""
    try:
        text = me3_session.me3_log_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for said in game_checks.me3_mount_failures(text):
        run_logging.log(f"warning: {said}")


def _after_play(opts, loc: Locations):
    _me3_said()
    if not loc.game.regulation_repair:
        pass  # this game has no regulation block me3 leaves dirty
    elif opts[repair_key(loc.game)]:
        save_repair.repair_all(loc)
    else:
        run_logging.log("repair after quitting is off (Settings > Launch)")
    if opts["play_clear_after"]:
        me3_session.clear_dead_shells(loc.game_exe_name(), "after exit")
    else:
        run_logging.log("clearing leftover processes after quitting is off (Settings > Launch)")


def job_play(launch: LaunchProfile, loc: Locations | None = None, backup: str = BACKUP_REQUIRED):
    """Play online. loc: the game's locations (default: the setup's, with the saves it uses). backup: how a failed
    'back up saves before Play' is handled (BACKUP_*)."""
    loc = loc or launch.locations()
    run_logging.start_log("launcher: play", loc.game.key)
    opts = play_options()
    _backup_before_play(opts, loc, backup)
    me3_session.ensure_steam(120)
    if opts["play_clear_before"]:
        me3_session.clear_dead_shells(loc.game_exe_name(), "before launch")
    online = game_checks.online_warning(Path(launch.profile), loc)
    if online is not None:
        run_logging.log(f"warning: {online}")
    me3_session.launch(
        launch.game.key,
        launch.profile,
        me3=launch.me3_path(),
        exe_name=loc.game_exe_name(),
        exe=launch.launch_exe(),
        extra_args=launch_extra_args(opts, me3_info.me3_version(launch.me3_path())),
    )
    time.sleep(3)
    _after_play(opts, loc)


NATIVE_BLOCK_RE = re.compile(r"(^[ \t]*\[\[natives\]\].*?)(?=^[ \t]*\[\[|\Z)", re.M | re.S)
PACKAGE_BLOCK_RE = re.compile(r"(^[ \t]*\[\[packages\]\].*?)(?=^[ \t]*\[\[|\Z)", re.M | re.S)


def overhaul_mark() -> re.Pattern | None:
    """Text marking a profile entry as an overhaul's own (its config's profile_marks), or None when none has marks."""
    marks = [m for o in overhauls.load() for m in o.recognise.profile_marks if m]
    return re.compile("|".join(re.escape(m) for m in marks), re.I) if marks else None


def _comment_block(block: str) -> str:
    return "".join(
        ("# " + ln if ln.strip() and not ln.lstrip().startswith("#") else ln) for ln in block.splitlines(keepends=True)
    )


def _ensure_disabled(body: str) -> str:
    if re.search(r"enabled\s*=\s*false", body, re.I):
        return body
    if re.search(r"enabled\s*=\s*true", body, re.I):
        return re.sub(r"enabled\s*=\s*true", "enabled = false", body, count=1, flags=re.I)
    return "{ enabled = false, " + body[1:]


def _disable_objects_matching(text: str, mark) -> str:
    """Set enabled = false on { ... } objects whose path matches, including nested braces."""
    i, n, out = 0, len(text), []
    while i < n:
        if text[i] != "{":
            out.append(text[i])
            i += 1
            continue
        depth, j = 0, i
        while j < n:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    body = text[i : j + 1]
                    if mark.search(body) and re.search(r"path\s*=", body, re.I):
                        body = _ensure_disabled(body)
                    out.append(body)
                    i = j + 1
                    break
            j += 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def offline_profile_text(text: str, strip_overhaul: bool = False, coop_dll: str | None = "ersc.dll") -> str:
    """A throwaway copy of the me3 profile with Seamless (and optionally the overhaul) and online play turned off.
    Seamless refuses to run without a signed-in, online Steam; without it the game uses the standard save.
    coop_dll: the game's Seamless Co-op dll (ersc.dll for Elden Ring, nrsc.dll for Nightreign)."""
    dll = (coop_dll or "").lower()

    def strip_coop(m):
        block = m.group(1)
        if not dll or dll not in block.lower():
            return block
        return _comment_block(block)

    out = NATIVE_BLOCK_RE.sub(strip_coop, text)
    if dll:
        out = re.sub(
            r"\{[^{}]*path\s*=\s*['\"][^'\"]*" + re.escape(dll) + r"['\"][^{}]*\}",
            lambda m: _ensure_disabled(m.group(0)),
            out,
            flags=re.I,
        )
    mark = overhaul_mark() if strip_overhaul else None
    if mark:

        def strip_rev(m):
            block = m.group(1)
            if not mark.search(block):
                return block
            return _comment_block(block)

        out = NATIVE_BLOCK_RE.sub(strip_rev, out)
        out = PACKAGE_BLOCK_RE.sub(strip_rev, out)
        out = _disable_objects_matching(out, mark)
    out = profile_tools.set_setting(out, "start_online", False)  # "Offline" must never go online
    note = "Seamless Co-op disabled."
    if strip_overhaul:
        note += " the overhaul disabled."
    return f"# OFFLINE COPY written by the launcher: {note} Regenerated on every offline launch.\n" + out


def offline_profile_for(profile: str, strip_overhaul: bool = False, coop_dll: str | None = "ersc.dll") -> Path:
    """Write <profile>.offline.me3 next to the profile (relative paths keep working) and return it."""
    src = Path(profile)
    dst = src.with_name(src.stem + ".offline.me3")
    atomic_write(
        dst,
        offline_profile_text(
            src.read_text(encoding="utf-8", errors="replace"), strip_overhaul=strip_overhaul, coop_dll=coop_dll
        ),
    )
    return dst


def steam_state():
    """(running, signed_in) from the process list and Steam's own registry flag."""
    try:
        running = steam.steam_running()
    except Exception:
        running = False
    try:
        signed = bool(steam.steam_logged_in())
    except Exception:
        signed = False
    return running, signed


def job_play_offline(
    launch, loc: Locations | None = None, strip_overhaul=False, start_steam=True, backup: str = BACKUP_REQUIRED
):
    loc = loc or launch.locations()
    run_logging.start_log("launcher: play offline", loc.game.key)
    opts = play_options()
    _backup_before_play(opts, loc, backup)
    if start_steam:
        me3_session.ensure_steam_running(60)
    if opts["play_clear_before"]:
        me3_session.clear_dead_shells(loc.game_exe_name(), "before launch")
    me3_session.launch(
        launch.game.key,
        str(offline_profile_for(launch.profile, strip_overhaul=strip_overhaul, coop_dll=launch.game.coop_dll)),
        me3=launch.me3_path(),
        exe_name=loc.game_exe_name(),
        exe=launch.launch_exe(),
        extra_args=("--skip-steam-init", "true", *launch_extra_args(opts, me3_info.me3_version(launch.me3_path()))),
    )
    time.sleep(3)
    _after_play(opts, loc)


def job_play_vanilla(launch, loc: Locations | None = None, backup: str = BACKUP_REQUIRED):
    """Launch Vanilla: the game started through Steam, with no me3 and no profile, so it plays the standard save with
    its own anti-cheat (game model, 2026-10-20). Nothing of a profile is read or written, and the after-Play
    regulation repair is not run: me3 did not touch the save. setup is not used (the caller may pass none)."""
    if loc is None:
        raise ValueError("a vanilla launch needs the game's locations")
    run_logging.start_log("launcher: play vanilla", loc.game.key)
    opts = play_options()
    _backup_before_play(opts, loc, backup)
    me3_session.ensure_steam(120)
    if opts["play_clear_before"]:
        me3_session.clear_dead_shells(loc.game_exe_name(), "before launch")
    run_logging.log(f"launching {loc.game.name} through Steam, without me3")
    desktop.open_path(f"steam://rungameid/{loc.game.app_id}")
    if not me3_session.wait_for_game(loc.game_exe_name(), appear_timeout=90):
        run_logging.log("warning: the game never appeared; Steam's own window says why")
    if opts["play_clear_after"]:
        me3_session.clear_dead_shells(loc.game_exe_name(), "after exit")


def job_repair(launch, loc: Locations):
    run_logging.start_log("launcher: repair", loc.game.key)
    save_repair.repair_all(loc)


def job_clear(launch, loc: Locations):
    run_logging.start_log("launcher: clear dead shells", loc.game.key)
    me3_session.clear_dead_shells(loc.game_exe_name(), "manual")


def play_command(game: games.Game) -> tuple[str, str]:
    """(target, launch options) for a Steam shortcut that runs Play for one game without the window."""
    opts = f"--game {game.key} --play"
    if FROZEN:
        return str(launch_target()), opts  # the stub or AppImage: its path stays the same across updates
    return sys.executable, f"-m roundtable_souls {opts}"


def game_from_args(argv: list[str], settings: LauncherSettings | None = None) -> games.Game | None:
    """The game `--game <name>` (or `--game=<name>`) asks for; without the flag, the tab the window last showed.
    None when the name is unknown."""
    value = None
    for i, arg in enumerate(argv):
        if arg == "--game":
            value = argv[i + 1] if i + 1 < len(argv) else ""
        elif arg.startswith("--game="):
            value = arg.split("=", 1)[1]
    if value is None:
        s = load_settings() if settings is None else settings
        return games.get(s.game)
    return games.resolve(value)


def play_headless(
    settings: LauncherSettings,
    loc: Locations,
    notice: Callable[..., None] | None = None,
    allow_without_backup: bool = False,
) -> int:
    """`roundtable-souls --game <name> --play`: the Play button without the window, for one game. Uses the setup
    Play last used for that game (or the only one), runs the same session (Steam, me3, wait, save repair, cleanup)
    and exits. For Steam shortcuts and Gaming Mode. notice(game, why[, headline]) tells the player when the game was
    not started (the command line passes one that shows a small window). loc: where the game to play is. With
    'back up saves before Play' on, a failed backup stops here (nothing can ask) unless allow_without_backup
    (--allow-without-backup): then it is logged and the game starts."""
    game = loc.game
    if not game.ready:
        run_logging.start_log("launcher: play (no window)", game.key)
        run_logging.log(f"error: Roundtable Souls cannot launch {game.name} yet")
        return 1
    remembered = remembered_profile(settings, game)
    if remembered and Path(remembered).is_file():
        try:
            mod_operations.recover(Path(remembered))  # an install the window left half done: undone first
        except Exception:
            pass  # then problems() says why Play cannot start
    launch_profiles = [s for s in discover(remembered, loc) if not s.problems()]
    launch = next(
        (s for s in launch_profiles if same_source(s.source, remembered)),
        launch_profiles[0] if launch_profiles else None,
    )
    if launch is None:
        run_logging.start_log("launcher: play (no window)", game.key)
        run_logging.log(
            f"error: no working {game.name} setup found; open Roundtable Souls once, pick the {game.name} tab, "
            "and choose one on the Play page"
        )
        return 1
    why = update_merge_headless(launch, automatic=play_options(settings)["play_update_merge"])
    if why:
        run_logging.log(f"error: the game was not started: {why}")
        if notice is not None:
            notice(game, why)
        return 1
    try:
        if allow_without_backup:
            job_play(launch, backup=BACKUP_ALLOW_FAILURE)
        else:
            job_play(launch)
    except BackupBeforePlayFailed as e:
        why = (
            f"Backing up your saves before Play failed: {e}. Fix that, turn 'back up saves before Play' off in "
            "Settings, or start with --allow-without-backup to play anyway."
        )
        if notice is not None:
            notice(game, why, f"{game.name} was not started: a backup before Play failed")
        return 1
    except SystemExit as e:
        return int(e.code or 1) if isinstance(e.code, int) else 1
    return 0


def update_merge_headless(launch, automatic: bool = True) -> str | None:
    """--play without the window: bring the merged mods up to date first. None when the game may start (nothing to
    do, or updated); otherwise why it must not start: the game never runs with merged mods that no longer match the
    profile (a removed mod still inside them, say). Nothing can ask here, so a rebuild tool runs only when it was
    already allowed. automatic False (the setting "rebuild ... automatically" off): nothing is rebuilt
    without being asked, so the game is not started either."""
    prof = Path(launch.profile) if getattr(launch, "profile", None) else None
    if prof is None:
        return None
    loc = launch.loc
    h = mod_merge.play_check(prof, loc=loc)
    if h is None:
        return None
    run_logging.start_log("launcher: update merged mods before Play (no window)", launch.game.key)
    reason = (h.get("reasons") or [h.get("text") or "the merged mods are out of date"])[0]
    if h["blocked"]:
        run_logging.log(f"error: the merged mods are out of date ({reason}) and cannot be rebuilt: {h['blocked']}")
        return f"The merged mods are out of date and cannot be rebuilt: {h['blocked']}"
    if not automatic:
        run_logging.log(f"error: the merged mods are out of date ({reason}); automatic rebuilds are off")
        return (
            f"The merged mods are out of date ({reason}), and rebuilding them automatically before Play is "
            "turned off. Open Roundtable Souls to rebuild them."
        )
    tool: Any = mod_merge.find_backend(prof, loc=loc)  # a rebuild tool (mods.backends), or None
    if tool is not None and tool.problem():
        run_logging.log(f"error: {tool.label} cannot run: {tool.problem()}")
        return f"The merged mods are out of date and {tool.label} cannot run: {tool.problem()}"
    if tool is not None and not mod_merge.approved(tool):
        run_logging.log(f"error: {tool.label} has not been allowed to run yet; open Roundtable Souls and allow it")
        return (
            f"The merged mods are out of date ({reason}), and {tool.label} has not been allowed to run yet. "
            "Open Roundtable Souls to allow it."
        )
    try:
        mod_merge.update_before_play(prof, run_logging.log, loc=loc)
        run_logging.log("done: merged mods updated")
        return None
    except mod_merge.MergeError as e:
        run_logging.log(f"error: the merged mods could not be updated: {e}")
        return f"The merged mods could not be updated: {e}"


def check(settings: LauncherSettings, loc: Locations, data: Path):
    """`roundtable-souls [--game <name>] --check`: what the launcher detects for one game, printed and written to
    logs/last_run.log (so the windowed exe, which has no console, can be checked too). The co-op password is never
    included. data: the data folder in use."""
    from roundtable_souls.saves.item_names import item_names

    lines = [f"{TITLE} {VERSION}"]
    game = loc.game
    installed = [g.name for g in games.GAMES if installed_dir(g)]
    lines.append(f"game: {game.name}{'' if game.ready else ' (not supported yet)'}")
    lines.append(f"installed games: {', '.join(installed) or 'none found'}")
    remembered = remembered_profile(settings, game)
    launch_profiles = discover(remembered, loc) if game.ready else []
    lines.append(f"setups found: {len(launch_profiles)}")
    for s in launch_profiles:
        spec = scaling_spec(s.ini) if s.ini else None
        sc = read_scaling(s.ini, spec) if s.ini else None
        if not s.ini or not has_password(s.ini):
            password = "none in this mod" if s.ini else "not set"
        else:
            password = "set" if read_password(s.ini) else "not set"
        lines += [
            f"  [{s.kind}] {s.label}",
            f"      {s.summary()}",
            f"      ini: {s.ini}  password: {password}",
            f"      scaling: {preset_of(sc, spec) if sc else None} {sc}",
        ]
        probs = s.problems()
        if probs:
            lines.append("      PROBLEMS: " + "; ".join(probs))
    lines.append(f"remembered: {remembered}")
    lines.append(f"steam: {steam.steam_exe()}")
    lines.append(f"game folder: {loc.game_dir()}")
    if game is games.ELDEN_RING:
        game_ids = save_analyze.game_item_ids(loc.regulation_bin())
        lines.append(f"game items from regulation.bin: {len(game_ids) if game_ids else 'not readable'}")
        names = item_names(loc.game_dir(), loc.me3_profiles_dir(), refresh=True).names
        sources = sorted({source for _name, source in names.values()})
        lines.append(f"mod item names: {len(names)} from {', '.join(sources) or 'no mods'}")
    lines.append(f"data folder: {data} ({'next to the program' if data == exe_dir() else 'per-user app data'})")
    for p in loc.save_files():
        i = save_info(p, loc=loc)
        lines.append(
            f"  save {i['name']}: {i['kind']}, block {i['block']}, modified {i['modified']}"
            + (f", error {i['error']}" if i["error"] else "")
        )
        for c in i["characters"]:
            lines.append(
                f"      slot {c['slot']}: {c['name']} lvl {c['level']} {c['body']} hp {c['hp']} runes {c['runes']}"
            )
        if not i["characters"]:
            for f in i["findings"]:
                lines.append(f"      {f['title']}: {f.get('detail', '')}")
    run_logging.start_log("launcher: check", game.key)
    for line in lines:
        print(line)
        run_logging.log(line)
