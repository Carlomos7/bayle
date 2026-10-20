"""Seamless Co-op in the game folder (S9-Shell test T2): moving it into a profile puts everything back when the profile
cannot be written, and cleaning up never touches the settings file, the locale folder or the crash folders."""

from pathlib import Path

import pytest

from roundtable_souls.game import catalog
from roundtable_souls.mods import profile_writer
from roundtable_souls.services import coop

PROFILE = 'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n'


class Loc:
    game = catalog.ELDEN_RING

    def __init__(self, game_dir: Path):
        self._dir = game_dir

    def game_dir(self):
        return self._dir


class LaunchProfile:
    kind = "me3"
    game = catalog.ELDEN_RING

    def __init__(self, profile: Path, game_dir: Path):
        self.profile = str(profile)
        self.loc = Loc(game_dir)


@pytest.fixture
def game_folder(tmp_path):
    folder = tmp_path / "game" / "SeamlessCoop"
    (folder / "locale").mkdir(parents=True)
    (folder / "crashdumps").mkdir()
    (folder / "ersc.dll").write_bytes(b"dll")
    (folder / "ersc_settings.ini").write_text("[PASSWORD]\ncooppassword = x\n", encoding="utf-8")
    (folder / "locale" / "en.txt").write_text("hi", encoding="utf-8")
    (folder / "crashdumps" / "a.dmp").write_bytes(b"d")
    (folder / "old.log").write_text("log", encoding="utf-8")
    return tmp_path / "game"


def test_a_profile_that_cannot_be_written_gets_the_files_back(tmp_path, game_folder, monkeypatch):
    profile = tmp_path / "profiles" / "main.me3"
    profile.parent.mkdir()
    profile.write_text(PROFILE, encoding="utf-8")
    launch = LaunchProfile(profile, game_folder)
    found = coop.game_folder_seamless(launch)
    assert found is not None and found.kind == "move"
    before = sorted(p.name for p in (game_folder / "SeamlessCoop").iterdir())

    def refuse(self, *a, **k):
        raise OSError("the profile is locked")

    monkeypatch.setattr(profile_writer.ProfileWriter, "write", refuse)
    with pytest.raises(OSError):
        coop.move_seamless_into_profile(launch, found)
    assert sorted(p.name for p in (game_folder / "SeamlessCoop").iterdir()) == before
    assert (game_folder / "SeamlessCoop" / "ersc_settings.ini").read_text(encoding="utf-8").startswith("[PASSWORD]")
    assert not (tmp_path / "profiles" / "natives" / "SeamlessCoop").exists()
    assert profile.read_text(encoding="utf-8") == PROFILE


def test_cleaning_up_leaves_the_settings_file_the_locale_folder_and_the_crash_folders(tmp_path, game_folder):
    own = tmp_path / "profiles" / "natives" / "SeamlessCoop"
    own.mkdir(parents=True)
    (own / "ersc.dll").write_bytes(b"mine")
    (own / "ersc_settings.ini").write_text("[PASSWORD]\ncooppassword = mine\n", encoding="utf-8")
    profile = tmp_path / "profiles" / "main.me3"
    profile.write_text(PROFILE + f"\n[[natives]]\npath = '{own / 'ersc.dll'}'\nload_early = true\n", encoding="utf-8")
    launch = LaunchProfile(profile, game_folder)
    found = coop.game_folder_seamless(launch)
    assert found is not None and found.kind == "cleanup"
    names = {p.name for p in found.files}
    assert names.isdisjoint({"ersc_settings.ini", "locale", "crashdumps"}) and "old.log" in names
    assert (own / "ersc.dll").read_bytes() == b"mine"  # the profile's own copy is not in the list
