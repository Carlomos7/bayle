"""Golden text for me3 profiles: the text codec (formats.me3_profile) and the text surgery (mods.profile_edit)
give exactly these bytes for fixed input. Later phases move both; the text must not change."""

from bayle.formats import me3_profile
from bayle.mods import profile_edit

BASE = (
    'profileVersion = "v1"\n'
    "start_online = false\n"
    "\n"
    "[[supports]]\n"
    'game = "eldenring"\n'
    "\n"
    "[[natives]]\n"
    "path = 'natives/SeamlessCoop/ersc.dll'\n"
    "load_early = true\n"
    "\n"
    "# old armor\n"
    "# [[packages]]\n"
    '# id = "fa-pu"\n'
    "# path = 'mod/fa-pu'\n"
    "\n"
    "# the flora\n"
    "[[packages]]\n"
    'id = "flora"\n'
    "path = 'mod/flora'\n"
    "\n"
    "[[packages]]\n"
    'id = "off"\n'
    "path = 'mod/off'\n"
    "enabled = false\n"
    'load_after = [{ id = "flora", optional = true }]\n'
)
ARRAY = (
    'profileVersion = "v1"\n'
    'packages = [{ id = "flora", path = \'mod/flora\' }, { id = "off", source = \'mod/off\', enabled = false, load_after = [{ id = "flora", optional = false }] }]\n'
    "natives = [{ path = 'natives/a.dll', load_early = true, initializer = { function = \"init\" } }]\n"
)

EXPECTED_TO_BLOCKS = (
    'profileVersion = "v1"\n'
    "\n"
    "[[natives]]\n"
    "path = 'natives/a.dll'\n"
    "load_early = true\n"
    'initializer = { function = "init" }\n'
    "\n"
    "[[packages]]\n"
    'id = "flora"\n'
    "path = 'mod/flora'\n"
    "\n"
    "[[packages]]\n"
    'id = "off"\n'
    "path = 'mod/off'\n"
    "enabled = false\n"
    'load_after = [{ id = "flora", optional = false }]\n'
)

EXPECTED_TO_BLOCKS_CRLF = (
    'profileVersion = "v1"\r\n'
    "\r\n"
    "[[natives]]\r\n"
    "path = 'natives/a.dll'\r\n"
    "load_early = true\r\n"
    'initializer = { function = "init" }\r\n'
    "\r\n"
    "[[packages]]\r\n"
    'id = "flora"\r\n'
    "path = 'mod/flora'\r\n"
    "\r\n"
    "[[packages]]\r\n"
    'id = "off"\r\n'
    "path = 'mod/off'\r\n"
    "enabled = false\r\n"
    'load_after = [{ id = "flora", optional = false }]\r\n'
)

EXPECTED_OPTIONS = (
    'profileVersion = "v1"\n'
    "start_online = false\n"
    "\n"
    "[[supports]]\n"
    'game = "eldenring"\n'
    "\n"
    "[[natives]]\n"
    "path = 'natives/SeamlessCoop/ersc.dll'\n"
    "load_early = true\n"
    "\n"
    "# old armor\n"
    "# [[packages]]\n"
    '# id = "fa-pu"\n'
    "# path = 'mod/fa-pu'\n"
    "\n"
    "# the flora\n"
    "[[packages]]\n"
    'id = "flora"\n'
    "path = 'mod/flora'\n"
    "enabled = false\n"
    'load_before = [{ id = "x", optional = true }]\n'
    "\n"
    "[[packages]]\n"
    'id = "off"\n'
    "path = 'mod/off'\n"
    "enabled = false\n"
    'load_after = [{ id = "flora", optional = true }]\n'
)

EXPECTED_NATIVE_OPTIONS = (
    'profileVersion = "v1"\n'
    "start_online = false\n"
    "\n"
    "[[supports]]\n"
    'game = "eldenring"\n'
    "\n"
    "[[natives]]\n"
    "path = 'natives/SeamlessCoop/ersc.dll'\n"
    "optional = true\n"
    "\n"
    "# old armor\n"
    "# [[packages]]\n"
    '# id = "fa-pu"\n'
    "# path = 'mod/fa-pu'\n"
    "\n"
    "# the flora\n"
    "[[packages]]\n"
    'id = "flora"\n'
    "path = 'mod/flora'\n"
    "\n"
    "[[packages]]\n"
    'id = "off"\n'
    "path = 'mod/off'\n"
    "enabled = false\n"
    'load_after = [{ id = "flora", optional = true }]\n'
)

EXPECTED_PATH = (
    'profileVersion = "v1"\n'
    "start_online = false\n"
    "\n"
    "[[supports]]\n"
    'game = "eldenring"\n'
    "\n"
    "[[natives]]\n"
    "path = 'natives/SeamlessCoop/ersc.dll'\n"
    "load_early = true\n"
    "\n"
    "# old armor\n"
    "# [[packages]]\n"
    '# id = "fa-pu"\n'
    "# path = 'mod/fa-pu'\n"
    "\n"
    "# the flora\n"
    "[[packages]]\n"
    'id = "flora"\n'
    "path = 'mod/flora'\n"
    "\n"
    "[[packages]]\n"
    'id = "off"\n'
    "path = 'mod/flora2'\n"
    "enabled = false\n"
    'load_after = [{ id = "flora", optional = true }]\n'
)

