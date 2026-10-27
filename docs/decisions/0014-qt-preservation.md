# 0014 The Qt app is kept on `legacy/qt-desktop` and a `qt-final-v*` tag before it leaves `main`

**Status:** Proposed. Phase 0 of the Tauri migration; nothing is preserved or removed yet.

## Context

The desktop app moves from PySide6/Qt (`apps/qt-desktop`) to Tauri 2 + React with the Python engine behind a Rust
gateway ([0011](0011-transport.md), [0012](0012-process-lifecycle.md), [0013](0013-updater-and-repo-layout.md)). Qt stays
the shipping app until the Tauri one is accepted. After that, Qt leaves `main`, but its last working state must stay
buildable from Git: no second repository and no copied directory.

Audit of `main` at `b345d3e6` (release 5.0.1, 2026-10-27):

- **Qt app:** `apps/qt-desktop` (package `bayle_qt`, version 5.0.1), its own uv project and `uv.lock`, Python 3.14.7
  (`.python-version`), `PySide6>=6.11.2`, `velopack==1.2.161`, engine as an editable path dependency (`../engine`).
- **Build:** `uv run python scripts/build.py` runs the tests, PyInstaller (onedir, `scripts/entry.py`,
  `scripts/pyinstaller_hooks/`), `vpk pack` and the share bundle (`scripts/make_share.py`). `--no-pack` builds PyInstaller
  only. Windows packs win-x64 (Setup.exe, portable zip, packages); Linux builds an AppImage.
- **Release:** `release.yml` runs on any `v*` tag. Its `verify` job refuses a tag that is not newer than the latest stable
  release. The `windows` and `linux` jobs build with vpk 1.2.161 (dotnet 10); on Windows they also test install and
  update from the previous release. `publish` signs the feeds with minisign (`MINISIGN_KEY` secret) and uploads 13 assets to the GitHub
  release. Feeds are channels `win` and `linux` on GitHub releases ([0003](0003-signed-releases.md),
  [0004](0004-velopack.md)).
- **Tagging:** the "Release tags" ruleset covers `refs/tags/v*` and blocks Release Please, so release tags are pushed by
  hand.
- **CI:** `test.yml` runs only for pushes and pull requests on `main`; `release-please.yml` only on `main`; Dependabot only
  on the default branch.
- **Repository:** default `main`, squash-only, `delete_branch_on_merge`, `main` protected (strict, `tests-passed`). No
  rules exist for `legacy/*` branches or non-`v*` tags.

## Decision

**Two references, made from the same commit:**

- `legacy/qt-desktop`: a branch with the final verified Qt state, kept for history and deliberate maintenance.
- `qt-final-vX.Y.Z`: an annotated tag on that commit, where `vX.Y.Z` is the last Qt release (for example
  `qt-final-v5.3.0`). It never moves. It does not match `v*`, so it never starts `release.yml`.

**When:** not before the Tauri app meets the cutover criteria below. Until then Qt keeps shipping from `main`, and every Qt
fix lands on `main` as usual, so the final references capture those fixes. No temporary reference is needed now: each
released `v*` tag already marks a verified Qt state.

**Which commit:** the last commit on `main` that was released as a `v*` tag whose release run went green (verify, windows,
linux, publish). If Qt-only changes landed after that tag, either release them first or preserve the tagged commit.
Never preserve an untagged commit.

**What the commit must contain** (all already in `main` today; check each at preservation time):

| Item | Where |
| --- | --- |
| Qt source, QML, assets, fonts, icons | `apps/qt-desktop/src/` |
| Qt project, lockfile, Python version | `apps/qt-desktop/pyproject.toml`, `uv.lock`, `.python-version` |
| The engine version it was built and tested with | `apps/engine/` and its `uv.lock` |
| Qt tests | `apps/qt-desktop/tests/` |
| Packaging | `scripts/build.py`, `entry.py`, `pyinstaller_hooks/`, `make_share.py`, `scripts/ci/` |
| Release and update | `.github/workflows/release.yml`, `release-please.yml`, `test.yml`; updater in `bayle_qt/updater/` |
| Decisions and architecture | `docs/decisions/`, `docs/architecture.md` |
| Licences | `LICENSE`, `apps/qt-desktop/THIRD_PARTY_NOTICES.md` |

