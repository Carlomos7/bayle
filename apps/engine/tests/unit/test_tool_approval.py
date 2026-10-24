"""A rebuild tool's permission is kept once per tool version (technical specification §8.10, Parameters card): the
key includes the program file's fingerprint, so a changed program is asked about again; a permission kept under the
older key (no fingerprint) counts once and moves to the new key."""

from pathlib import Path

from bayle.config.settings import load_settings, save_settings
from bayle.mods import rebuild
from bayle.mods.backends import Recipe, Tool, program_fingerprint


def tool(tmp_path: Path, program: str = "refresh.exe") -> Tool:
    recipe = Recipe(
        label="refresh",
        package={"name": "Overhaul"},
        profile=tmp_path / "p.me3",
        command=[program, "--refresh"],
        cwd=tmp_path,
        sources_file=tmp_path / "installation.json",
        approval=f"{tmp_path}|refresh",
    )
    return Tool(recipe)


def test_a_new_version_of_the_program_is_asked_about_again(tmp_path):
    exe = tmp_path / "refresh.exe"
    exe.write_bytes(b"version 1")
    t = tool(tmp_path)
    assert not rebuild.approved(t)
    rebuild.approve(t)
    assert rebuild.approved(t)
    exe.write_bytes(b"version 2, a little longer")  # an update replaces the program
    assert not rebuild.approved(tool(tmp_path))


def test_a_permission_kept_under_the_older_key_counts_once_and_moves(tmp_path):
    exe = tmp_path / "refresh.exe"
    exe.write_bytes(b"version 1")
    t = tool(tmp_path)
    save_settings(rebuild_approved=[t.legacy_approval_key()])
    assert rebuild.approved(t)
    assert load_settings().rebuild_approved == [t.approval_key()]  # moved: the old key is gone
    exe.write_bytes(b"version 2, a little longer")
    assert not rebuild.approved(tool(tmp_path))  # and the next version asks


def test_a_changed_script_is_asked_about_again_though_the_interpreter_is_the_same(tmp_path):
    script = tmp_path / "tool.py"
    script.write_text("print('version 1')\n", encoding="utf-8")

    def scripted() -> Tool:
        t = tool(tmp_path, program="python")
        t.recipe.command = ["python", "tool.py", "--refresh"]
        return t

    rebuild.approve(scripted())
    assert rebuild.approved(scripted())
    script.write_text("print('version 2, which does something else')\n", encoding="utf-8")
    assert not rebuild.approved(scripted())


def test_the_data_a_tool_is_given_does_not_count_as_the_tool(tmp_path):
    (tmp_path / "tool.py").write_text("print('v1')\n", encoding="utf-8")
    data = tmp_path / "p.me3"
    data.write_text("profileVersion = 'v1'\n", encoding="utf-8")

    def scripted() -> Tool:
        t = tool(tmp_path, program="python")
        t.recipe.command = ["python", "tool.py", str(data)]
        return t

    rebuild.approve(scripted())
    data.write_text("profileVersion = 'v1'\n# every rebuild writes the profile\n", encoding="utf-8")
    assert rebuild.approved(scripted())


def test_a_program_that_is_not_a_file_has_no_fingerprint(tmp_path):
    assert program_fingerprint("python", tmp_path) == ""
    assert program_fingerprint("", tmp_path) == ""
    (tmp_path / "tool.exe").write_bytes(b"x")
    assert len(program_fingerprint("tool.exe", tmp_path)) == 64
    assert program_fingerprint(str(tmp_path / "tool.exe")) == program_fingerprint("tool.exe", tmp_path)
