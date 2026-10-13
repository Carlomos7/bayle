"""The facts behind two of the Mods page's tags (technical specification §8.10, tag vocabulary): "Loads nothing" (an
entry pointing at the profile's own folder or at a folder that only holds other mods) and "Outside the library" (an
entry of a library profile whose folder lies outside rs-<game>/)."""

from roundtable_souls.mods import checks
from roundtable_souls.services.mods import profile_entries


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_an_entry_for_a_folder_of_mods_or_the_profile_folder_loads_nothing(tmp_path):
    p = tmp_path / "my.me3"
    write(
        p,
        'profileVersion = "v1"\n\n'
        "[[packages]]\nid = \"all\"\npath = 'mod'\n\n"
        "[[packages]]\nid = \"here\"\npath = '.'\n\n"
        "[[packages]]\nid = \"flora\"\npath = 'mod/flora'\n",
    )
    (tmp_path / "mod" / "flora" / "parts").mkdir(parents=True)
    (tmp_path / "mod" / "flora" / "parts" / "a.partsbnd.dcx").write_bytes(b"a")
    items = profile_entries(p)
    names = {e["index"]: e["name"] for e in items}
    assert {names[i] for i in checks.loads_nothing(p, items)} == {"all", "here"}


def test_outside_the_library_only_for_a_profile_kept_in_the_library(tmp_path):
    library = tmp_path / "rs-eldenring"
    p = library / "profiles" / "main.me3"
    outside = tmp_path / "Downloads" / "flora"
    outside.mkdir(parents=True)
    write(
        p,
        'profileVersion = "v1"\n\n'
        "[[packages]]\nid = \"inside\"\npath = '../packages/inside'\n\n"
        f"[[packages]]\nid = \"flora\"\npath = '{outside.as_posix()}'\n",
    )
    (library / "packages" / "inside").mkdir(parents=True)
    items = profile_entries(p)
    flagged = {e["name"] for e in items if e["index"] in checks.outside_library(p, items, library)}
    assert flagged == {"flora"}
    assert checks.outside_library(p, items, None) == []
    old = tmp_path / "eldenring-mods" / "old.me3"  # an existing setup, not in the library: no tag at all
    write(old, f'profileVersion = "v1"\n\n[[packages]]\nid = "flora"\npath = \'{outside.as_posix()}\'\n')
    assert checks.outside_library(old, profile_entries(old), library) == []
