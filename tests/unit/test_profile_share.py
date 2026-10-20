"""Safety tests for Export / Import profile (S7e): the import rewrites players' profiles and settings files from
someone else's file. Synthetic profiles in temporary folders only."""

import json
import zipfile
from pathlib import Path

import pytest

from roundtable_souls.config.settings import load_settings
from roundtable_souls.merging.build import BuildError
from roundtable_souls.mods import profile_share, undo
from roundtable_souls.mods.profile_edit import ModError
from roundtable_souls.services import profile_transfer as pt
from support import er

PROFILE = (
    'profileVersion = "v1"\nsavefile = "ER0000.sl2"\n\n[[supports]]\ngame = "eldenring"\n\n'
    "[[natives]]\npath = 'natives/SeamlessCoop/ersc.dll'\nload_early = true\n\n"
    "[[packages]]\nid = \"flora\"\npath = 'mod/flora'\n\n"
    '[[packages]]\nid = "fauna"\npath = \'mod/fauna\'\nload_after = [{ id = "flora", optional = true }]\n'
)
INI = "[Main]\nvolume = 5\nname = a\n"


def make(root: Path, volume: int = 5) -> Path:
    for rel, data in {
        "mod/flora/flora.ini": INI.replace("5", str(volume)),
        "mod/flora/parts/a.dcx": "flora",
        "mod/fauna/fauna.ini": "[Main]\nspeed = 1\n",
        "natives/SeamlessCoop/ersc.dll": "dll",
        "natives/SeamlessCoop/ersc_settings.ini": "[PASSWORD]\ncooppassword = secret\n[SCALING]\nlevel = 1\n",
    }.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data.replace("\n", "\r\n").encode())
    me3 = root / "my.me3"
    me3.write_bytes(PROFILE.replace("\n", "\r\n").encode())
    return me3


def export(profile: Path, **kw) -> dict:
    doc, _ = pt.share_list(profile, loc=er(), settings=load_settings(), name="Mine", **kw)
    return doc


def incoming(tmp_path: Path, doc: dict) -> pt.Incoming:
    f = tmp_path / "in.json"
    f.write_text(json.dumps(doc), encoding="utf-8")
    return pt.read(f, loc=er())


def tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_untrusted_keys_write_nothing_outside_the_matched_mods(tmp_path):
    prof = make(tmp_path / "me")
    doc = export(prof)
    evil = {
        "../x.ini": "a = 1",
        "/abs.ini": "a = 1",
        "C:/x.ini": "a = 1",
        "flora/sub/../../x.ini": "a = 1",
        "flora\\..\\x.ini": "a = 1",
        "flora/evil.dll": "MZ",
        "flora/a.txt:b.ini": "x = 1",
        "ghost/ghost.ini": "volume = 9",
        "flora/flora.ini": "[Main]\nvolume = 9\n",
    }
    doc["configs"] = evil
    doc["settings"] = {"savefile": "..\\..\\x.sl2", "start_online": True}
    inc = incoming(tmp_path, doc)
    assert set(inc.share.configs) == {("ghost", "ghost.ini"), ("flora", "flora.ini")}
    assert len(inc.share.skipped) == 7
    before = tree(tmp_path)
    pre = pt.preview(inc, prof, loc=er(), settings=load_settings())
    assert any("ghost" in s for s in pre.skipped)  # no such mod in this profile
    assert not any(c.key == pt.PROFILE_CARD for c in pre.cards)  # savefile and start_online were not applied
    pt.apply(pre)
    after = tree(tmp_path)
    changed = {k for k in after if before.get(k) != after[k]} - {
        k for k in after if ".roundtable" in k or k.endswith(".bak")
    }
    assert changed == {"me/mod/flora/flora.ini"}
    assert b"volume = 9" in after["me/mod/flora/flora.ini"]
    ok, left = profile_share.usable_settings({"savefile": "CON.sl2", "start_online": True})
    assert ok == {} and len(left) == 2
    assert profile_share.usable_settings({"savefile": "Other.sl2", "start_online": False})[0] == {
        "savefile": "Other.sl2",
        "start_online": False,
    }
    for bad in ({"format": "other"}, {"version": 2}, {"game": "nightreign"}):
        with pytest.raises(profile_share.ShareError):
            incoming(tmp_path, {**export(prof), **bad})


