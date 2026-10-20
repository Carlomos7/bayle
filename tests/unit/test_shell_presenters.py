"""The shell's presenters without Qt (S9 acceptance): the Launch pill's modes and four states with their reasons, every
status-text state, the profile and game drop-downs, the menu's enabled rules, the unsaved rule and the Launch mode
memory."""

from types import SimpleNamespace

from roundtable_souls.config.settings import LauncherSettings
from roundtable_souls.game import catalog
from roundtable_souls.ui.launcher import menu, topbar
from roundtable_souls.ui.launcher.topbar import Facts

ER = catalog.ELDEN_RING


def facts(**kw) -> Facts:
    return Facts(game=ER, profile_count=1, **kw)


def test_the_pill_has_four_states_with_their_reasons():
    assert topbar.pill(facts()).state == topbar.ENABLED and topbar.pill(facts()).can_launch
    assert topbar.pill(facts(busy=True, job_kind="launch")).text == "Launching..."
    assert topbar.pill(facts(busy=True, job_kind="update")).text == "Updating..."
    assert topbar.pill(facts(game_running=True)).state == topbar.RUNNING
    blocked = topbar.pill(Facts(game=ER, profile_count=0))
    assert (
        blocked.state == topbar.BLOCKED and blocked.reason == "No profile" and blocked.link.action == topbar.NEW_PROFILE
    )
    assert topbar.pill(Facts(game=ER, installed=False, profile_count=1)).link.action == topbar.LOCATIONS
    assert topbar.pill(Facts(game=catalog.SEKIRO)).reason == "Not supported yet"
    assert "unfinished" in topbar.pill(facts(problems=("unfinished setup",))).reason


def test_vanilla_needs_no_profile_and_the_modes_are_remembered_per_game():
    assert topbar.pill(Facts(game=ER, profile_count=0, mode=topbar.VANILLA)).state == topbar.ENABLED
    s = LauncherSettings(launch_mode="offline", games={"nightreign": {"launch_mode": "vanilla"}})
    assert topbar.mode_of(s, ER) == "offline" and topbar.mode_of(s, catalog.NIGHTREIGN) == "vanilla"
    assert topbar.mode_of(LauncherSettings(), ER) == "profile"
    assert [m["checked"] for m in topbar.mode_menu("offline")] == [False, True, False]


def test_every_status_text_state():
    s = topbar.status
    assert s(facts()).text == "Ready"
    busy = s(facts(busy=True, job_label="Installing X...", job_kind="other"))
    assert busy.busy and busy.text == "Installing X..."
    assert (
        s(facts(busy=True, job_label="Updating merged mods...", job_kind="update")).link.action == topbar.STOP_REBUILD
    )
    assert "running" in s(facts(game_running=True)).text
    assert s(facts(failed_job="Rebuilding...")).tone == "danger"
    assert s(facts(steam_bad=True)).link.action == topbar.OPEN_STEAM
    assert s(facts(dead_shells=2)).link.action == topbar.CLEAR_DEAD
    assert s(facts(dead_shells=2, warn_dead_shells=False)).text == "Ready"
    assert s(Facts(game=ER, profile_count=0)).link.action == topbar.NEW_PROFILE
    assert s(facts(coop_unsaved=True)).text.startswith("Unsaved co-op settings apply on launch")
    assert "1.4" in s(facts(me3_update="1.4")).text
    assert s(Facts(game=catalog.SEKIRO)).text == "Not supported yet"


def _setup(label, kind="me3", source=None):
    return SimpleNamespace(label=label, kind=kind, source=source or f"C:/p/{label}")


def test_the_profile_drop_down_lists_the_profiles_the_current_one_checked_and_new_profile_last():
    setups = [_setup("a.me3"), _setup("Revive  ·  installation.json", "manifest")]
    m = topbar.profile_menu(setups, 1, busy=False)
    assert [e.label for e in m.entries] == ["a.me3", "Revive"] and m.entries[1].managed and m.entries[1].checked
    assert m.current == "Revive" and m.new_text == "New profile..." and m.enabled
    assert not topbar.profile_menu(setups, 0, busy=True).enabled
    assert topbar.profile_menu([], -1, busy=False).current == "No profile"


