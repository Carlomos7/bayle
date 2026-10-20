"""The QML pages, registered once: each entry names its QML file and how its adapter is made. A window (the S5 page
window today, the QML shell from S9) and the self-test build every page from this list, so a page added here is
covered by both without editing either."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from roundtable_souls.ui.notifications import Notifier


@dataclass(frozen=True)
class QmlPage:
    name: str
    qml: str  # relative to ui/qml
    make_adapter: Callable[[Any, Notifier], Any]  # (host, notifier) -> the page's adapter
    commands: tuple[str, ...] = ()  # what the shell's menu may ask of its adapter (adapter.command(name, args))


def _activity(host, notifier: Notifier):
    from roundtable_souls.ui.pages.activity.adapter import ActivityAdapter

    return ActivityAdapter(host, notifier)


def _mods(host, notifier: Notifier):
    from roundtable_souls.ui.pages.mods.adapter import ModsAdapter

    return ModsAdapter(host, notifier)


def _mod_configs(host, notifier: Notifier):
    from roundtable_souls.ui.pages.mod_configs.adapter import ModConfigsAdapter

    return ModConfigsAdapter(host, notifier)


def _profile_transfer(host, notifier: Notifier):
    from roundtable_souls.ui.pages.profile_transfer.adapter import ProfileTransferAdapter

    return ProfileTransferAdapter(host, notifier)


def _saves(host, notifier: Notifier):
    from roundtable_souls.ui.pages.saves.adapter import SavesAdapter

    return SavesAdapter(host, notifier)


def _settings(host, notifier: Notifier):
    from roundtable_souls.ui.pages.settings.adapter import SettingsAdapter

    return SettingsAdapter(host, notifier)


QML_PAGES: tuple[QmlPage, ...] = (
    QmlPage("activity", "Pages/ActivityPage.qml", _activity),
    QmlPage("mods", "Pages/ModsPage.qml", _mods),
    QmlPage("modConfigs", "Pages/ModConfigsPage.qml", _mod_configs),
    QmlPage("profileTransfer", "Pages/ProfileTransferPage.qml", _profile_transfer),
    QmlPage("saves", "Pages/SavesPage.qml", _saves),
    QmlPage("settings", "Pages/SettingsPage.qml", _settings),
)


def page(name: str) -> QmlPage:
    return next(p for p in QML_PAGES if p.name == name)