def test_round_trip_changes_only_the_listed_values_and_undo_restores_the_bytes(tmp_path):
    src, dst = make(tmp_path / "a", 7), make(tmp_path / "b", 5)
    doc = export(src)
    assert "cooppassword" not in json.dumps(doc["configs"])  # the password is left out
    before = tree(tmp_path / "b")
    pre = pt.preview(incoming(tmp_path, doc), dst, loc=er(), settings=load_settings())
    assert {c.key for c in pre.cards} == {"flora/flora.ini"}
    pt.apply(pre)
    got = (tmp_path / "b/mod/flora/flora.ini").read_bytes()
    assert got == before["mod/flora/flora.ini"].replace(b"volume = 5", b"volume = 7")
    assert (tmp_path / "b/mod/fauna/fauna.ini").read_bytes() == before["mod/fauna/fauna.ini"]
    assert dst.read_bytes() == before["my.me3"]  # nothing in the profile differs
    # an unticked file stays
    pre = pt.preview(incoming(tmp_path, doc), dst, loc=er(), settings=load_settings())
    assert not pre.cards  # already the same
    ini = tmp_path / "b/mod/flora/flora.ini"
    ini.write_bytes(before["mod/flora/flora.ini"])
    pre = pt.preview(incoming(tmp_path, doc), dst, loc=er(), settings=load_settings())
    with pytest.raises(ModError):  # nothing ticked
        pt.apply(pre, skip={"flora/flora.ini"})
    assert (tmp_path / "b/mod/flora/flora.ini").read_bytes() == before["mod/flora/flora.ini"]
    doc["settings"] = {"savefile": "Other.sl2"}
    pre = pt.preview(incoming(tmp_path, doc), dst, loc=er(), settings=load_settings())
    out = pt.apply(pre)
    assert b'savefile = "Other.sl2"' in dst.read_bytes() and b"volume = 7" in ini.read_bytes()
    rec = {"type": "profile-import", "profile": str(dst), "name": dst.name, "operation": out["operation"]}
    undo.run(rec, lambda s: None, loc=er())
    assert (tmp_path / "b/mod/flora/flora.ini").read_bytes() == before["mod/flora/flora.ini"]
    assert dst.read_bytes() == before["my.me3"]


def test_a_file_changed_after_the_preview_refuses_the_whole_import(tmp_path):
    src, dst = make(tmp_path / "a", 7), make(tmp_path / "b", 5)
    doc = export(src)
    doc["settings"] = {"savefile": "Other.sl2"}
    pre = pt.preview(incoming(tmp_path, doc), dst, loc=er(), settings=load_settings())
    assert {c.key for c in pre.cards} == {pt.PROFILE_CARD, "flora/flora.ini"}
    me3_before = dst.read_bytes()
    ini = tmp_path / "b/mod/flora/flora.ini"
    ini.write_bytes(ini.read_bytes() + b"; edited meanwhile\r\n")
    edited = ini.read_bytes()
    with pytest.raises(BuildError):
        pt.apply(pre)
    assert dst.read_bytes() == me3_before and ini.read_bytes() == edited


def test_a_full_export_imports_as_a_new_profile_without_the_save_or_an_exe(tmp_path, monkeypatch):
    src, dst = make(tmp_path / "a", 7), make(tmp_path / "b", 5)
    (tmp_path / "a" / "me3.exe").write_bytes(b"never")  # beside the profile, not part of any mod
    save = tmp_path / "ER0000.sl2"
    save.write_bytes(b"save")
    monkeypatch.setattr(type(er()), "save_files", lambda self: [save])
    items = pt.items(src, full=True)
    out = pt.full_export(
        src,
        loc=er(),
        settings=load_settings(),
        name="Pack",
        version="1",
        author="me",
        readme="# Pack\n",
        changelog="",
        chosen={it.key for it in items},
        out_dir=tmp_path / "out",
        with_save=True,
    )
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    assert "save/ER0000.sl2" in names and "manifest.json" in names
    zin = tmp_path / "pack2.zip"
    with zipfile.ZipFile(out) as a, zipfile.ZipFile(zin, "w") as b:
        for info in a.infolist():
            data = a.read(info)
            if info.filename == "manifest.json":
                doc = json.loads(data)
                doc["settings"] = {"savefile": "New.sl2", "start_online": True}
                data = json.dumps(doc).encode()
            b.writestr(info.filename, data)
    inc = pt.read(zin, loc=er())
    try:
        pre = pt.preview(inc, dst, loc=er(), settings=load_settings(), new_name="Imported")
        assert not pre.refusals, pre.refusals
        pt.apply(pre)
        new = dst.parent / "imported.me3"
        text = new.read_text(encoding="utf-8")
        assert 'savefile = "New.sl2"' in text and "start_online" not in text
        assert (dst.parent / "mod" / "flora-2" / "flora.ini").read_bytes().count(b"volume = 7") == 1
        assert not any(p.name in ("me3.exe", "ER0000.sl2") for p in dst.parent.rglob("*"))
        assert any("save" in n for n in pre.notes)
    finally:
        pt.discard(inc)


