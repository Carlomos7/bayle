# 0010 The backend is separate from Qt; the session is the one seam

**Status:** Accepted (owner, 2026-10-21). The user interface that sits on top of it is not decided here.

## Context

Nothing below `ui/` imports Qt today, and an import-linter contract keeps it that way. But the backend is not yet usable
without Qt, for shape reasons:

- PySide6 is a hard dependency of the whole package.
- The only job runner that has ids, results and cancel is Qt-bound.
- Each page's logic lives in closures inside Qt adapters (about 5,500 lines), not in functions that can be called by
  name.
- Confirmations are in-process callbacks, and errors travel as `SystemExit`.

A second front end (a web UI in a Tauri window, tests, scripts) cannot reuse any of that.

## Decision

The Python package (`src/bayle/`, renamed from `roundtable_souls`) is split into layers, top to bottom:

```
cli > app > ui | api > session > views > services > (mods|saves|coop|updates) > ... > platform
```

- **`session`** is the one seam. A small interface: take a snapshot of a page, run an operation, answer a plan, cancel
  a job, subscribe to events. It holds the job manager, event bus, plan store and the registered operations.
- **`views`** is the read side: presenters and frozen view-model dataclasses, wording included, no file or network I/O.
  `session` may import `views`, never the reverse.
- **`ui`** (Qt) and **`api`** (HTTP) are sibling adapters over `session`. Neither may import the other. When Qt is
  removed, `ui` and its contract line go.
- **Operations** are typed functions with typed parameters and results. Each is a query (returns data), a job (returns
  a job id) or a plan (returns what would happen and asks first). The decorator supplies what every adapter used to
  re-implement: the log wrapper, error mapping, the one-writer and game-running gate, and the undo record.
- **Jobs** have an id, structured progress (rate-limited to about 10 per second), a result or typed error, and
  cooperative cancel. Terminal events are never dropped. `SystemExit` stops being an error protocol.
- **Risky actions use plan/execute.** The first call returns a plan token and the text to confirm; a second call with
  the token and the answers runs it. Only the Launch flow, which asks several questions while running, uses prompt events.
- **No Qt anywhere except `ui`.** The "no Qt below the UI" contract is widened to `session`, `views`, `api`, `cli`
  and `app`. PySide6 becomes an optional extra, so a headless install works.
- One implementation, two adapters. Qt pages are re-pointed at operations, not forked; every operation is tested
  through `Session.run`, not through Qt.

## Why

The seam has two real adapters from the start (Qt now, HTTP next), so it is not speculative. The same refactor is useful
if the front end changes again, which is why it is committed independently of that choice. Keeping the Qt app shippable
after every step removes the need for a big-bang rewrite.

## Consequences

- Several months of work moving page logic out of adapters; the Mods page is the largest and goes last.
- New features go into `session` and `views` first, so Qt and any later UI cannot drift apart.
- The backend sends final, translated strings in the first version; message ids can come later.
- Tests of flows move off the fake-host helpers to the session seam.
- The coverage exclusion for `ui/` stays; `api`, `session` and `views` are measured.

## Alternatives considered

- **Leave the logic in the Qt adapters and put HTTP over them.** Rejected: nothing is callable by name, and the
  callbacks cannot wait on an HTTP request.
- **A separate repository or distribution for the backend.** Rejected for now: it churns release paths, build specs and
  every worktree for no gain while Qt still ships from the same package.
- **Duplicate view models as Pydantic mirrors.** Rejected: the presenters' dataclasses are validated by the API library
  directly, so one set of types serves both adapters.

## Reopen if

A page cannot be made JSON-clean without a second copy of its view, or the first migrated page (Activity) costs more
than twice its estimate; then the operation decorator is redesigned before the next page.