def test_the_game_drop_down_has_four_games_one_checked_with_their_status():
    entries = topbar.game_menu(ER, {"eldenring": True})
    assert [e.name for e in entries] == ["Elden Ring", "Nightreign", "Dark Souls III", "Sekiro"]
    assert [e.checked for e in entries] == [True, False, False, False]
    assert [e.status for e in entries] == ["installed", "not installed", "coming soon", "coming soon"]


def _items(f):
    return {i.id: i for _k, _t, items in menu.resolve(f) for i in items if not i.separator}


def test_menu_entries_follow_their_rules_and_a_missing_command_disables_not_hides():
    commands = {"mods": frozenset({"deleteProfile", "fixOrder"}), "saves": frozenset({"backUpNow"})}
    f = menu.MenuFacts(ER, has_profile=True, commands=commands, can_launch={"profile": True})
    items = _items(f)
    assert items["profile.delete"].enabled and not items["profile.rename"].enabled  # no Rename command yet
    assert not items["profile.fix_order"].enabled  # the stays-last check passes
    assert _items(menu.MenuFacts(ER, has_profile=True, load_order_broken=True, commands=commands))[
        "profile.fix_order"
    ].enabled
    assert items["game.launch.profile"].enabled and not items["game.launch.offline"].enabled
    busy = _items(menu.MenuFacts(ER, has_profile=True, busy=True, commands=commands))
    assert not busy["profile.delete"].enabled and not busy["saves.backup"].enabled
    none = _items(menu.MenuFacts(ER, has_profile=False, commands=commands))
    assert not none["profile.delete"].enabled and none["file.exit"].enabled
    assert not _items(menu.MenuFacts(catalog.SEKIRO, commands=commands))["view.mods"].enabled
    assert "game.eldenring" in items and items["game.eldenring"].checked


def test_a_shortcut_belongs_to_one_entry_only():
    seen: dict[str, str] = {}
    for key, _t in menu.MENUS:
        for e in menu.entries_of(key):
            for found in (e, *e.submenu):
                if found.shortcut:
                    assert found.shortcut not in seen, found.shortcut
                    seen[found.shortcut] = found.id
    assert seen["Ctrl+1"] == "view.mods" and seen["Ctrl+Q"] == "file.exit"


class _Page:
    def __init__(self):
        self.dirty = True
        self.log = []

    def unsaved_words(self):
        return ["text"] if self.dirty else []

    def command(self, name, args):
        self.log.append(name)
        self.dirty = False
        return True

    def refresh(self):
        pass


def test_the_unsaved_rule_asks_before_leaving_and_discard_or_save_goes_on(tmp_path):
    from roundtable_souls.ui import self_test
    from roundtable_souls.ui.launcher.adapter import ShellAdapter
    from roundtable_souls.ui.launcher.host import ShellHost

    host = ShellHost(self_test._Context(tmp_path, "dark"))  # type: ignore[arg-type]
    shell = ShellAdapter(host)
    page = _Page()
    host.register_page("mods", page)
    host.pages["mods"] = page
    shell._adapters["mods"] = page
    asked = []
    shell.unsavedPrompt.connect(lambda token, words, action: asked.append((token, words)))
    shell.goTo("saves")
    assert asked and asked[0][1] == ["text"] and shell.currentPage == "mods"  # asked, not left
    shell.unsavedAnswer(asked[0][0], "cancel")
    assert shell.currentPage == "mods"
    shell.goTo("saves")
    shell.unsavedAnswer(asked[1][0], "discard")
    assert page.log == ["discardUnsaved"] and shell.currentPage == "saves"


def test_every_setup_problem_has_a_plain_short_form_and_a_fix_link():
    for raw in (
        r"profile missing: C:\x\a.me3",
        "this profile is for Sekiro, not Elden Ring",
        r"me3 missing: C:\x\me3.exe",
        "me3 is not installed on this PC (not on PATH, not in its default folder, not set in Settings)",
        r"game exe missing: C:\x\eldenring.exe",
        r"game exe set in Settings is missing: C:\x\eldenring.exe",
    ):
        reason = topbar.pill(facts(problems=(raw,))).reason
        assert "C:" not in reason and "Tools" not in reason and reason.startswith("Blocked: "), reason
        assert topbar.pill(facts(problems=(raw,))).link is not None
