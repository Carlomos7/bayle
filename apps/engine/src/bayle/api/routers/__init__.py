"""The feature routers, one per engine feature interface (runtime.features); api.app mounts every one under /v1."""

from fastapi import APIRouter

from bayle.api.routers import (
    activity,
    builds,
    games,
    launch,
    mod_configs,
    mod_install,
    mod_library,
    mods,
    profile_transfer,
    saves,
    settings,
)

ALL: list[APIRouter] = [
    m.router
    for m in (
        activity,
        settings,
        saves,
        profile_transfer,
        mod_configs,
        mods,
        builds,
        mod_install,
        mod_library,
        games,
        launch,
    )
]
