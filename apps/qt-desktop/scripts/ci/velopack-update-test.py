"""Release check on a clean Windows runner: the previous published release updates itself to this build.

What users do: the installed launcher's Update now. Here, its headless form (`--update`):
  1. the newest published release older than this build installs silently (Velopack setup);
  2. its identity is pointed at a local feed served by this script and at a throwaway signing key (an override file
     in the installed copy's data folder, which releases read; nothing is rebuilt), so the real checks run: the feed's
     minisign signature and trusted comment, then the package's checksums;
  3. `--update` downloads this build's package from that feed, keeps the old version for a rollback, and hands over
     to Velopack, which installs it and restarts the launcher;
  4. this build must start, open (create) its database at the current schema and report ready before the update
     watchdog's 90 s; no rollback may happen;
  5. the copy is uninstalled.

--broken: the rollback instead. The previous release updates to a broken build of this one (its QML window removed,
packed as a higher, never-published version, served only by the local feed); its own watchdog must put it back, the
restored version must start and report ready, the player's database, setting and file must be as they were, the
broken version must be blocked and a second --update must refuse it (exit code 3).

Every wait is bounded; a step that does not finish fails the test after printing the update and watchdog logs.
It runs only on CI (GITHUB_ACTIONS): it installs with the real app ID and clears that app's data folder first.

Run from the repository root after scripts/build.py:  uv run python scripts/ci/velopack-update-test.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NoReturn

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

ROOT = Path(__file__).resolve().parents[2]
SHARE = ROOT / "dist" / "share"
PACK = "Carlomos7.RoundtableSouls"
TITLE = "Bayle"
PREVIOUS_TITLE = "Roundtable Souls"  # releases before the rename; Steam shortcuts point at their stub
PORT = 8797
LOCAL = Path(os.environ.get("LOCALAPPDATA", ""))
DATA = LOCAL / "RoundtableSouls"  # the app's data folder (its identity's data_dir_name)
WORK = Path(os.environ.get("RUNNER_TEMP", ROOT / "build")) / "update-test"
INSTALL = WORK / "install"
STARTED = time.time()


def say(message: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {message}", flush=True)


def tail(path: Path, lines: int = 30) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    print(f"  --- {path} (last {lines} lines)", flush=True)
    for line in text[-lines:]:
        print(f"    {line}", flush=True)


def diagnostics() -> None:
    say("diagnostics")
    print(f"  installed version: {installed()}", flush=True)
    for folder in (DATA / "updates" / "state", DATA / "logs" / "jobs"):
        for p in sorted(folder.glob("*"), key=lambda p: p.stat().st_mtime)[-6:] if folder.is_dir() else []:
            if p.is_file() and p.stat().st_mtime >= STARTED:
                tail(p)
    for p in (INSTALL / "velopack.log", LOCAL / PACK / "velopack.log", DATA / "logs" / "launcher.log"):
        if p.is_file():
            tail(p, 40)


def fail(message: str) -> NoReturn:
    print(f"::error::{message}", flush=True)
    diagnostics()
    stop_launchers()
    sys.exit(1)


def wait_until(condition, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.5)
    return bool(condition())


def run_bounded(args: list, seconds: int, what: str) -> int:
    """Waits for this process only (never its children: a setup or an update starts the launcher)."""
    say(f"start: {what}")
    proc = subprocess.Popen([str(a) for a in args], env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    try:
        code = proc.wait(seconds)
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        fail(f"{what} did not finish within {seconds} s")
    say(f"end: {what} (exit code {code})")
    return code


def stop_launchers() -> None:
    script = (
        f"Get-Process | Where-Object {{ $_.Path -and $_.Path.StartsWith('{INSTALL}', 'OrdinalIgnoreCase') }} | "
        "Stop-Process -Force"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True)


def installed() -> str:
    try:
        text = (INSTALL / "current" / "sq.version").read_text(encoding="utf-8")
    except OSError:
        return "?"
    m = re.search(r"<version>([^<]+)</version>", text)
    return m.group(1) if m else "?"


def version_key(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def is_prerelease(v: str) -> bool:
    """A beta (X.Y.Z-beta.N): published to the Beta channel only, so the installed copy must be on that channel to
    see it (the Stable channel takes GitHub's /releases/latest, which never names a pre-release)."""
    return "-" in v


# ----------------------------------------------------------------------------- a throwaway signing key
class Key:
    def __init__(self):
        self.private = Ed25519PrivateKey.generate()
        self.key_id = os.urandom(8)

    def public_text(self) -> str:
        raw = self.private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return "untrusted comment: update test key\n" + base64.b64encode(b"Ed" + self.key_id + raw).decode() + "\n"

    def sign(self, data: bytes, comment: str) -> str:
        """minisign's default (prehashed) signature, as release.yml makes them."""
        body = self.private.sign(hashlib.blake2b(data, digest_size=64).digest())
        line = base64.b64encode(b"ED" + self.key_id + body).decode()
        glob = base64.b64encode(self.private.sign(body + comment.encode())).decode()
        return f"untrusted comment: update test\n{line}\ntrusted comment: {comment}\n{glob}\n"


# ----------------------------------------------------------------------------- the local feed
def serve(version: str, files: dict[str, bytes]) -> ThreadingHTTPServer:
    base = f"http://127.0.0.1:{PORT}"
    release = {
        "tag_name": f"v{version}",
        "name": f"Bayle v{version}",
        "draft": False,
        "prerelease": is_prerelease(version),
        "html_url": f"{base}/releases/v{version}",
        "body": "update test",
        "assets": [{"name": n, "browser_download_url": f"{base}/dl/{n}"} for n in files],
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 (the base class's name)
            say(f"feed: {self.command} {self.path}")

        def send(self, code: int, body: bytes, kind: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/advisory.json":
                return self.send(200, b'{"minimum": null}')
            if path in ("/api/releases/latest", f"/api/releases/tags/v{version}"):
                return self.send(200, json.dumps(release).encode())
            if path == "/api/releases":
                return self.send(200, json.dumps([release]).encode())
            if path.startswith("/dl/") and path[4:] in files:
                return self.send(200, files[path[4:]], "application/octet-stream")
            return self.send(404, b"{}")

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ----------------------------------------------------------------------------- the test
def previous_release(new: str) -> str:
    """The newest published release older than this build (a re-run of a published version updates from the one
    before it)."""
    out = subprocess.run(
        ["gh", "release", "list", "--repo", os.environ["GITHUB_REPOSITORY"], "--exclude-drafts",
         "--exclude-pre-releases", "--limit", "20", "--json", "tagName", "--jq", ".[].tagName"],
        capture_output=True, text=True, check=True,
    ).stdout.split()  # fmt: skip
    older = [t for t in out if version_key(t) < version_key(new)]
    if not older:
        fail(f"no published release older than {new} to update from")
    return max(older, key=version_key)


FEED, SIG = "releases.win.json", "releases.win.json.minisig"
EXE = INSTALL / "current" / "RoundtableSouls.exe"
STATE = DATA / "updates" / "state"


def main() -> None:
    if not os.environ.get("GITHUB_ACTIONS"):
        sys.exit("velopack-update-test: runs only on CI (it installs with the real app ID and clears its data folder)")
    broken = "--broken" in sys.argv[1:]
    new = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if not (SHARE / FEED).is_file():
        fail(f"{SHARE / FEED} is missing: run scripts/build.py first")
    prev = previous_release(new)
    if broken:
        say(f"this build: {new}; the published {prev} updates to a broken build of it and must roll back")
    else:
        say(f"this build: {new}; updating from the published {prev}")
    install_previous(prev)
    if broken:
        rollback_test(prev, new)
    else:
        update_test(prev, new)
    uninstall()


def install_previous(prev: str) -> None:
    """1. the published release installs silently into a throwaway folder, with a clean data folder."""
    shutil.rmtree(WORK, ignore_errors=True)
    shutil.rmtree(DATA, ignore_errors=True)  # a clean start (the install test before this one used it)
    WORK.mkdir(parents=True)
    subprocess.run(
        ["gh", "release", "download", prev, "--repo", os.environ["GITHUB_REPOSITORY"],
         "--pattern", "RoundtableSouls-Setup.exe", "--dir", str(WORK)],
        check=True,
    )  # fmt: skip
    code = run_bounded(
        [WORK / "RoundtableSouls-Setup.exe", "--silent", "--installto", INSTALL], 300, f"the {prev} setup"
    )
    if code != 0 or not wait_until(lambda: installed() == prev.lstrip("v"), 60):
        fail(f"the {prev} setup did not install (exit code {code}, installed {installed()})")
    time.sleep(3)
    stop_launchers()


def point_at_local_feed(key: Key) -> None:
    """2. the installed copy checks this script's feed, with this key (the real checks, a different key and address)."""
    base = f"http://127.0.0.1:{PORT}"
    override = {
        "pack_id": PACK,
        "api_base": f"{base}/api",
        "releases_page": f"{base}/releases",
        "advisory_url": f"{base}/advisory.json",
        "signing_key": key.public_text(),
        "display_platform": "offscreen",
    }
    # the installed (previous) release reads the override from its own package's data folder: bayle/ since the
    # package rename, roundtable_souls/ in the releases published before it (4.5.1, 4.6.0-rc.N)
    internal = INSTALL / "current" / "_internal"
    data_dir = next((d for d in (internal / p / "data" for p in ("bayle", "roundtable_souls")) if d.is_dir()), None)
    if data_dir is None:
        fail(f"no bayle/data or roundtable_souls/data under {internal}: the installed layout changed")
    (data_dir / "build-identity.json").write_text(json.dumps(override, indent=1), encoding="utf-8")


def signed(files: dict[str, bytes], version: str, key: Key) -> dict[str, bytes]:
    return {**files, SIG: key.sign(files[FEED], f"roundtable-souls {version} win").encode()}


def schema_version() -> str | None:
    """The database's Alembic version, read-only (None when there is no database or no version)."""
    db = DATA / "roundtable.db"
    if not db.is_file():
        return None
    conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        ok = conn.execute("PRAGMA integrity_check").fetchone()
    finally:
        conn.close()
    if not ok or ok[0] != "ok":
        fail(f"the database fails its integrity check: {ok}")
    return row[0] if row else None


def stop_and_wait() -> None:
    stop_launchers()
    if not wait_until(lambda: not _running(EXE), 30):
        fail("the launcher did not stop")


def update_test(prev: str, new: str) -> None:
    """The previous release updates itself to this build, which starts, reports ready and keeps no rollback."""
    key = Key()
    point_at_local_feed(key)
    files = {p.name: p.read_bytes() for p in SHARE.iterdir() if p.is_file() and p.suffix in (".nupkg", ".json")}
    if is_prerelease(new):  # a beta: the installed copy is put on the Beta channel first, as a beta tester would be
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / "launcher_settings.json").write_text(json.dumps({"launcher_channel": "beta"}), encoding="utf-8")
        say("this build is a beta: the installed copy's Settings put on the Beta channel")
    server = serve(new, signed(files, new, key))
    try:
        # 3. Update now, without the window
        code = run_bounded([EXE, "--update"], 300, f"--update in {prev}")
        if code != 0:
            fail(f"--update exited with {code}")
        if not wait_until(lambda: installed() == new, 180):
            fail(f"Velopack did not install {new} (installed: {installed()})")
        say(f"installed {new}; waiting for it to report ready")
        ready = STATE / f"ready-{new}"
        if not wait_until(ready.exists, 150):
            fail(f"{new} did not report ready (the watchdog would roll it back)")
        say(f"ready: {ready.read_text(encoding='utf-8', errors='replace').strip()}")
        time.sleep(5)
        # 4. its database, and no rollback
        version = schema_version()
        say(f"database: {DATA / 'roundtable.db'} at schema {version or '?'}")
        if version is None:
            fail(f"{new} started without a database at a schema version")
        if (STATE / "rollback.json").exists() or installed() != new:
            fail(f"a rollback happened (installed: {installed()})")
        check_title()
        say(f"updated {prev} -> {new}: ready, database at {version}, no rollback")
    finally:
        server.shutdown()
    stop_and_wait()


# ----------------------------------------------------------------------------- --broken: the rollback
def broken_package(version: str) -> dict[str, bytes]:
    """This build with its window's QML taken out (it starts, but its window never comes up, so it never reports
    ready), packed by vpk as version: never published, kept in this run's work folder and served only by the local
    feed. Its feed and full package, by name."""
    app = WORK / "broken-app"
    shutil.copytree(ROOT / "dist" / "RoundtableSouls", app)
    main_qml = app / "_internal" / "bayle_qt" / "qml" / "Main.qml"
    if not main_qml.is_file():
        fail(f"{main_qml} is not there: the packaged layout changed, so the build cannot be broken this way")
    main_qml.unlink()
    out = WORK / "broken-vpk"
    args = [
        os.environ.get("VPK") or shutil.which("vpk") or "vpk", "pack", "--skip-updates", "--packId", PACK,
        "--packVersion", version, "--packDir", app, "--packTitle", TITLE, "--packAuthors", "Carlomos7",
        "--outputDir", out, "--mainExe", "RoundtableSouls.exe", "--runtime", "win-x64",
    ]  # fmt: skip
    if run_bounded(args, 600, f"vpk pack of the broken {version}") != 0:
        fail("vpk could not pack the broken build")
    files = {p.name: p.read_bytes() for p in out.iterdir() if p.is_file() and p.name.endswith(("-full.nupkg", FEED))}
    if FEED not in files or not any(n.endswith("-full.nupkg") for n in files):
        fail(f"vpk left no feed or full package in {out}: {sorted(p.name for p in out.iterdir())}")
    return files


def seed_user_data() -> dict:
    """What a player has before the update: the previous release's own database (made by its --check-storage), a
    setting they chose and a file of theirs in the data folder. Returns what must survive the rollback."""
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "launcher_settings.json").write_text(json.dumps({"theme": "light"}), encoding="utf-8")
    mine = DATA / "rollback-test" / "kept.me3"
    mine.parent.mkdir(parents=True, exist_ok=True)
    mine.write_bytes(b'profileVersion = "v1"\n# a player\'s own file: the rollback must keep it byte for byte\n')
    if run_bounded([EXE, "--check-storage"], 180, "--check-storage in the installed release") != 0:
        fail("the installed release could not open its database")
    version = schema_version()
    if version is None:
        fail("the installed release made no database")
    say(f"user data seeded: database at {version}, theme light, {mine.name}")
    return {"schema": version, "file": mine, "bytes": mine.read_bytes()}


def settings() -> dict:
    try:
        return json.loads((DATA / "launcher_settings.json").read_text(encoding="utf-8-sig"))
    except OSError, ValueError:
        return {}


def rollback_test(prev: str, new: str) -> None:
    """--broken: the previous release updates to a broken build; the watchdog it ships must put it back.

    The update is the previous release's own (its --update keeps its package and starts its watchdog: the real
    Update.exe and the real watchdog script, nothing faked). Checked: the broken build is applied and never reports
    ready; the watchdog restores the previous version; that version starts and reports ready again; the database,
    a setting and a file of the player's are as they were; the broken version is blocked, and a second Update now
    refuses it (exit code 3) and changes nothing."""
    old = prev.lstrip("v")
    major, minor, patch = version_key(new)
    broken = f"{major}.{minor}.{patch + 1}"  # above this build and every published release: offered as an update
    files = broken_package(broken)
    seed = seed_user_data()
    key = Key()
    point_at_local_feed(key)
    server = serve(broken, signed(files, broken, key))
    try:
        code = run_bounded([EXE, "--update"], 300, f"--update in {prev} to the broken {broken}")
        if code != 0:
            fail(f"--update exited with {code}")
        if not wait_until(lambda: installed() == broken, 180):
            fail(f"Velopack did not apply the broken {broken} (installed: {installed()})")
        say(f"the broken {broken} is applied; it must not report ready, and the watchdog must put {old} back")
        # the watchdog gives it 90 s once applied, then stops it and applies the kept package
        if not wait_until(lambda: installed() == old, 90 + 180):
            fail(f"the watchdog did not put {old} back (installed: {installed()})")
        rolled_back = time.time()
        if (STATE / f"ready-{broken}").exists():
            fail(f"the broken {broken} reported ready, so this proved nothing")
        log = (STATE / "watchdog.log").read_text(encoding="utf-8", errors="replace")
        if "putting the previous version back" not in log:
            fail("the watchdog's log does not say it rolled back")
        say(f"rolled back to {old}")

        # the restored version starts and reports ready; when nothing starts it, a player would
        ready = STATE / f"ready-{old}"

        def fresh() -> bool:
            return ready.is_file() and ready.stat().st_mtime >= rolled_back - 5

        if wait_until(fresh, 60):
            say(f"{old} was started after the rollback and reported ready")
        else:
            say(f"nothing started {old} after the rollback: starting it as a player would")
            subprocess.Popen([str(EXE)], env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
            if not wait_until(fresh, 120):
                fail(f"{old} did not start and report ready after the rollback")
        # its first start reads the watchdog's record: the broken version is blocked
        if not wait_until(
            lambda: any(str(b).lstrip("v") == broken for b in settings().get("update_blocked") or []), 60
        ):
            fail(f"{broken} is not blocked after the rollback (update_blocked: {settings().get('update_blocked')})")
        say(f"blocked: {settings().get('update_blocked')}")

        # the player's data is as it was
        if seed["file"].read_bytes() != seed["bytes"]:
            fail(f"{seed['file']} changed in the rollback")
        if settings().get("theme") != "light":
            fail(f"the player's setting was lost (theme: {settings().get('theme')})")
        version = schema_version()
        if version != seed["schema"]:
            fail(f"the database is at {version} after the rollback, not {seed['schema']} as the restored version needs")
        say(f"user data intact: {seed['file'].name} byte for byte, theme light, database at {version}")

        # the blocked state: a second Update now refuses the broken version and changes nothing
        stop_and_wait()
        point_at_local_feed(key)  # the restored copy is a fresh install of the kept package, without the override
        code = run_bounded([EXE, "--update"], 300, f"a second --update in {old}")
        if code != 3:
            fail(f"a second --update exited with {code}, not 3 (the newest release is blocked here)")
        time.sleep(5)
        if installed() != old:
            fail(f"the blocked {broken} was installed anyway (installed: {installed()})")
        say(f"rollback {old} -> {broken} -> {old}: watchdog restored it, it runs, data intact, {broken} blocked")
    finally:
        server.shutdown()
    stop_and_wait()


def uninstall() -> None:
    """5. the copy is uninstalled."""
    run_bounded([INSTALL / "Update.exe", "uninstall", "--silent"], 300, "the uninstaller")
    if not wait_until(lambda: not (INSTALL / f"{TITLE}.exe").exists(), 60):
        fail("the uninstaller left the program")
    say("uninstalled")


def check_title() -> None:
    """After the update: the new stub is there, an old-title stub is kept for Steam shortcuts, the uninstall entry
    and the Start menu shortcut carry the new title (Velopack renames them on update), no shortcut keeps the old one."""
    if not (INSTALL / f"{TITLE}.exe").is_file():
        fail(f"the update did not leave the stub {TITLE}.exe")
    had_old_stub = (INSTALL / f"{PREVIOUS_TITLE}.exe").is_file()
    say(f"old stub {PREVIOUS_TITLE}.exe kept: {had_old_stub} (expected when updating from a release with that title)")
    key = "HKCU:/Software/Microsoft/Windows/CurrentVersion/Uninstall/".replace("/", chr(92)) + PACK
    script = (
        f"(Get-ItemProperty '{key}').DisplayName; "
        "$p = [Environment]::GetFolderPath('Programs'); "
        f"Test-Path (Join-Path $p '{TITLE}.lnk'); Test-Path (Join-Path $p '{PREVIOUS_TITLE}.lnk')"
    )
    run = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True)
    out = run.stdout.splitlines()
    shown, new_lnk, old_lnk = (out + ["", "", ""])[:3]
    if shown.strip() != TITLE:
        fail(f"the uninstall entry is called '{shown.strip()}', not '{TITLE}'")
    if new_lnk.strip() != "True" or old_lnk.strip() == "True":
        fail(f"the Start menu shortcut was not renamed (new: {new_lnk.strip()}, old: {old_lnk.strip()})")


def _running(exe: Path) -> bool:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"@(Get-Process | Where-Object {{ $_.Path -eq '{exe}' }}).Count"],
        capture_output=True, text=True,
    ).stdout.strip()  # fmt: skip
    return out not in ("", "0")


if __name__ == "__main__":
    main()
