"""Bayle Dev's guard: copied settings or undo records that name the player's real folders reach nothing there. An audit
hook stays for the life of its process, so each check runs in a child Python."""

import json
import os
import subprocess
import sys
import textwrap

SCRIPT = textwrap.dedent(
    """
    import json, os, shutil, sys
    from pathlib import Path
    from bayle.adapters.system import sandbox

    real, data, other, extra = (Path(p) for p in sys.argv[1:5])
    os.environ[sandbox.PROTECT_ENV] = str(real)
    os.environ[sandbox.ALLOW_ENV] = str(extra)
    assert sandbox.guard_from_env(data, data / "program")

    def tried(f):
        try:
            f()
            return "ok"
        except sandbox.SandboxRefused:
            return "refused"

    print(json.dumps({
        "read real": tried(lambda: (real / "RoundtableSouls" / "launcher_settings.json").read_text()),
        "list real": tried(lambda: os.listdir(real / "RoundtableSouls")),
        "long form": tried(lambda: open("\\\\\\\\?\\\\" + str(real / "RoundtableSouls" / "launcher_settings.json")).read()),
        "delete real": tried(lambda: (real / "RoundtableSouls" / "launcher_settings.json").unlink()),
        "move out of real": tried(lambda: os.rename(real / "RoundtableSouls" / "launcher_settings.json", data / "x")),
        "write data": tried(lambda: (data / "settings.json").write_text("{}")),
        "read other": tried(lambda: (other / "mod.zip").read_bytes()),
        "write other": tried(lambda: (other / "new.txt").write_text("x")),
        "copy into other": tried(lambda: shutil.copyfile(data / "settings.json", other / "copy.json")),
        "write allowed": tried(lambda: (extra / "moved.txt").write_text("x")),
    }))
    """
)


def test_bayle_dev_reaches_nothing_in_the_real_folders_and_writes_only_where_allowed(tmp_path):
    real, data, other, extra = (tmp_path / n for n in ("real", "data", "other", "extra"))
    (real / "RoundtableSouls").mkdir(parents=True)
    (real / "RoundtableSouls" / "launcher_settings.json").write_text("{}")
    for d in (data, other, extra):
        d.mkdir()
    (other / "mod.zip").write_bytes(b"zip")
    # the temp folder is always allowed: give the child its own, apart from the folders under test
    (tmp_path / "tmp").mkdir()
    env = {**os.environ, **{k: str(tmp_path / "tmp") for k in ("TMPDIR", "TEMP", "TMP")}}
    out = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(real), str(data), str(other), str(extra)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == {
        "read real": "refused",
        "list real": "refused",
        "long form": "refused",
        "delete real": "refused",
        "move out of real": "refused",
        "write data": "ok",
        "read other": "ok",  # a mod archive picked anywhere else is read as usual
        "write other": "refused",
        "copy into other": "refused",
        "write allowed": "ok",
    }
    assert (real / "RoundtableSouls" / "launcher_settings.json").exists()
    assert not (other / "new.txt").exists() and not (other / "copy.json").exists()


def test_no_guard_without_the_shell_asking(monkeypatch):
    from bayle.adapters.system import sandbox

    monkeypatch.delenv(sandbox.PROTECT_ENV, raising=False)
    assert sandbox.guard_from_env(sandbox.Path("."), sandbox.Path(".")) is False
