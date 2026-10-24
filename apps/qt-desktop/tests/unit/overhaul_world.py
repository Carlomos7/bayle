"""Builders the desktop's overhaul tests share, copied from the engine's tests (test_overhaul_install, test_engine,
test_param_merge, test_mod_configs_ops): a profile folder with an Example-like download, small regulation files built
here, a game stand-in. Copied, not imported, so the two projects' tests stay independent."""

import json
import struct
import subprocess
import tomllib
from pathlib import Path

import fakegame
from bayle import formats, overhauls
from bayle.game import catalog, locate
from bayle.game import config as game_config
from bayle.game.locate import Locations, Overrides
from bayle.mods import library, overhaul_install
from bayle.platform import paths as common
from bayle.platform import trash as real_trash
from fakegame import bnd, dcx, fmg

DCX = (  # the 0x4C header of the game's regulation (sizes are filled in on write)
    b"DCX\0"
    + struct.pack(">IIIII", 0x11000, 0x18, 0x24, 0x44, 0x4C)
    + b"DCS\0"
    + struct.pack(">II", 0, 0)
    + b"DCP\0ZSTD"
    + struct.pack(">IIIIII", 0x20, 0x15000000, 0, 0, 0, 0x10100)
    + b"DCA\0"
    + struct.pack(">I", 8)
)
assert len(DCX) == 0x4C


STRIDE = 16


def table(type_name: str, rows, stride: int = STRIDE, names=None) -> formats.param.Param:
    header = bytearray(0x40)
    struct.pack_into("<H", header, 0x06, 1)
    header[0x2D], header[0x2E] = 0x85, 7
    struct.pack_into("<q", header, 0x10, 0x40)
    tail = type_name.encode() + b"\0" + b"\0\0\0\0"
    p = formats.param.Param(bytes(header), [], stride, tail, len(type_name) + 1, True, data_end=0x40)
    p.rows = [formats.param.Row(i, bytes(d), (names or {}).get(i, "")) for i, d in rows]
    return p


def row(*words: int, stride: int = STRIDE) -> bytes:
    data = b"".join(struct.pack("<I", w) for w in words)
    return data + bytes(stride - len(data))


def regulation(tables: dict, version: str = "11711000") -> bytes:
    hdr = bytearray(0x40)
    hdr[0:4] = b"BND4"
    hdr[0x08:0x0C] = bytes.fromhex("00000100")
    struct.pack_into("<q", hdr, 0x10, 0x40)
    hdr[0x18:0x20] = version.encode()
    struct.pack_into("<q", hdr, 0x20, 36)
    hdr[0x30:0x34] = bytes([1, 0x74, 4, 0])
    entries = [
        formats.bnd4.Entry(f"N:\\GR\\data\\Param\\param\\GameParam\\{n}.param", i, formats.param.write_param(p))
        for i, (n, p) in enumerate(tables.items())
    ]
    binder = formats.bnd4.Bnd4(bytes(hdr), formats.regulation.REGULATION_FORMAT, 0x74, True, 4, entries)
    return formats.regulation.write_regulation(formats.regulation.Regulation(DCX, binder))


def vanilla(version="11711000") -> bytes:
    return regulation(
        {
            "EquipParamWeapon": table("EQUIP_PARAM_WEAPON_ST", [(1000, row(1, 2, 3, 4)), (2000, row(5, 6, 7, 8))]),
            "SpEffectParam": table("SP_EFFECT_PARAM_ST", [(10, row(9, 9, 9, 9))]),
        },
        version,
    )


def pack(edits: dict, version="11711000", base=None) -> bytes:
    """A pack: the vanilla regulation with edits {table: fn(param)} applied."""
    reg = formats.regulation.read_regulation(base or vanilla(version))
    for name, fn in edits.items():
        f = reg.bnd.get(name + ".param")
        p = formats.param.read_param(f.data)
        fn(p)
        f.data = formats.param.write_param(p)
    return formats.regulation.write_regulation(reg)


def set_word(rid, i, value):
    def fn(p):
        r = next(x for x in p.rows if x.id == rid)
        d = bytearray(r.data)
        struct.pack_into("<I", d, i * 4, value)
        r.data = bytes(d)

    return fn


PAYLOAD = [
    "payload/ExamplePrototype.dll",
    "payload/ExampleHudBootstrap.dll",
    "payload/audio/example.wav",
    "payload/ui/base.png",
    "payload/settings/m00_00_00_00.talkesdbnd.dcx",
]
ARCHIVES = ["chr/c0000.anibnd.dcx", "chr/c0000.behbnd.dcx", "chr/c0000_a00_hi.anibnd.dcx", "chr/c0000_a00_md.anibnd.dcx",
            "chr/c0000_a00_lo.anibnd.dcx", "sfx/sfxbnd_commoneffects.ffxbnd.dcx"]  # fmt: skip
GAME_CLIPS = {"a000_000.hkx": b"walk", "a000_001.hkx": b"run", "a000_002.hkx": b"roll"}


