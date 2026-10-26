"""Processes on this machine: the ones running under a program name (a Toolhelp snapshot on Windows; /proc on Linux, where a
Wine or Proton process is matched by the Windows exe its command line names), and the flag that keeps child consoles
hidden."""

import re
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
# Child consoles must never pop up (the window has no console of its own).
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# Only for a /proc without thread counts: a real game uses gigabytes, a leftover shell almost nothing.
LIVE_MIN_KB = 100_000


def _windows_processes(name):
    """(pid, thread count) from a Toolhelp snapshot. A dead shell the game leaves behind is listed with 0 threads."""
    assert sys.platform == "win32"  # also tells pyright on Linux that the rest is Windows-only
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    found = []
    try:
        e = Entry()
        e.dwSize = ctypes.sizeof(Entry)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if e.szExeFile.lower() == name.lower():
                found.append((int(e.th32ProcessID), int(e.cntThreads)))
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return found


def _linux_processes(name, proc_root=Path("/proc")):
    """Match the program name, or for Wine / Proton processes the Windows exe named in the command line."""
    wanted = name.lower()
    found = []
    for entry in proc_root.iterdir() if proc_root.is_dir() else ():
        if not entry.name.isdigit():
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
            comm = (entry / "comm").read_text(errors="ignore").strip()
            status = (entry / "status").read_text(errors="ignore")
        except OSError:
            continue
        first = argv[0].decode(errors="ignore").replace("\\", "/").rsplit("/", 1)[-1].lower() if argv else ""
        if wanted not in (first, comm.lower()):
            continue
        threads = re.search(r"^Threads:\s+(\d+)", status, re.M)
        if threads:
            found.append((int(entry.name), int(threads.group(1))))
            continue
        # No thread count in /proc: judge by memory as before.
        rss = re.search(r"^VmRSS:\s+(\d+)\s+kB", status, re.M)
        found.append((int(entry.name), int(int(rss.group(1)) >= LIVE_MIN_KB) if rss else 0))
    return found


def processes(name):
    """(pid, thread count) for every process with this program name."""
    if IS_WINDOWS:
        return _windows_processes(name)
    if IS_LINUX:
        return _linux_processes(name)
    return []