def test_a_cancelled_full_export_leaves_no_zip_and_no_temp_file(tmp_path):
    src = make(tmp_path / "a", 7)
    items = pt.items(src, full=True)
    with pytest.raises(pt.ExportCancelled):
        pt.full_export(
            src,
            loc=er(),
            settings=load_settings(),
            name="Pack",
            version="1",
            author="me",
            readme="",
            changelog="",
            chosen={it.key for it in items},
            out_dir=tmp_path / "out",
            cancelled=lambda: True,
        )
    assert list((tmp_path / "out").iterdir()) == []


def test_importing_a_full_export_reuses_an_identical_installed_folder_and_undo_leaves_it(tmp_path):
    src, dst = make(tmp_path / "a", 7), make(tmp_path / "b", 7)  # the same mod, byte for byte, on both sides
    out = pt.full_export(
        src,
        loc=er(),
        settings=load_settings(),
        name="Pack",
        version="1",
        author="me",
        readme="",
        changelog="",
        chosen={it.key for it in pt.items(src, full=True)},
        out_dir=tmp_path / "out",
    )
    flora = tmp_path / "b/mod/flora"
    before = {p.relative_to(flora).as_posix(): p.read_bytes() for p in flora.rglob("*") if p.is_file()}
    inc = pt.read(out, loc=er())
    try:
        pre = pt.preview(inc, dst, loc=er(), settings=load_settings(), new_name="Imported")
        assert not pre.refusals, pre.refusals
        assert pre.zip_preview.reused and not pre.zip_preview.copies and pre.zip_preview.saved > 0
        res = pt.apply(pre)
        assert not (tmp_path / "b/mod/flora-2").exists()
        assert "flora" in (dst.parent / "imported.me3").read_text(encoding="utf-8")
        rec = {
            "type": "profile-import",
            "profile": res["profile"],
            "name": "imported.me3",
            "operation": res["operation"],
        }
        undo.run(rec, lambda s: None, loc=er())
        assert {p.relative_to(flora).as_posix(): p.read_bytes() for p in flora.rglob("*") if p.is_file()} == before
    finally:
        pt.discard(inc)


def test_undoing_an_import_into_a_new_profile_removes_it_and_its_coop_copy_and_nothing_else(tmp_path):
    src, dst = make(tmp_path / "a", 7), make(tmp_path / "b", 5)
    (tmp_path / "b/natives/SeamlessCoop/ersc.dll").write_bytes(b"another build")  # differs, so it is copied
    other = tmp_path / "b" / "other.me3"
    other.write_bytes(b'profileVersion = "v1"\n')
    out = pt.full_export(
        src,
        loc=er(),
        settings=load_settings(),
        name="Pack",
        version="1",
        author="me",
        readme="",
        changelog="",
        chosen={it.key for it in pt.items(src, full=True)},
        out_dir=tmp_path / "out",
    )
    before = tree(tmp_path / "b")
    inc = pt.read(out, loc=er())
    try:
        pre = pt.preview(inc, dst, loc=er(), settings=load_settings(), new_name="Imported")
        assert not pre.refusals, pre.refusals
        res = pt.apply(pre)
        assert (tmp_path / "b/natives/seamlesscoop-2/ersc.dll").is_file() and (tmp_path / "b/imported.me3").is_file()
        rec = {
            "type": "profile-import",
            "profile": res["profile"],
            "name": "imported.me3",
            "operation": res["operation"],
        }
        undo.run(rec, lambda s: None, loc=er())
        assert not (tmp_path / "b/imported.me3").exists() and not (tmp_path / "b/natives/seamlesscoop-2").exists()
        after = {k: v for k, v in tree(tmp_path / "b").items() if not k.startswith(".roundtable")}
        assert after == before  # the other profile and the original co-op folder are untouched
    finally:
        pt.discard(inc)


