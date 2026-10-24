"""What a run of the game can tell the player afterwards, from data only: the game's exe changed since the last Play
(its DLL mods may need updates), and the logs that overhaul configs declare (overhauls.config.Health) held a failure
line written during the run. Nothing here scans for the word "error"; a mod with no declared health is not read."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from bayle import overhauls
from bayle.config.settings_file import change_settings, load_settings
from bayle.game import exe as game_exe
from bayle.game.locate import Locations
from bayle.overhauls.config import Health
from bayle.platform import logging as run_logging
from bayle.platform import paths

TAIL_BYTES = 1 << 20  # a log is read from its last megabyte at most, however long the run was


def game_update_notice(loc: Locations) -> str | None:
    """Record the game exe's build for this game; the words to show when it differs from the last Play's, else None
    (also on the first Play ever, and when the exe cannot be read: nothing is recorded then)."""
    game_dir = loc.game_dir()
    stamp = game_exe.build_stamp(game_dir / loc.game_exe_name()) if game_dir else None
    if stamp is None:
        return None
    key = loc.game.key
    seen = load_settings().run_state.get(key, {}).get("exe_build")
    if seen == stamp:
        return None
    change_settings(
        lambda cur: {"run_state": {**cur.run_state, key: {**cur.run_state.get(key, {}), "exe_build": stamp}}}
    )
    if seen is None:
        return None
    return f"{loc.game.name} updated since your last run. DLL mods may need updates."


Watch = list[tuple[str, Path, Health, int | None]]  # mod label, log path, entry, size at launch


def watch(profile: str | Path, game: str) -> Watch:
    """The declared logs of the overhauls in this profile's folder, with each log's size now (None: not there yet)."""
    out: Watch = []
    for config in overhauls.load(game):
        folder = Path(profile).parent / config.recognise.folder
        if not folder.is_dir():
            continue
        for entry in [*config.health, *(config.basic.health if config.basic else [])]:
            path = folder / entry.log
            out.append((config.label, path, entry, _size(path)))
    return out


def _size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def _new_text(path: Path, before: int | None) -> str | None:
    """The text written since `before` bytes (all of it when the file got shorter: it was started over), at most the
    last TAIL_BYTES of it; None when the file cannot be read."""
    try:
        with path.open("rb") as f:
            size = f.seek(0, 2)
            start = before if before is not None and before <= size else 0
            start = max(start, size - TAIL_BYTES)
            f.seek(start)
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return None


def findings(label: str, text: str, entry: Health) -> list[str]:
    fail = [re.compile(p) for p in entry.fail]
    ok = re.compile(entry.ok) if entry.ok else None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    last_ok = max((i for i, ln in enumerate(lines) if ok and ok.search(ln)), default=-1)
    found = [f"{label}: {ln}" for i, ln in enumerate(lines) if i > last_ok and any(p.search(ln) for p in fail)]
    if ok and last_ok < 0 and not found and lines:
        found.append(f"{label}: {entry.log} never said it started ({entry.ok})")
    return found


def report(
    watched: Iterable[tuple[str, Path, Health, int | None]], notice: Callable[[str], None] = run_logging.notice
) -> list[str]:
    """After the run: a notice (a warning in Activity) for every failure line the declared logs gained. Returns them."""
    out: list[str] = []
    for label, path, entry, before in watched:
        text = _new_text(path, before)
        if text:
            out.extend(findings(label, text, entry))
    for line in out:
        notice(line)
    return out


# ----------------------------------------------------------------------------- a run Bayle did not see end
def _set_pending(game: str, pending: dict | None) -> None:
    def change(cur):
        state = {**cur.run_state}
        mine = {k: v for k, v in state.get(game, {}).items() if k != "pending"}
        state[game] = {**mine, "pending": pending} if pending else mine
        return {"run_state": state}

    change_settings(change)


def begin(profile: str | Path, game: str, exe_name: str) -> Watch:
    """At launch: report a run that was never reported (Bayle was closed or crashed during it), then note the declared
    logs' sizes and when the launch happened, kept in the settings until end() reports them."""
    recover(game)
    watched = watch(profile, game)
    if watched:
        logs = [{"label": m, "path": str(p), "entry": e.model_dump(), "size": s} for m, p, e, s in watched]
        _set_pending(game, {"started": time.time(), "exe": exe_name, "logs": logs})
    return watched


def end(game: str, watched: Watch, notice: Callable[[str], None] = run_logging.notice) -> list[str]:
    """After the run: report the new lines, then forget the sizes."""
    found = report(watched, notice)
    _set_pending(game, None)
    return found


def recover(game: str) -> list[str]:
    """Report the run noted by begin() that end() never closed (nothing while that game is running)."""
    pending = load_settings().run_state.get(game, {}).get("pending")
    if not pending or paths.exe_running(pending.get("exe", "")):
        return []
    try:
        started = float(pending["started"])
        watched: Watch = [
            (x["label"], Path(x["path"]), Health.model_validate(x["entry"]), x["size"]) for x in pending["logs"]
        ]
    except KeyError, TypeError, ValueError:
        watched, started = [], 0.0
    # a log not touched since the launch has nothing new (the size check says the same; this skips the read)
    watched = [w for w in watched if _modified(w[1]) >= started or w[3] is None]
    return end(game, watched)


def recover_all() -> list[str]:
    """At Bayle's start: every game's unreported run."""
    out: list[str] = []
    for game in list(load_settings().run_state):
        out.extend(recover(game))
    return out


def _modified(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