EXPECTED_REMOVED = (
    'profileVersion = "v1"\n'
    "start_online = false\n"
    "\n"
    "[[supports]]\n"
    'game = "eldenring"\n'
    "\n"
    "[[natives]]\n"
    "path = 'natives/SeamlessCoop/ersc.dll'\n"
    "load_early = true\n"
    "\n"
    "# old armor\n"
    "# [[packages]]\n"
    '# id = "fa-pu"\n'
    "# path = 'mod/fa-pu'\n"
    "\n"
    "[[packages]]\n"
    'id = "off"\n'
    "path = 'mod/off'\n"
    "enabled = false\n"
    'load_after = [{ id = "flora", optional = true }]\n'
)

EXPECTED_CHUNK = "# the flora\n[[packages]]\nid = \"flora\"\npath = 'mod/flora'\n"

EXPECTED_INSERT = (
    'profileVersion = "v1"\n'
    "start_online = false\n"
    "\n"
    "[[supports]]\n"
    'game = "eldenring"\n'
    "\n"
    "[[natives]]\n"
    "path = 'natives/SeamlessCoop/ersc.dll'\n"
    "load_early = true\n"
    "\n"
    "# old armor\n"
    "# [[packages]]\n"
    '# id = "fa-pu"\n'
    "# path = 'mod/fa-pu'\n"
    "\n"
    "[[packages]]\n"
    'id = "new"\n'
    "path = 'mod/new'\n"
    'load_after = [{ id = "flora", optional = true }]\n'
    "\n"
    "# the flora\n"
    "[[packages]]\n"
    'id = "flora"\n'
    "path = 'mod/flora'\n"
    "\n"
    "[[packages]]\n"
    'id = "off"\n'
    "path = 'mod/off'\n"
    "enabled = false\n"
    'load_after = [{ id = "flora", optional = true }]\n'
)

EXPECTED_APPEND_CRLF = (
    'profileVersion = "v1"\r\n'
    "start_online = false\r\n"
    "\r\n"
    "[[supports]]\r\n"
    'game = "eldenring"\r\n'
    "\r\n"
    "[[natives]]\r\n"
    "path = 'natives/SeamlessCoop/ersc.dll'\r\n"
    "load_early = true\r\n"
    "\r\n"
    "# old armor\r\n"
    "# [[packages]]\r\n"
    '# id = "fa-pu"\r\n'
    "# path = 'mod/fa-pu'\r\n"
    "\r\n"
    "# the flora\r\n"
    "[[packages]]\r\n"
    'id = "flora"\r\n'
    "path = 'mod/flora'\r\n"
    "\r\n"
    "[[packages]]\r\n"
    'id = "off"\r\n'
    "path = 'mod/off'\r\n"
    "enabled = false\r\n"
    'load_after = [{ id = "flora", optional = true }]\r\n'
    "\r\n"
    "[[natives]]\r\n"
    "path = 'natives/x.dll'\r\n"
    "optional = true\r\n"
    "initializer = { delay = { ms = 500 } }\r\n"
)


def test_the_inline_array_shape_is_rewritten_as_blocks_and_stays_so():
    assert me3_profile.to_blocks(ARRAY) == EXPECTED_TO_BLOCKS
    assert me3_profile.to_blocks(EXPECTED_TO_BLOCKS) == EXPECTED_TO_BLOCKS  # parse -> write is stable
    assert me3_profile.to_blocks(ARRAY.replace("\n", "\r\n")) == EXPECTED_TO_BLOCKS_CRLF


def test_the_block_shape_is_read_back_entry_by_entry():
    found = me3_profile.entries(BASE)
    assert [(e["index"], e["kind"], e["name"], e["path"], e["enabled"]) for e in found] == [
        (0, "native", "ersc.dll", "natives/SeamlessCoop/ersc.dll", True),
        (1, "package", "flora", "mod/flora", True),
        (2, "package", "off", "mod/off", False),
    ]


def test_option_and_path_edits_change_only_their_block():
    assert profile_edit.set_block_options(BASE, 1, {"enabled": False, "load_before": ["x"]}) == EXPECTED_OPTIONS
    assert profile_edit.set_block_options(BASE, 0, {"optional": True, "load_early": False}) == EXPECTED_NATIVE_OPTIONS
    assert profile_edit.set_block_path(BASE, 2, "mod/flora2") == EXPECTED_PATH


def test_removing_an_entry_takes_its_note_and_restoring_gives_the_original_back():
    text, chunk, where = profile_edit.remove_entry(BASE, 1)
    assert text == EXPECTED_REMOVED and chunk == EXPECTED_CHUNK
    assert profile_edit.restore_entry(text, chunk, where) == BASE


def test_inserting_goes_above_the_note_and_appending_keeps_crlf():
    row = {"id": "new", "path": "mod/new", "load_after": ["flora"]}
    assert profile_edit.insert_entry(BASE, "package", row, 1) == EXPECTED_INSERT
    native = {"path": "natives/x.dll", "optional": True, "initializer": {"delay": {"ms": 500}}}
    assert profile_edit.append_entry(BASE.replace("\n", "\r\n"), "native", native) == EXPECTED_APPEND_CRLF
