# Contributing

## Branches

`main` is the only long-lived branch (GitHub Flow). Work on a short-lived branch from `main`, named `feat/...`,
`fix/...`, `docs/...` or `chore/...`, and open a pull request into `main`. Pull requests are squash-merged, so the
**pull request title** becomes the commit on `main` and must be in Conventional Commit form (below). Tests (lint, types,
import layers, unit and UI tests on Windows and Linux) must pass before merging.

## Commit messages: Conventional Commits

```
<type>[(scope)][!]: <description>

[body]

[BREAKING CHANGE: <what breaks>]
```

| Type       | Use for                          | In the changelog |
|------------|----------------------------------|------------------|
| `feat`     | a new feature                    | Added            |
| `fix`      | a bug fix                        | Fixed            |
| `refactor` | a change that is not a fix or a feature | Changed   |
| `perf`     | a performance improvement        | Changed          |
| `revert`   | reverts or removes earlier work  | Removed          |
| `docs`, `test`, `build`, `ci`, `chore` | no user-visible change | hidden |

The scope is optional and names the area (`mods`, `updates`, `ui`, `storage`). Add `!` after the type or scope, or a
`BREAKING CHANGE:` footer, for an incompatible change: it makes a major release. Otherwise `feat` makes a minor release
and `fix`, `refactor` and `perf` a patch. Examples:

```
feat(mods): install a mod from a 7z archive
fix(updates): keep the channel after a failed check
refactor!: drop the v1 profile format
```

A commit-msg hook checks this locally: `uv run pre-commit install --hook-type pre-commit --hook-type commit-msg`.

## Authorship

The owner identity is the only author. Do not add `Co-Authored-By` trailers or tool attribution lines to commits or pull
requests.

## Versions and releases

Versions follow [SemVer 2.0](https://semver.org): `MAJOR.MINOR.PATCH`; a pre-release such as `6.0.0-beta.1` is offered on
the Beta channel only, a plain `X.Y.Z` on both. The version lives in `apps/desktop/src-tauri/tauri.conf.json` and
`apps/desktop/src-tauri/Cargo.toml` (they must match); the engine keeps its own in `apps/engine`.

1. Commits land on `main` by squash-merged pull requests; `CHANGELOG.md` gets an entry for each release.
2. Every push to `main` that touches the app builds the signed installer and checks its signature
   (`.github/workflows/desktop-release-build.yml`, after the owner's approval). Nothing is published.
3. To release: write `apps/desktop/release-notes/<version>.md`, create the tag `v<version>` on the release commit (only
   admins may create `v*` tags), then start Desktop release build by hand with **publish**. It makes the GitHub
   release with the signed installer and its `.sig`: a pre-release for `X.Y.Z-…`, the Latest release for `X.Y.Z`.
4. Add the channel manifest on the `updates` branch (`site/updates/beta.json`; a stable release goes in both
   `stable.json` and `beta.json`), pointing at that installer with its signature. Its Pages deploy waits for the
   owner's approval.

Bayle 5 (the Qt app) is kept on `legacy/qt-desktop` and the tag `qt-final-v5.0.2` (ADR 0014); it is not released from
`main` any more.
