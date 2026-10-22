# 0013 Velopack stays the updater; the desktop app and the API package live in this repository

**Status:** Proposed. Depends on a packaging spike; the owner has not yet decided the updater.

## Context

If a Tauri app replaces the Qt one, the install must keep updating in place for people who already have Bayle, keep the
signed feeds and the startup rollback of [0003](0003-signed-releases.md) and [0004](0004-velopack.md), and keep one
product version. The shipped identity (Velopack app id `Carlomos7.RoundtableSouls`, the exe name, the data folder and the
repository name) stays for now, so an update replaces the program and leaves the data alone. Tauri's own bundler expects
a single sidecar file, while the backend is a onedir folder.

## Decision

- **Updater:** keep Velopack. Build the shell with `tauri build --no-bundle`, put the exe and the backend folder side by
  side, and run `vpk pack`. Tauri's bundler and updater are not used. The Rust shell calls Velopack's startup hook first
  in `main`; the backend does not.
- **Trust and rollback:** the signed feed, the package checks and the 90-second start watchdog of 0003 and 0004 carry
  over unchanged in rules; only the process that reports "ready" changes (the shell, once its window is up and the
  backend answers `/v1/health`).
- **Data:** the Tauri app uses the existing data folder and `ROUNDTABLE_SOULS_DATA`, never its own app-data directory.
  Database migrations stay forward-only, and a "newer data than this program" guard lets a rollback to Qt refuse safely.
- **Layout:** one repository, a strangler migration, Python not moved.

  ```
  src/bayle/            backend (and ui/ until the cutover)
  apps/desktop/         Vite + React + Tauri (src-tauri/ inside)
  packages/api/         committed openapi.json + generated TypeScript client
  pnpm-workspace.yaml   apps/*, packages/*
  ```

- **Versioning:** one release-please package at the root. `extra-files` bump `package.json`, `Cargo.toml`, `Cargo.lock`
  and `tauri.conf.json`; a check in the release workflow fails if the fields disagree. Tags stay `vX.Y.Z`; the release
  workflow stays the publisher.
- **CI:** web and Rust jobs run only when their paths change; the single required check keeps its name. A preview job
  builds and installs the desktop app on a test identity but does not publish.
- **Cutover:** the Qt app keeps shipping from `main` during the migration. The Tauri build ships first as a beta
  release candidate (for example `5.0.0-rc.1`) on the same app id, then as the stable release. No parallel installs.

## Why

Keeping Velopack keeps every installed user on an in-place update path and keeps the trust code that was written and
tested. Tauri's updater would mean a mandatory new signing key whose loss strands users, a one-time bridge release for
existing installs, and an open bug reinstalling a PyInstaller sidecar. One repository, with a lock file each for Python
and JavaScript, avoids releasing the API and the app out of step.

## Consequences

- Velopack with a Tauri exe is untested territory; its documentation never mentions Tauri. A throwaway-identity spike
  (install, update, rollback, uninstall) comes first, and never on the owner's own PC.
- On Linux the AppImage depends on the system WebKitGTK 4.1, unlike Tauri's own bundled AppImage; needs a Steam Deck check.
- Code signing and the Defender false positive of an unsigned Rust exe plus a Python folder are still open.
- Contributors need Node, pnpm and Rust in addition to uv.

## Alternatives considered

- **Tauri updater with `externalBin`:** less glue, but the key, bridge and reinstall problems above.
- **A uv workspace or moving Python to `packages/engine` now:** churns paths and specs with no gain until Qt is gone.
- **Separate repositories or linked versions per component:** needed only if the parts release independently.

## Evidence

https://docs.velopack.io/getting-started/rust , https://v2.tauri.app/reference/cli/ (`--no-bundle`),
https://v2.tauri.app/develop/sidecar/ , https://v2.tauri.app/plugin/updater/ , https://v2.tauri.app/distribute/appimage/ ,
https://github.com/tauri-apps/tauri/issues/15134 , release-please `extra-files` documentation
(googleapis/release-please, docs/customizing.md). The `Cargo.lock` filter for release-please is not yet verified.

## Reopen if

The packaging spike fails, Velopack gains no path for a Tauri exe, or the owner chooses another updater.