External inputs the commit does not contain: the `MINISIGN_KEY` secret, vpk 1.2.161 from NuGet, dotnet 10, GitHub's
`windows-latest` and `ubuntu-22.04` runners, and the published GitHub releases that vpk diffs against. Installers and
packages stay as GitHub release assets with their signed `SHA256SUMS`; none are committed to Git. Old releases are never
deleted, because updates and deltas download from them.

**Procedure** (each step needs the owner's go-ahead):

1. Check the clone: branch, `HEAD`, clean tree, `origin` points at `Carlomos7/bayle`.
2. Pick the commit (above). Record its SHA, the `v*` tag, and that release run's id.
3. Check that neither reference exists: `git ls-remote origin refs/heads/legacy/qt-desktop 'refs/tags/qt-final-*'`.
   If one does, stop.
4. In a clean worktree at that commit: `uv sync --locked` and `uv run pytest` in both `apps/engine` and
   `apps/qt-desktop`, then `uv run python scripts/build.py --no-pack` and the headless smoke test.
5. `git tag -a qt-final-vX.Y.Z <sha> -m "Final Qt desktop: vX.Y.Z"` and `git branch legacy/qt-desktop <sha>`.
6. Push each by its own name (never `--force`, never `--tags`), then confirm with `git ls-remote` that both resolve to
   `<sha>`.
7. Add the rules below, then record the SHA, tag, release and run id in this file and in `CHANGELOG.md`.
8. Only then open the pull request that removes Qt from `main`.

**Repository rules to add at preservation** (owner, admin settings):

- Extend the tag ruleset (or add one) to `refs/tags/qt-final-*`: no update, no deletion.
- Add a branch ruleset for `refs/heads/legacy/*`: no deletion, no force push, changes only through pull requests.

**Maintaining the branch afterwards:**

- Never merge Tauri-era `main` into it, and never open a pull request from it into `main`.
- A fix goes in as a pull request into `legacy/qt-desktop`. The first commit on the branch adds `legacy/**` to the branch
  filters in its own `test.yml`; the tag stays on the verified commit before that.
- No releases come from the branch by default. Once Tauri releases ship, `release.yml`'s `verify` job refuses an older
  version anyway, and a Qt build published to the `win` or `linux` channel would reach Tauri users. A Qt hotfix release
  needs its own channel and a separate decision.

**Cutover criteria** (all must hold before the removal pull request):

1. The Tauri app covers every Qt feature, or each gap is accepted in writing.
2. The installer route (decision 6) is chosen and tested: clean install, update from an installed Qt release, a failed
   update that recovers, and clean uninstall, on Windows and Linux.
3. User data carries over: the same data folder, migrations forward-only, and the "newer data than this program" guard
   lets an older build refuse safely.
4. At least one Tauri release has shipped to Beta with no data-loss or update reports.
5. `legacy/qt-desktop` and `qt-final-vX.Y.Z` exist, are protected, and point at a commit whose tests and build pass.

**The removal pull request:** deletes `apps/qt-desktop/` and its jobs, steps and scripts in the workflows; Qt-only
dependencies; Dependabot entries; Qt-specific notices; and updates `docs/architecture.md`, `README.md` and
`CONTRIBUTING.md`. It keeps `apps/engine/` whole, including features only Qt used so far.

## Consequences

- The Qt app stays buildable from one tag, with no second copy of the code.
- Preserving Qt in Git does not make downgrades safe. Going back from Tauri to Qt is only as safe as the data guard in
  [0013](0013-updater-and-repo-layout.md) makes it, and is tested as part of decision 6.
- A legacy build needs external inputs that can change: runner images, dotnet, NuGet's vpk 1.2.161 and the signing secret.
  The further from the freeze, the more a rebuild may need small workflow fixes on the branch.
- The update feed and advisory URLs in `bayle/adapters/system/identity.py` still name `Carlomos7/roundtable-souls` and
  work through GitHub's redirect after the rename to `bayle`. A new repository with the old name would break that
  redirect for installed apps, Qt and Tauri alike.
