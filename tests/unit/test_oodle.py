"""The game's Oodle library wiring. The game's DLL is never needed: WinDLL is faked with a stand-in whose functions
record their arguments, and the tests that need a real file on Windows use a placeholder file, not the game's."""

import ctypes
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from roundtable_souls.game import oodle


class FakeFn:
    """A ctypes function stand-in: records its calls and answers with impl."""

    def __init__(self, impl=None):
        self.impl, self.restype, self.argtypes, self.calls = impl, None, None, []

    def __call__(self, *args):
        self.calls.append(args)
        if self.impl is None:
            raise AssertionError("the test did not say what this function answers")
        return self.impl(*args)


def fake_dll(compress=None):
    """Every function the wrappers use, with answers that do not depend on the library."""
    opts = oodle._Options()
    opts.verbosity = 3
    fake = SimpleNamespace(
        OodleLZ_Decompress=FakeFn(
            lambda payload, n, out, usize, *rest: (ctypes.memmove(out, b"ABCDEFG", usize), usize)[1]
        ),
        OodleLZ_CompressOptions_GetDefault=FakeFn(lambda kind, level: ctypes.addressof(opts)),
        OodleLZ_GetCompressedBufferSizeNeeded=FakeFn(lambda n: n + 16),
        OodleLZ_Compress=FakeFn(compress or (lambda kind, body, n, out, level, *rest: n)),
        opts=opts,
    )
    return fake


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(oodle.sys, "platform", "win32")


@pytest.fixture
def no_cached_compressor(monkeypatch):
    monkeypatch.setattr(oodle, "_compressor", None)  # restored after the test


def test_the_error_is_a_value_error():
    assert issubclass(oodle.OodleError, ValueError)


def test_off_windows_nothing_is_found_even_with_a_library_present(monkeypatch, tmp_path, no_cached_compressor):
    monkeypatch.setattr(oodle.sys, "platform", "linux")
    (tmp_path / "oo2core_8_win64.dll").write_bytes(b"not a library")
    assert oodle.find_oodle(tmp_path) is None
    assert oodle.oodle_compressor(tmp_path) is None


def test_no_game_folder_finds_nothing(windows, no_cached_compressor):
    assert oodle.find_oodle(None) is None
    assert oodle.oodle_compressor(None) is None


def test_a_folder_without_the_library_finds_nothing(windows, tmp_path, no_cached_compressor):
    assert oodle.find_oodle(tmp_path) is None
    assert oodle.oodle_compressor(tmp_path) is None


def test_a_placeholder_file_that_is_not_a_library_is_skipped(windows, tmp_path, no_cached_compressor):
    if sys.platform != "win32":
        pytest.skip("loading a DLL needs Windows; the placeholder is only read there")
    (tmp_path / "oo2core_8_win64.dll").write_bytes(b"not a library")
    assert oodle.find_oodle(tmp_path) is None


def test_the_newest_library_that_loads_is_used(windows, monkeypatch, tmp_path, no_cached_compressor):
    loaded, lib = [], fake_dll()

    def win_dll(path):
        loaded.append(Path(path).name)
        if loaded[-1].startswith("oo2core_9"):
            raise OSError("bad image")  # the newest one does not load: the older one is tried
        return lib

    monkeypatch.setattr(oodle.ctypes, "WinDLL", win_dll, raising=False)
    (tmp_path / "oo2core_8_win64.dll").write_bytes(b"")
    (tmp_path / "oo2core_9_win64.dll").write_bytes(b"")
    found = oodle.find_oodle(tmp_path)
    assert loaded == ["oo2core_9_win64.dll", "oo2core_8_win64.dll"]
    assert isinstance(found, oodle.Decompressor)
    assert lib.OodleLZ_Decompress.restype is ctypes.c_ssize_t
    assert len(lib.OodleLZ_Decompress.argtypes) == 14


def test_decompressor_returns_the_bytes_the_library_wrote(monkeypatch):
    lib = fake_dll()
    assert oodle.Decompressor(lib.OodleLZ_Decompress).decompress(b"payload", 7) == b"ABCDEFG"
    assert lib.OodleLZ_Decompress.calls[0][:2] == (b"payload", 7)


def test_decompressor_refuses_a_short_result():
    lib = fake_dll()
    lib.OodleLZ_Decompress.impl = lambda *args: 3
    with pytest.raises(oodle.OodleError, match="could not decompress"):
        oodle.Decompressor(lib.OodleLZ_Decompress).decompress(b"payload", 7)


def test_compressor_sets_the_game_options_and_returns_the_packed_bytes():
    seen = {}

    def compress(kind, body, n, out, level, options, *rest):
        seen["options"] = options._obj  # the byref'd struct the library would read
        seen["level"] = level
        ctypes.memmove(out, b"K" + body, n + 1)
        return n + 1

    lib = fake_dll(compress)
    comp = oodle.Compressor(lib)
    assert comp.compress_kraken(b"body", 5) == b"Kbody"
    assert seen["level"] == 5
    assert seen["options"].seekChunkReset == 1  # the game needs these two
    assert seen["options"].seekChunkLen == 0x40000
    assert seen["options"].verbosity == 3  # the library's own defaults are kept


def test_compressor_refuses_an_empty_result():
    lib = fake_dll(lambda *args: 0)
    with pytest.raises(oodle.OodleError, match="could not compress"):
        oodle.Compressor(lib).compress_kraken(b"body", 5)


def test_compressor_is_loaded_once_and_then_reused(monkeypatch, windows, tmp_path, no_cached_compressor):
    lib = fake_dll()
    monkeypatch.setattr(oodle.ctypes, "WinDLL", lambda path: lib, raising=False)
    (tmp_path / "oo2core_8_win64.dll").write_bytes(b"")
    first = oodle.oodle_compressor(tmp_path)
    assert isinstance(first, oodle.Compressor)
    assert lib.OodleLZ_Compress.argtypes is not None
    assert oodle.oodle_compressor(None) is first  # cached: no folder needed the second time