def game_files() -> dict[str, bytes]:
    files = {rel: dcx(bnd(GAME_CLIPS)) for rel in ARCHIVES}
    for lang in game_config.load().languages:
        files[f"msg/{lang}/menu_dlc02.msgbnd.dcx"] = dcx(
            bnd({"EventTextForTalk.fmg": fmg({1000: "Rest", 1001: None}), "Other.fmg": fmg({5: "x"})})
        )
    return files


PROFILE = """profileVersion = "v1"
start_online = true

# my mods
[[packages]]
id = "body"
path = 'mod/body'

[[packages]]
id = "anims"
path = 'mod/anims'

[[natives]]
path = 'natives/SeamlessCoop/ersc.dll'
load_early = true
"""


class Bin:
    """A Recycle Bin in a temporary folder: send moves an item there, restore puts it back."""

    TrashError = real_trash.TrashError

    def __init__(self, root: Path):
        self.root = root
        self.n = 0

    def available(self) -> bool:
        return True

    def send(self, path: Path) -> dict:
        self.n += 1
        item = self.root / f"R{self.n}"
        self.root.mkdir(parents=True, exist_ok=True)
        Path(path).replace(item)
        return {"kind": "test", "item": str(item), "original": str(path)}

    def exists(self, record) -> bool:
        return bool(record) and Path(record["item"]).exists()

    def restore(self, record) -> Path:
        Path(record["original"]).parent.mkdir(parents=True, exist_ok=True)  # as platform.trash.restore does
        Path(record["item"]).replace(record["original"])
        return Path(record["original"])


class World:
    def __init__(self, tmp_path: Path, monkeypatch):
        self.tmp = tmp_path
        self.profiles = tmp_path / "me3" / "profiles"
        self.base = self.profiles / "eldenring-mods"
        self.game = tmp_path / "Game"
        self.game.mkdir(parents=True)
        (self.game / "regulation.bin").write_bytes(vanilla())
        (self.game / "eldenring.exe").write_bytes(b"x")
        fakegame.game(monkeypatch, game_files())
        monkeypatch.setattr(locate, "installed_dir", lambda _game: self.game)
        monkeypatch.setattr(common, "exe_running", lambda _exe: False)
        self.loc = Locations(catalog.ELDEN_RING, Overrides(profiles_dir=str(self.profiles)))
        self.download = self.make_download(tmp_path / "Downloads" / "ExampleOverhaul-LITE-0.1.33-rc3")
        body = self.base / "mod" / "body"
        (body / "parts").mkdir(parents=True)
        anims = self.base / "mod" / "anims"
        (anims / "chr").mkdir(parents=True)
        (anims / "chr/c0000_a00_hi.anibnd.dcx").write_bytes(dcx(bnd({"a000_000.hkx": b"sekiro walk"})))
        (anims / "regulation.bin").write_bytes(pack({"EquipParamWeapon": set_word(1000, 0, 55)}))
        (self.base / "natives/SeamlessCoop").mkdir(parents=True)
        (self.base / "natives/SeamlessCoop/ersc.dll").write_bytes(b"d")
        self.profile = self.base / "my.me3"
        self.profile.write_text(PROFILE, encoding="utf-8")
        self.own = self.base / "ExampleOverhaul"
        self.bin = Bin(tmp_path / "bin")
        monkeypatch.setattr(overhaul_install, "trash", self.bin)

        def no_programs(*args, **kwargs):
            raise AssertionError(f"a program was started: {args[0] if args else kwargs}")

        monkeypatch.setattr(subprocess, "run", no_programs)
        monkeypatch.setattr(subprocess, "Popen", no_programs)

    @staticmethod
    def make_download(top: Path, version: str = "0.1.33-rc3", edition: str = "LITE") -> Path:
        """Example's download as its archive unpacks: a folder named after the edition inside."""
        d = top / f"ExampleOverhaul-{edition}"
        for f in PAYLOAD:
            (d / f).parent.mkdir(parents=True, exist_ok=True)
            (d / f).write_bytes(f"{version} {f}".encode())
        (d / "payload/ExamplePrototype.ini").write_text("[Coop]\nEnabled=1\n")
        for rel in ARCHIVES:
            (d / "payload/mod" / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / "payload/mod" / rel).write_bytes(dcx(bnd({**GAME_CLIPS, "example.hkx": b"example"})))
        (d / "payload/mod/regulation.bin").write_bytes(pack({"EquipParamWeapon": set_word(2000, 1, 77)}))
        (d / "payload/settings/engus.json").write_text('{"99002000": "Example: session settings"}')
        (d / "payload/settings/rusru.json").write_text('{"99002000": "Example ru"}', encoding="utf-8")
        for lang in ("engus", "rusru"):  # the game's text per language, a fallback the text step names
            (d / f"payload/settings/vanilla/msg/{lang}").mkdir(parents=True)
            (d / f"payload/settings/vanilla/msg/{lang}/menu_dlc02.msgbnd.dcx").write_bytes(
                dcx(bnd({"EventTextForTalk.fmg": fmg({1000: "Rest"})}))
            )
        (d / "payload/settings/vanilla/script/talk").mkdir(parents=True)
        (d / "payload/settings/vanilla/script/talk/m00.bin").write_bytes(b"unused")
        (d / "payload/mod/action/script").mkdir(parents=True)
        (d / "payload/mod/action/script/c0000.hks").write_text(
            "-- vanilla\nfunction Update() end\n-- Wrap the current mod's Update;\nexample stock wrapper\n"
        )
        (d / "installer").mkdir()
        (d / "installer/example.hks").write_text("-- example extension\n")
        (d / "installer/setup.py").write_text("# the mod's installer")
        (d / "tools/python").mkdir(parents=True)
        (d / "tools/python/python.exe").write_bytes(b"py")
        (d / "licenses").mkdir()
        (d / "licenses/lupa.txt").write_text("MIT")
        (d / "Install.cmd").write_text("@echo off")
        (d / "edition.json").write_text(json.dumps({"version": version, "edition": edition}))
        return d

    def preview(self, download=None, **kw):
        return overhaul_install.preview_install(self.profile, download or self.download.parent, loc=self.loc, **kw)

    def install(self, download=None):
        p = self.preview(download)
        assert p.ok, p.refusals
        return overhaul_install.install(p, loc=self.loc)

    def text(self) -> str:
        return self.profile.read_text(encoding="utf-8")

    def data(self) -> dict:
        return tomllib.loads(self.text())

    @property
    def library(self) -> Path:
        return library.ProfileFolder.of(self.profile).root


