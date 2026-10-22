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

Versions follow [SemVer 2.0](https://semver.org): `MAJOR.MINOR.PATCH`; a pre-release is `X.Y.Z-rc.N` (older versions
used `-beta.N`, which the launcher still reads). A pre-release is offered on the Beta channel only; a plain `X.Y.Z` on
both. Never edit the version or `CHANGELOG.md` by hand: [release-please](https://github.com/googleapis/release-please)
does it.

1. Commits land on `main` by squash-merged pull requests.
2. Each push to `main` opens or updates the **release pull request**: the next version (from the commit types), the
   `CHANGELOG.md` entry, `pyproject.toml`, `src/bayle/__init__.py` and `uv.lock`.
3. Merging that pull request makes release-please tag `vX.Y.Z` and create a draft GitHub release holding the
   changelog entry. The same workflow then starts `release.yml` on the tag (a tag made by `GITHUB_TOKEN` does not
   trigger workflows by itself, so it is dispatched explicitly).
4. `release.yml` checks the tag is on `main` and matches the version, builds Windows and Linux, signs the feeds,
   uploads into the draft, verifies it, and publishes (a pre-release for `-rc.N`, the latest release for `X.Y.Z`).

**A release candidate:** merge a commit with a `Release-As` footer, for example an empty one from a branch:

```
git commit --allow-empty -m "chore: release 4.1.0-rc.1" -m "Release-As: 4.1.0-rc.1"
```

The release pull request then proposes `4.1.0-rc.1`. After testing it, merge another `Release-As: 4.1.0` commit for the
stable release. `scripts/bump_version.py` remains as a manual fallback.
