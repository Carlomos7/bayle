# 0016 Bayle ships as a clean install under its own identity, with Tauri's installer and updater

**Status:** Direction accepted (owner, 2026-10-27), with forward recovery and no automatic rollback for the first Tauri
releases. The updater is committed only once the installer spike below passes
on Windows and Linux. If it fails, the evidence and the alternatives go back to the owner; there is no automatic switch
back to Velopack. Supersedes the updater and identity parts of [0013](0013-updater-and-repo-layout.md); 0013's
repository layout (one repository, the engine not moved) stands. [0004](0004-velopack.md) stays the record of the Qt app.

## Context

0013 kept Velopack and the `Carlomos7.RoundtableSouls` identity so existing installs would update in place. Bayle has no
established user base, so the owner dropped that priority: the Tauri app replaces the Qt one as a new architecture, and
its first release may be a clean install.

The audit behind this record found:

- **Identity:** everything shipped carries the old name: the Velopack app ID, `RoundtableSouls.exe`, the data folder
  `%LOCALAPPDATA%\RoundtableSouls`, `ROUNDTABLE_SOULS_DATA`, the instance-name prefix, the repository URLs and the feed
  signature label (`apps/engine/src/bayle/adapters/system/identity.py`). The Inno Setup takeover and the old-name stub
  exist only for installs older than Velopack.
- **Updater:** the trust and rollback rules (signed feeds, keeping the last version, the 90-second watchdog, never
  re-offering a failed version) are Bayle's own Python code in the Qt app. Velopack only installs, swaps folders and
  makes deltas. A Tauri shell would have to re-implement those rules in Rust whichever installer it used; the owner
  chose forward recovery instead (below).
- **Data folder (`adapters/system/app_paths.py`):** for the window, `data_dir()` guesses. It picks the repository when
  run from source, and a frozen build outside Velopack picks its own folder when that folder is writable, which a
  per-user Tauri install is. Otherwise it picks `%LOCALAPPDATA%\RoundtableSouls`, the Qt app's data, and may rename an
  older `Roundtable` folder into it. A Tauri app relying on that guess would keep its data in the install folder, which
  updates and uninstall replace, or would write into the Qt app's data.

## Decision

**Identity:**

| Item | Release | Development and tests |
| --- | --- | --- |
| Product name, window title | Bayle | Bayle Dev |
| Tauri identifier | `io.github.carlomos7.bayle` | `io.github.carlomos7.bayle.dev` |
| Executable | `Bayle.exe` (Windows), `bayle` (Linux) | same names, own install folder |
| Instance-name prefix | `Bayle` | `BayleDev` |
| Release assets | `Bayle_<version>_x64-setup.exe`, `Bayle_<version>_amd64.AppImage`, signed `SHA256SUMS.txt` | never published |
| First version | 6.0.0 (betas `6.0.0-beta.N`) | |

**Folders:**

- **Install:** per user, no administrator prompt. Windows: NSIS `currentUser`, expected `%LOCALAPPDATA%\Bayle` (to be
  confirmed by the spike). Linux: the AppImage file wherever the user keeps it.
- **Application state:** Tauri's `app_local_data_dir()`, the one canonical state folder: Windows
  `%LOCALAPPDATA%\<identifier>`, Linux `~/.local/share/<identifier>`. The shell passes it to the engine as `BAYLE_DATA`
  on every start. The engine's settings, logs, backups, save library, mods and caches live there, and the web view's
  own profile (`EBWebView` on Windows) sits beside them.
- **Not `app_data_dir()`:** on Windows that is the roaming profile (`%APPDATA%\<identifier>`), which domain profiles copy
  between machines. Mods and backups run to gigabytes and must not roam, so Bayle writes nothing there.
- **Override:** `BAYLE_DATA` alone. `ROUNDTABLE_SOULS_DATA` stays the Qt app's.

**The engine never guesses its data folder when the shell starts it.** `bayle --backend` requires `BAYLE_DATA` and
exits 2 before creating or moving anything when it is missing, inside the program's own folder (the install, or the
repository when run from source), or inside the Qt app's data folder (`app_paths.backend_data_dir()`). The window's
`data_dir()` rules are unchanged while the Qt app ships. Development builds use the `.dev` identifier's own state
folder; the Phase 0 development page goes further and isolates `BAYLE_DATA`, `LOCALAPPDATA`, `APPDATA` and the home
folder under a scratch folder.

**Installer and updater:** Tauri's bundler and `tauri-plugin-updater`. NSIS per user on Windows and the AppImage on
Linux; deb and rpm are not shipped, because they do not update themselves. The Python engine is the PyInstaller onedir
folder of the engine alone (no Qt, no Pillow), bundled as `bundle.resources` and started by the shell from its resource
folder.

**Update trust:**

- Every update is signed with the Tauri updater key (minisign format). The public key is in the release build's
  configuration; the private key and its password exist only as CI secrets. A signature that does not verify means
  nothing is installed.
- Development builds use their own key pair and their own manifest URLs, so a development build can never install a
  release and the reverse.
- Two manifests at fixed URLs, one per channel (Stable and Beta). They are not tied to GitHub's "latest release", so a
  Qt release published meanwhile hides nothing.
- `SHA256SUMS.txt` stays minisign-signed for people checking downloads by hand.
- Authenticode signing (SignPath, later) plugs in through `bundle.windows.signCommand`; the spike does not need it.

**Recovery is forward, not backward** (owner, 2026-10-27). There is no automatic rollback: no watchdog, no kept old
installer, no state snapshots for downgrades, no failed-version blocklist. A broken release is fixed by the next one,
and the app stays able to receive it:

1. **The updater is the shell's.** Checking, downloading, verifying and installing updates are Rust code in the shell
   and need neither the Python engine nor the React UI. A release whose engine or pages are broken can still update.
2. **Engine failure screen.** When the engine does not start, stops, or keeps stopping, the shell shows a recovery
   screen with Retry, Check for updates, Open logs and Report issue. It is served by the shell itself and works with
   the engine unavailable.
3. **UI failure fallback.** If the React UI fails to load or crashes at start, the shell shows a minimal built-in page
   with the same four actions, where Tauri makes that practical.
4. **Shell failure.** If the shell itself cannot start, the user reinstalls from the signed installer of the latest
   release; the documented repair path keeps the state folder. This is the one case the app cannot fix itself, so
   every release's installed shell is smoke-tested in CI before it is published.
5. **Before installing an update**, the shell stops the engine (stdin end of file, then the Job Object on Windows or
   the process group on Linux), so no engine process survives and no file in the install folder is locked.
6. **Downgrades:** the updater refuses a lower version from a manifest. Going back is a manual reinstall and is not
   promised to work on data a newer version migrated.
7. **Safeguards that stay:** the database backup and integrity check before every migration, refusing data newer than
   the program, `BAYLE_DATA` checks against the install, repository and Qt data folders, and the install folder never
   holding the state folder.
8. **Releases go to Beta first** and reach Stable after they have run there. A bad version that slips through is
   marked in the advisory file, which tells users to update.

Bayle does not advertise automatic rollback, atomic updates or guaranteed self-repair.

**What the Tauri app drops** (the Qt branch keeps it, [0014](0014-qt-preservation.md)): Velopack and its hooks and
watchdog scripts, the Inno Setup takeover, the old-name stubs, the `RoundtableSouls` folder and variable names, and
portable mode. The engine's code for older data layouts (`modules/mods/migrate.py`, `adapters/filesystem/data_folder.py`)
is reviewed separately before anything there goes.

**What stays:**

- signed releases and the signed checksum file;
- the release `verify` job: no older or duplicate versions;
- install, update and recovery tests in CI, rewritten for NSIS and the AppImage;
- install folder never equal to, or containing, the state folder;
- forward-only migrations, refusing newer data, a backup before migrating;
- the advisory file that marks bad versions remotely;
- isolated identities for every test build;
- Release Please with hand-pushed tags, and one product version.

## Installer spike: acceptance criteria

All on Windows and Linux unless noted, with installed and signed builds, never against real data:

1. **Package:** `tauri build` produces the NSIS installer, the AppImage, the update bundles and their signatures, with
   the engine onedir inside. Record the sizes.
2. **WebView2 (Windows):** the chosen bootstrapper mode installs WebView2 on a machine without it (Windows Sandbox),
   and the app starts there.
3. **Clean install:** no administrator prompt. Start-menu shortcut. The engine starts from the resource folder.
   `BAYLE_DATA` is `app_local_data_dir()`. Listing the install folder before and after a session shows nothing written
   there, and `%LOCALAPPDATA%\RoundtableSouls` is untouched.
4. **Update:** a signed 6.0.0-beta.1 → beta.2 through the Beta manifest. The engine is stopped first with no process
   left, the state folder is kept, and beta.2 starts with it.
5. **Trust:** a wrong signature, a tampered bundle and a manifest signed with the development key are each refused,
   with nothing installed.
6. **Broken engine, fixed forward:** a beta.3 whose engine fails at start is installed. The shell shows the recovery
   screen, and Retry, Open logs and Report issue work without the engine. Check for updates then installs a fixed
   beta.4, which starts normally with the state folder intact. No engine process is left behind at any step.
7. **Broken UI:** a build whose React UI fails to load shows the shell's fallback page with the same actions, where
   Tauri allows it; otherwise the result and the reinstall path are recorded.
8. **Data preserved:** across install, both updates and the broken release, the state folder and database survive, a
   migration that fails leaves its backup in place, and nothing is written to the install folder or the Qt data folder.
9. **Downgrade:** a manifest offering an older version installs nothing.
10. **Uninstall:** the install folder, shortcuts and uninstall entry are gone, and no process is left. The state folder
    is kept unless the user chose to delete it.
11. **Repair path:** with the shell deliberately unable to start, reinstalling from the signed installer brings the app
    back with its state folder.
12. **Linux AppImage:** it runs on the CI image and on the Steam Deck when that layer starts. The engine runs from the
    mounted image, state goes to `~/.local/share/<identifier>`, an update replaces the file, and criteria 6 and 8 hold.
13. **Channels and identities:** a Stable install never sees a Beta-only version. A `.dev` build installs beside a
    release build with separate folders, instance names and keys, and neither changes the other.

If any criterion fails, the result is reported with evidence and alternatives. Velopack is one of the alternatives, not
the default.

## Consequences

- The first Tauri release is a new install. Qt users keep the Qt app until cutover. An optional, copy-only import of a
  Qt data folder can come later; nothing moves or deletes it.
- Each update is a full download (the engine alone is about 59 MB); there are no deltas.
- A broken release stays installed until the next one; users see the recovery screen, not the previous version.
- A release whose shell cannot start needs a manual reinstall, which is why the installed shell is smoke-tested before
  every release.
- Automatic rollback can be added later, as its own decision, if real users need it.

## Reopen if

The spike fails a criterion that no reasonable change to the shell fixes, or Tauri's updater stops being maintained.
