# Decision records

Why some of the launcher's behaviour (file formats, releases) is the way it is: what was decided, what it rests on, and what
would reopen it. One file per decision, numbered in order. A later record supersedes an earlier one by saying so;
records are not rewritten afterwards.

| No. | Decision | Status |
|---|---|---|
| 0001 | [regulation.bin is compressed with a 64 KB zstd window](0001-regulation-zstd-window.md) | in use since 3.13.2 |
| 0002 | [Merged Oodle files stay at level 6 (6/6)](0002-kraken-layout-speed.md) | superseded by 0007 |
| 0003 | [Release feeds are signed with minisign](0003-signed-releases.md) | in use from the release after 3.13.2 |
| 0004 | [Velopack installs and applies updates; the launcher decides what to trust and undoes failed starts](0004-velopack.md) | in use from the release after 3.13.2 |
| 0005 | [The launcher's own records go into one SQLite database, through SQLAlchemy and Alembic](0005-storage.md) | in use since 3.16.0 |
| 0006 | [Composed character scripts are checked with Lua 5.1 itself (lupa) before a build is used](0006-lua-parser.md) | in use from 3.20.0; its Havok-syntax rule superseded by 0009 |
| 0007 | [Merged Oodle files are written at level 4 (4/4)](0007-kraken-level-4.md) | in use from the release after 3.21.0-beta.2 |
| 0008 | [The 64 KB zstd rule is about how far back the data reaches](0008-zstd-window-reason.md) | in use (corrects 0001's reason) |
| 0009 | [Havok Script's own syntax is a warning, not a refusal, in the character-script check](0009-havok-script-syntax.md) | in use from the release after 3.21.0-beta.3 |
| 0010 | [The backend is separate from Qt; the session is the one seam](0010-backend-separation.md) | accepted |
| 0011 | [The interface talks to the backend over loopback HTTP and server-sent events](0011-transport.md) | proposed |
| 0012 | [The backend process dies with the app: onedir, stdin watchdog, Job Object, startup sweep](0012-process-lifecycle.md) | proposed |
| 0013 | [Velopack stays the updater; the desktop app and the API package live in this repository](0013-updater-and-repo-layout.md) | proposed |
| 0014 | [The Qt app is kept on `legacy/qt-desktop` and a `qt-final-v*` tag before it leaves `main`](0014-qt-preservation.md) | proposed |
