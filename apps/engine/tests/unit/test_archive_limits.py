"""E1: an archive is judged from its list before anything is written: links, alternate data streams, depth, entry
count, size and free space."""

import shutil
import zipfile
from collections import namedtuple

import pytest

from bayle.adapters.archives import extract
from bayle.modules.mods.models import ModError


def _zip(path, names, link=None):
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(n, b"x")
        if link:
            info = zipfile.ZipInfo(link)
            info.external_attr = 0o120777 << 16  # a Unix symlink entry
            z.writestr(info, b"../../outside")
    return path


@pytest.mark.parametrize(
    "names, link, why",
    [
        (["mod/ok.dcx", "mod/regulation.bin:evil"], None, "escapes"),  # an alternate data stream
        (["/".join(["d"] * (extract.MAX_DEPTH + 1))], None, "escapes"),
        (["mod/ok.dcx"], "mod/link", "link"),
    ],
)
def test_a_zip_with_a_bad_entry_writes_nothing(tmp_path, names, link, why):
    a = _zip(tmp_path / "m.zip", names, link)
    with pytest.raises(ModError, match=why):
        extract.extract_zip(a, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_caps_on_entries_size_and_free_space(tmp_path, monkeypatch):
    a = _zip(tmp_path / "m.zip", [f"mod/{i}.dcx" for i in range(4)])
    monkeypatch.setattr(extract, "MAX_ENTRIES", 3)
    with pytest.raises(ModError, match="entries"):
        extract.extract_zip(a, tmp_path / "o1")
    monkeypatch.setattr(extract, "MAX_ENTRIES", 10)
    monkeypatch.setattr(extract, "MAX_TOTAL", 3)
    with pytest.raises(ModError, match="more than any mod"):
        extract.extract_zip(a, tmp_path / "o2")
    monkeypatch.setattr(extract, "MAX_TOTAL", 10)
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: Usage(10, 7, 3))
    with pytest.raises(ModError, match="free"):
        extract.extract_zip(a, tmp_path / "o3")
    assert not any((tmp_path / f"o{i}").exists() for i in (1, 2, 3))
    monkeypatch.setattr(shutil, "disk_usage", lambda p: Usage(10, 0, 10))
    assert sorted(p.name for p in (extract.extract_zip(a, tmp_path / "o4") / "mod").iterdir()) == [
        "0.dcx",
        "1.dcx",
        "2.dcx",
        "3.dcx",
    ]


def test_a_7z_is_judged_by_its_list(tmp_path, monkeypatch):
    py7zr = pytest.importorskip("py7zr")
    (tmp_path / "src").mkdir()
    for i in range(3):
        (tmp_path / "src" / f"{i}.dcx").write_bytes(b"xy")
    a = tmp_path / "m.7z"
    with py7zr.SevenZipFile(a, "w") as z:
        z.writeall(tmp_path / "src", "mod")
    monkeypatch.setattr(extract, "MAX_TOTAL", 5)
    with pytest.raises(ModError, match="more than any mod"):
        extract.extract_7z(a, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_the_rar_list_from_bsdtar_is_read_with_links_and_names_with_spaces():
    text = (
        "-rw-rw-r--  0 0      0     1234 Jan 01  2020 Mod Folder/a file.dcx\n"
        "drwxrwxr-x  0 0      0        0 Jan 01  2020 Mod Folder\n"
        "lrwxrwxrwx  0 0      0        0 Jan 01  2020 Mod Folder/l -> ../../x\n"
    )
    assert extract.parse_bsdtar_listing(text) == [
        ("Mod Folder/a file.dcx", 1234, False),
        ("Mod Folder", 0, False),
        ("Mod Folder/l -> ../../x", 0, True),
    ]
    with pytest.raises(ModError, match="list"):
        extract.parse_bsdtar_listing("garbage")


def test_a_rar_is_refused_before_unpacking_when_its_list_fails_the_checks(tmp_path, monkeypatch):
    fake = tmp_path / "m.rar"
    fake.write_bytes(b"not really")
    monkeypatch.setattr(extract, "rar_tools", lambda: [["tar.exe", "-xf"]])
    monkeypatch.setattr(extract, "_rar_listing", lambda a: [("mod/x.dcx:ads", 1, False)])
    with pytest.raises(ModError, match="escapes"):
        extract.extract_rar(fake, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_a_shared_profile_zip_meets_the_same_limits(tmp_path):
    from bayle.modules.mods.profile_import import ZipSource

    a = _zip(tmp_path / "p.zip", ["mods/ok.dcx"], link="mods/link")
    with pytest.raises(ModError, match="link"):
        ZipSource(a, tmp_path / "root")
