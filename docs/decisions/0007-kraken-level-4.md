# 0007 Merged Oodle files are written at level 4 (4/4)

**Status:** in use from the release after 3.21.0-beta.2. Supersedes [0002](0002-kraken-layout-speed.md).

## Decision

Files the launcher writes with Oodle (Kraken) are compressed at level 4, with level 4 in the DCX header (the "4/4"
layout). `formats/dcx.py` (`KRAKEN_LEVEL`) and `data/games/eldenring.json` (`dcx_writer.krak`) say so, and a test
keeps the two the same.

## Why

0002 kept level 6 because the evidence did not reach the case a faster level would help. What it asked for now exists:

- **The game accepts it.** The game's DCX reader only range-checks the header's level byte (Oodle 0–8), and Oodle
  decompresses every level the same way (static reading of the game, 2026-10-12). In game on Windows (2026-10-13), the
  88 MB common effects archive written at Kraken level 4 with header level 4 loaded with normal effects, and load time
  was not noticeably different from the game's own level-6 file.
- **The timing, on equal settings.** On the files a Nightreign Revive build recompresses (the same content, the same
  Oodle library, one machine, 2026-10-13):

  | File | Level 6 | Level 4 | Size at 6 → 4 |
  |---|---|---|---|
  | `sfx/sfxbnd_commoneffects.ffxbnd.dcx` | 111.6 s | 5.2 s | 88.0 → 90.8 MB |
  | `chr/c0000.anibnd.dcx` | 41.9 s | 1.1 s | 6.9 → 7.9 MB |
  | `chr/c0000_a00_hi.anibnd.dcx` | 5.3 s | 0.5 s | 12.2 → 12.7 MB |
  | `msg/engus/menu_dlc02.msgbnd.dcx` | 1.5 s | 0.1 s | 0.5 → 0.6 MB |
  | total | 160.2 s | 6.8 s | about 3% larger |

  About two and a half minutes saved per build, for about 3% more disk.
- 4/4 rather than 4/6: the header names the level the payload was written with, and 4/4 is the layout tested in game.

## Not decided here

- The Steam Deck: not tested there. The Deck runs the same game files through Proton, so the outcome is expected to
  match Windows, but that is an expectation, not a result.
- Builds made at level 6 stay valid and are not rebuilt for this change alone.
