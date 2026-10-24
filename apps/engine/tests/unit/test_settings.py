"""The pydantic settings file: defaults, tolerance of broken files, unknown keys kept, atomic merge."""

import json

from bayle.config import settings


def test_defaults_when_missing_or_broken(tmp_path):
    assert settings.load_settings().theme == "dark"
    settings.settings_path().write_text("{not json", encoding="utf-8")
    assert settings.load_settings().play_repair_after is True


def test_save_merges_and_keeps_unknown_keys():
    settings.settings_path().write_text(json.dumps({"future_key": 1, "theme": "light"}), encoding="utf-8")
    settings.save_settings(play_show_logos=True)
    on_disk = json.loads(settings.settings_path().read_text(encoding="utf-8"))
    assert on_disk["future_key"] == 1 and on_disk["theme"] == "light" and on_disk["play_show_logos"] is True
    assert not settings.settings_path().with_suffix(".json.tmp").exists()


def test_invalid_value_falls_back_to_default_for_that_key():
    settings.settings_path().write_text(json.dumps({"theme": "purple", "me3_path": "x"}), encoding="utf-8")
    loaded = settings.load_settings()
    assert loaded.theme == "dark" and loaded.me3_path == "x"


def test_the_file_keeps_its_keys():
    """An older build restored by the update watchdog reads the same flat file: a save writes back every key it
    had (another build's included), and the keys declared later only once something sets them."""
    old = settings.LauncherSettings().model_dump(by_alias=True)
    for key in settings.WRITTEN_WHEN_SET:
        old.pop(key)
    old["from_a_newer_build"] = {"x": 1}
    settings.settings_path().write_text(json.dumps(old), encoding="utf-8")
    settings.save_settings(theme="light")
    written = json.loads(settings.settings_path().read_text(encoding="utf-8"))
    assert set(written) == set(old) and written["theme"] == "light" and written["from_a_newer_build"] == {"x": 1}
    settings.save_settings(update_blocked=["9.9.9"])
    written = json.loads(settings.settings_path().read_text(encoding="utf-8"))
    assert written["update_blocked"] == ["9.9.9"] and "inno_migration" not in written
    assert settings.load_settings().update_blocked == ["9.9.9"]


def test_the_launch_profile_keeps_the_file_key_setup():
    """T7: the field is `profile`, the key on disk stays `setup` (top level and per game), so a build restored after a
    rollback still reads it; an old-format file loads and a save writes the same keys and keeps unknown ones."""
    old = {"setup": "a.me3", "games": {"nightreign": {"setup": "nr.me3", "game_exe": "x.exe"}}, "future_key": [1]}
    settings.settings_path().write_text(json.dumps(old), encoding="utf-8")
    loaded = settings.load_settings()
    assert loaded.profile == "a.me3" and settings.game_setting(loaded, "eldenring", "setup") == "a.me3"
    assert settings.game_setting(loaded, "nightreign", "setup") == "nr.me3"
    settings.save_settings(theme="light")
    settings.save_game_settings("eldenring", setup="b.me3")
    settings.save_game_settings("nightreign", setup="n2.me3")
    written = json.loads(settings.settings_path().read_text(encoding="utf-8"))
    assert written["setup"] == "b.me3" and "profile" not in written and written["future_key"] == [1]
    assert written["games"]["nightreign"] == {"setup": "n2.me3", "game_exe": "x.exe"}
    assert settings.load_settings().profile == "b.me3"


def test_settings_an_older_build_wrote_for_overhauls_still_load():
    """build_merges is retired: an older file with it still loads and the key is dropped on save."""
    settings.settings_path().write_text(
        json.dumps({"offline_strip_overhaul": True, "build_merges": True, "theme": "light"}), encoding="utf-8"
    )
    assert settings.load_settings().offline_strip_overhaul is True
    settings.save_settings(theme="dark")
    written = json.loads(settings.settings_path().read_text(encoding="utf-8"))
    assert written["offline_strip_overhaul"] is True and "build_merges" not in written


def test_logo_setting_migrates_old_values():
    from bayle.config.settings import LauncherSettings

    got = {v: LauncherSettings.from_raw({"logo": v}).logo for v in ("dark", "light", "gold", "ice", "bogus", None)}
    assert got == {"dark": "crimson", "light": "ice", "gold": "gold", "ice": "ice", "bogus": "auto", None: "auto"}
    assert LauncherSettings.from_raw({}).logo == "auto"