def test_an_apply_whose_unpacking_fails_partway_leaves_no_staging_folder_and_no_change(tmp_path):
    src, dst = make(tmp_path / "a", 7), make(tmp_path / "b", 5)
    (tmp_path / "a/mod/flora/parts/a.dcx").write_bytes(b"UNIQUEDATA1234")
    out = pt.full_export(
        src,
        loc=er(),
        settings=load_settings(),
        name="Pack",
        version="1",
        author="me",
        readme="",
        changelog="",
        chosen={it.key for it in pt.items(src, full=True)},
        out_dir=tmp_path / "out",
    )
    inc = pt.read(out, loc=er())
    try:
        pre = pt.preview(inc, dst, loc=er(), settings=load_settings(), new_name="Imported")
        assert not pre.refusals, pre.refusals
        out.write_bytes(out.read_bytes().replace(b"UNIQUEDATA1234", b"UNIQUEDATA1235"))  # a bad CRC, found mid-unpack
        before = tree(tmp_path / "b")
        with pytest.raises(ModError):
            pt.apply(pre)
        assert {k: v for k, v in tree(tmp_path / "b").items() if not k.startswith(".roundtable")} == before
        assert not any(".staging" in p.name for p in (tmp_path / "b").rglob("*"))
        assert not (tmp_path / "b/imported.me3").exists()
    finally:
        pt.discard(inc)


def _pack(tmp_path: Path, volume: int) -> Path:
    src = make(tmp_path / "a", volume)
    return pt.full_export(
        src,
        loc=er(),
        settings=load_settings(),
        name="Pack",
        version="1",
        author="me",
        readme="",
        changelog="",
        chosen={it.key for it in pt.items(src, full=True) if it.entry.get("id") == "flora"},
        out_dir=tmp_path / "out",
    )


def test_use_the_incoming_copy_replaces_the_folder_in_the_current_profile_and_undo_restores_the_old_bytes(tmp_path):
    zipped = _pack(tmp_path, 7)
    dst = make(tmp_path / "b", 5)  # same mods, but flora's settings file differs
    flora = tmp_path / "b/mod/flora"
    before = tree(flora)
    inc = pt.read(zipped, loc=er())
    try:
        pre = pt.preview(inc, dst, loc=er(), settings=load_settings())
        assert not pre.refusals, pre.refusals
        assert [c.key for c in pre.zip_preview.clashes] == ["flora"] and pre.zip_preview.undecided == ["flora"]
        pre = pt.preview(inc, dst, loc=er(), settings=load_settings(), choices={"flora": "incoming"})
        assert not pre.refusals, pre.refusals
        res = pt.apply(pre)
        assert not (tmp_path / "b/mod/flora-2").exists() and tree(flora) != before
        assert b"volume = 7" in (flora / "flora.ini").read_bytes()
        rec = {"type": "profile-import", "profile": res["profile"], "name": "my.me3", "operation": res["operation"]}
        undo.run(rec, lambda s: None, loc=er())
        assert tree(flora) == before
    finally:
        pt.discard(inc)


def test_a_folder_another_profile_lists_is_never_replaced_and_this_profile_gets_name_2(tmp_path):
    zipped = _pack(tmp_path, 7)
    dst = make(tmp_path / "b", 5)
    (tmp_path / "b/friend.me3").write_text("[[packages]]\nid = \"flora\"\npath = 'mod/flora'\n", encoding="utf-8")
    flora = tmp_path / "b/mod/flora"
    before = tree(flora)
    inc = pt.read(zipped, loc=er())
    try:
        pre = pt.preview(inc, dst, loc=er(), settings=load_settings(), choices={"flora": "incoming"})
        assert not pre.refusals, pre.refusals
        assert pre.zip_preview.clashes[0].shared and pre.zip_preview.undecided == []
        pt.apply(pre)
        assert tree(flora) == before  # the other profile's mod is untouched
        assert b"volume = 7" in (tmp_path / "b/mod/flora-2/flora.ini").read_bytes()
    finally:
        pt.discard(inc)
