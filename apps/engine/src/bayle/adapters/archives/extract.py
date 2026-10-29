"""Unpacking a mod download: .zip, .7z and .rar archives, or a folder used where it is, into a staging folder. Every
archive's list is checked before anything is written (check_listing): no path outside the target, no link, no
alternate data stream, and caps on entries, size and depth."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from bayle.modules.mods.models import ModError

ARCHIVE_EXTENSIONS = (
    ".zip",
    ".7z",
    ".rar",
)  # .7z via py7zr (bundled), .rar via an extractor on the PC

# far above any real mod (the largest overhauls are a few GB in tens of thousands of files), far below a full disk
MAX_ENTRIES = 200_000
MAX_TOTAL = 64 * 2**30
MAX_DEPTH = 40


def _unsafe(name: str) -> bool:
    """Lands outside the folder, names a drive or an alternate data stream (any ':'), or nests absurdly deep."""
    parts = name.replace("\\", "/").split("/")
    return name.startswith(("/", "\\")) or ".." in parts or ":" in name or "\0" in name or len(parts) > MAX_DEPTH


def check_entry(name: str) -> None:
    """Refuse an archive entry that would land outside the folder it is unpacked into."""
    if _unsafe(name):
        raise ModError(f"archive entry escapes the folder: {name}")


def check_listing(entries: list[tuple[str, int, bool]], dest: Path) -> None:
    """Refuse an archive from its list, before anything is written. entries: (name, unpacked size, is a link)."""
    if len(entries) > MAX_ENTRIES:
        raise ModError(f"the archive has {len(entries):,} entries, more than any mod ({MAX_ENTRIES:,}); refused")
    total = 0
    for name, size, link in entries:
        check_entry(name)
        if link:
            raise ModError(f"the archive holds a link ({name}); refused, a mod needs none")
        total += max(size, 0)
    if total > MAX_TOTAL:
        raise ModError(f"the archive unpacks to {total / 2**30:.1f} GB, more than any mod; refused")
    probe = Path(dest)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    if total > free:
        raise ModError(
            f"the archive unpacks to {total / 2**30:.1f} GB and the drive has {free / 2**30:.1f} GB free; "
            "nothing was unpacked"
        )


def is_link(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def extract_zip(archive: Path, dest: Path) -> Path:
    """Extract a .zip into dest, refusing entries that would escape it."""
    archive = Path(archive)
    dest = Path(dest)
    with zipfile.ZipFile(archive) as z:
        # zipfile never writes more than a member's listed size, so the listed sizes bound what lands on disk
        check_listing([(i.filename, i.file_size, is_link(i)) for i in z.infolist()], dest)
        dest.mkdir(parents=True, exist_ok=True)
        z.extractall(dest)
    return dest


def extract_7z(archive: Path, dest: Path) -> Path:
    """.7z through py7zr (bundled in the exe); entries that would escape the folder are refused."""
    try:
        import py7zr
    except ImportError as e:
        raise ModError("7z support is missing from this build") from e
    archive = Path(archive)
    dest = Path(dest)
    try:
        with py7zr.SevenZipFile(archive, "r") as z:
            if z.needs_password():
                raise ModError(
                    "This 7z is password-protected. Unpack it with 7-Zip using the password its author gave, then "
                    "install the folder."
                )
            check_listing([(f.filename, f.uncompressed or 0, f.is_symlink) for f in z.list()], dest)
            dest.mkdir(parents=True, exist_ok=True)
            z.extractall(path=dest)
    except ModError:
        raise
    except Exception as e:
        raise ModError(f"could not read the 7z archive: {e}") from e
    return dest


def _no_window():
    try:
        from bayle.adapters.system import proc

        return proc.NO_WINDOW
    except Exception:
        return 0


def rar_tools() -> list[list[str]]:
    """Command lines that can unpack .rar on this PC, best first: Windows' own bsdtar (libarchive reads RAR and RAR5),
    then 7-Zip, then WinRAR's UnRAR. Each takes the archive and the destination appended by extract_rar."""
    tools = []
    win = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
    if win.is_file():
        tools.append([str(win), "-xf"])
    for pf in filter(None, (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"))):
        for exe in (Path(pf) / "7-Zip" / "7z.exe", Path(pf) / "WinRAR" / "UnRAR.exe"):
            if exe.is_file():
                tools.append([str(exe), "x", "-y"])
    return tools


def parse_bsdtar_listing(text: str) -> list[tuple[str, int, bool]]:
    """`tar -tvf` lines ("-rw-r--r--  0 0 0  1234 Jan 01  2020 name", a link "lrwx... name -> target", a hard link
    "... name link to target") as check_listing entries."""
    entries = []
    for line in text.splitlines():
        f = line.split(maxsplit=8)
        if len(f) < 9 or not f[4].isdigit():
            raise ModError(f"could not read the .rar's list: {line[:120]}")
        link = f[0].startswith(("l", "h")) or " -> " in f[8] or " link to " in f[8]
        entries.append((f[8], int(f[4]), link))
    return entries


def _rar_listing(archive: Path) -> list[tuple[str, int, bool]]:
    """The .rar's list from Windows' bsdtar, read before anything is unpacked. Without it the archive is refused."""
    tools = [t for t in rar_tools() if t[1] == "-xf"]
    if not tools:
        raise ModError(
            "can't check the .rar before unpacking it (Windows' tar.exe is missing); unpack it yourself and install "
            "the folder"
        )
    try:
        r = subprocess.run(
            [tools[0][0], "-tvf", str(archive)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            creationflags=_no_window(),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ModError(f"could not read the .rar's list: {e}") from e
    if r.returncode != 0:
        why = (r.stderr or r.stdout or "").strip()[:200] or f"exit {r.returncode}"
        raise ModError(f"could not unpack the .rar: {why}")
    return parse_bsdtar_listing(r.stdout)


def _check_unpacked(dest: Path) -> None:
    """What an outside extractor wrote, checked again: inside dest, no link or junction, within the caps."""
    root = dest.resolve()
    count = total = 0
    for p in dest.rglob("*"):
        count += 1
        if p.is_symlink() or p.is_junction() or root not in p.resolve().parents:
            raise ModError("archive tried to write outside the folder or make a link; refused")
        if p.is_file():
            total += p.stat().st_size
    if count > MAX_ENTRIES or total > MAX_TOTAL:
        raise ModError("the archive unpacked to more than any mod; refused")


def extract_rar(archive: Path, dest: Path) -> Path:
    """.rar through whichever extractor the PC has, once its list (from bsdtar) passed check_listing; what it wrote is
    checked again, since the extractor is not ours."""
    archive = Path(archive)
    dest = Path(dest)
    tools = rar_tools()
    if not tools:
        raise ModError(
            "no .rar extractor found: Windows' tar.exe, 7-Zip or WinRAR is needed, or unpack it first and install the folder"
        )
    check_listing(_rar_listing(archive), dest)
    dest.mkdir(parents=True, exist_ok=True)
    errors = []
    for tool in tools:
        if tool[1] == "-xf":
            cmd = tool + [str(archive), "-C", str(dest)]
        else:
            cmd = tool + [str(archive), f"-o{dest}"]
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                creationflags=_no_window(),
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            errors.append(f"{Path(tool[0]).name}: {e}")
            continue
        if r.returncode == 0 and any(dest.iterdir()):
            try:
                _check_unpacked(dest)
            except ModError:
                shutil.rmtree(dest, ignore_errors=True)
                raise
            return dest
        errors.append(
            f"{Path(tool[0]).name}: {(r.stderr or r.stdout or '').strip()[:200] or 'exit ' + str(r.returncode)}"
        )
        for p in dest.iterdir():
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    raise ModError("could not unpack the .rar: " + "; ".join(errors))


def extract_archive(archive: Path, dest: Path) -> Path:
    ext = Path(archive).suffix.lower()
    if ext == ".zip":
        return extract_zip(archive, dest)
    if ext == ".7z":
        return extract_7z(archive, dest)
    if ext == ".rar":
        return extract_rar(archive, dest)
    raise ModError(f"{ext or 'that file'} is not a supported archive (zip, 7z, rar)")


def stage(source: Path, staging_root: Path) -> tuple[Path, bool]:
    """(folder to detect from, is_temporary). Archives are extracted, and a lone .dll copied, into a temp folder under
    staging_root."""
    source = Path(source)
    if source.is_dir():
        return source, False
    if source.suffix.lower() in ARCHIVE_EXTENSIONS:
        tmp = Path(tempfile.mkdtemp(prefix="install-", dir=str(staging_root)))
        try:
            extract_archive(source, tmp)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return tmp, True
    if source.suffix.lower() == ".dll" and source.is_file():  # a DLL mod on its own
        tmp = Path(tempfile.mkdtemp(prefix="install-", dir=str(staging_root)))
        (tmp / source.stem).mkdir()
        shutil.copy2(source, tmp / source.stem / source.name)
        return tmp, True
    raise ModError("pick a .zip, .7z or .rar archive, a .dll, or a folder")
