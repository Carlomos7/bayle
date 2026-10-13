"""services.game_checks (3.22-B P3, P6, M1): online with changed parameters, the regulation's fingerprint, and what
me3's failed fast loading means. A made-up game folder, profile and me3 log only."""

import hashlib

import pytest

from roundtable_souls.game import catalog as games
from roundtable_souls.game.locate import Locations, Overrides
from roundtable_souls.services import game_checks

PROFILE = """profileVersion = "v1"
{online}
[[packages]]
id = "body"
path = 'body'

[[packages]]
id = "params"
path = 'params'
"""


@pytest.fixture
def world(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    (game / "eldenring.exe").write_bytes(b"MZ")
    (game / "regulation.bin").write_bytes(b"the game's own")
    for name in ("body", "params"):
        (tmp_path / name).mkdir()
    profile = tmp_path / "p.me3"
    profile.write_text(PROFILE.format(online=""), encoding="utf-8")
    loc = Locations(games.ELDEN_RING, Overrides(game_exe=str(game / "eldenring.exe")))
    return tmp_path, profile, loc


def test_the_game_uses_the_last_packages_regulation_else_its_own(world):
    root, profile, loc = world
    assert game_checks.active_regulation(profile, loc) == game_checks.Regulation(root / "game/regulation.bin", "")
    (root / "params/regulation.bin").write_bytes(b"changed")
    assert game_checks.active_regulation(profile, loc) == game_checks.Regulation(
        root / "params/regulation.bin", "params"
    )


def test_going_online_with_a_packages_parameters_is_warned_about(world):
    root, profile, loc = world
    (root / "params/regulation.bin").write_bytes(b"changed")
    assert game_checks.online_warning(profile, loc) is None  # offline (me3's default)
    profile.write_text(PROFILE.format(online="start_online = true\n"), encoding="utf-8")
    assert game_checks.online_warning(profile, loc) == (
        "this profile goes online with changed parameters (params's regulation.bin). Online, the game sends a "
        "fingerprint of its parameters to FromSoftware's servers, which can see the change and can send the game "
        "their own parameters. Turn Online matchmaking off in Profile settings to play offline."
    )
    (root / "params/regulation.bin").unlink()
    assert game_checks.online_warning(profile, loc) is None  # the game's own parameters


def test_the_fingerprint_names_the_regulation_in_use(world):
    root, profile, loc = world
    (root / "params/regulation.bin").write_bytes(b"changed")
    got = game_checks.regulation_fingerprint(profile, loc)
    assert got == game_checks.Fingerprint(hashlib.sha256(b"changed").hexdigest()[:8].upper(), 7, "params")
    assert (
        got is not None
        and got.text() == f"Parameters: {got.short}, 7 bytes (params's regulation.bin); co-op partners need the same"
    )
    (root / "params/regulation.bin").unlink()
    own = game_checks.regulation_fingerprint(profile, loc)
    assert own is not None and own.text().endswith("(the game's own regulation.bin); co-op partners need the same")


KEYS = {
    "Data0": "-----BEGIN RSA PUBLIC KEY-----\nAAAA\nBBBB\n-----END RSA PUBLIC KEY-----",
    "DLC": "-----BEGIN RSA PUBLIC KEY-----\nCCCC\nDDDD\n-----END RSA PUBLIC KEY-----",
}


def failed(name: str) -> str:
    """One me3 log line as me3 0.13 writes it: colour codes, the key on the following lines."""
    return (
        "\x1b[31mERROR\x1b[0m \x1b[1massets\x1b[0m:\x1b[1mmount_ebl\x1b[0m: \x1b[3merror\x1b[0m\x1b[2m=\x1b[0m"
        f"trampoline returned null \x1b[3mkey\x1b[0m\x1b[2m=\x1b[0m{KEYS[name]}\n\n"
    )


def test_me3s_failed_dlc_loading_is_said_once_or_as_the_likely_cause():
    assert game_checks.me3_mount_failures("INFO all fine\n", KEYS) == []
    assert game_checks.me3_mount_failures("x\n" + failed("DLC"), KEYS) == [
        "me3's fast DLC loading failed this launch; if your DLC was missing, that's why; Play again."
    ]
    assert game_checks.me3_mount_failures(failed("DLC") + "later\n" + failed("DLC"), KEYS) == [
        "me3's fast DLC loading failed 2 times this launch: that is the likely reason if your DLC was missing; "
        "Play again."
    ]
    assert game_checks.me3_mount_failures(failed("Data0"), KEYS) == [
        "me3's fast loading of the game's Data0 archive failed this launch (1 time); if parts of the game were "
        "missing, that's why; Play again."
    ]


def test_the_shipped_dlc_key_is_recognised():
    from roundtable_souls.game import config as game_config

    pem = dict(game_config.load().archives)["DLC"]
    line = f"error=trampoline returned null key={pem}\n"
    assert game_checks.me3_mount_failures(line) == [
        "me3's fast DLC loading failed this launch; if your DLC was missing, that's why; Play again."
    ]