def files(folder: Path) -> dict[str, bytes]:
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in Path(folder).rglob("*")
        if p.is_file()
        and not p.relative_to(folder).as_posix().startswith((".bayle", ".roundtable"))
        and ".bak" not in p.suffixes
        and "history" not in p.parts
    }


def legacy(world) -> None:
    """Example's installer's setup: its folder with its manifest, its setup copy, its backup of the profile before."""
    world.own.mkdir()
    (world.own / "mod").mkdir()
    (world.own / "mod/regulation.bin").write_bytes(b"x" * 3000)
    (world.own / "ExamplePrototype.dll").write_bytes(b"d")
    (world.own / "installation.json").write_text(json.dumps({"version": "0.1.33-rc3", "sources": []}))
    setup = world.base / ".example-overhaul-setup"
    (setup / "payload").mkdir(parents=True)
    (setup / "payload/big.bin").write_bytes(b"y" * 5000)
    for stamp, start_online in (("20260101-000000-000000", "true"), ("20260201-000000-000000", "false")):
        b = world.base / "Example Backups" / stamp
        b.mkdir(parents=True)
        (b / "file-0").write_text(PROFILE.replace("start_online = true", f"start_online = {start_online}"))
        (b / "restore.json").write_text(
            json.dumps({"files": [{"path": str(world.profile), "original": "file-0"}], "directories": []})
        )
    world.profile.write_text(
        PROFILE.replace("start_online = true", "start_online = false")
        + "\n[[natives]]\npath = 'ExampleOverhaul/ExamplePrototype.dll'\n"
        + "\n[[packages]]\nid = \"example-overhaul\"\npath = 'ExampleOverhaul/mod'\n",
        encoding="utf-8",
    )


def mixed_mod(world) -> Path:
    """A mod no config describes: game files and a DLL with its settings."""
    m = world.tmp / "Downloads" / "Mixed Mod"
    (m / "chr").mkdir(parents=True)
    (m / "chr/c0000_a00_hi.anibnd.dcx").write_bytes(dcx(bnd({**GAME_CLIPS, "mine.hkx": b"mine"})))
    (m / "regulation.bin").write_bytes(pack({"EquipParamWeapon": set_word(2000, 0, 9)}))
    (m / "MixedMod.dll").write_bytes(b"d")
    (m / "MixedMod.ini").write_text("[a]\nb=1\n")
    return m


def set_up(world) -> tuple[Path, Path, dict]:
    from bayle.overhauls import basic

    folder = mixed_mod(world)
    config = basic.make(id="mixed-mod", label="Mixed Mod", game="eldenring", basic=basic.propose(folder), folder=folder)
    p = overhaul_install.preview_setup(world.profile, folder, config, loc=world.loc)
    assert p.ok, p.refusals
    out = overhaul_install.install_setup(p, loc=world.loc)
    local = overhauls.local_dir()
    assert local is not None
    toml = local / "mixed-mod.toml"
    assert overhauls.read(toml) == config
    return folder, toml, out


def other_of(world) -> Path:
    """A second DLL of the profile with a settings file of its own (listed in the tree)."""
    folder = world.base / "natives/Other"
    folder.mkdir(parents=True)
    (folder / "other.dll").write_bytes(b"d")
    (folder / "other.ini").write_bytes(b"[a]\r\nb = 1\r\nc = 2\r\n")
    world.profile.write_text(PROFILE + "\n[[natives]]\npath = 'natives/Other/other.dll'\n", encoding="utf-8")
    return folder / "other.ini"
