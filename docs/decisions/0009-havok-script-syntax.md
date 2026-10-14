# 0009 Havok Script's own syntax is a warning, not a refusal, in the character-script check

**Status:** in use from the release after 3.21.0-beta.3. Supersedes [0006](0006-lua-parser.md) in one point: what
the check does with syntax that is Havok Script's and not Lua 5.1's. The rest of 0006 stands (lupa's `lua51`,
compile only, never run; the error named with its line and the part that introduced it).

## Decision

The check still compiles the composed `c0000.hks` with Lua 5.1 and still refuses the build on a real syntax error.
When the text uses one of Havok Script's own forms, it is not refused for that:

- The integer literal `0x…hi` is read as `0` before compiling, so the rest of the script is still checked; each
  line that has one gets a warning.
- The integer literal `0x…hl` is refused, naming the line and the part it came from: the game's compiler never
  accepts it (owner, 2026-10-14).
- The reserved words `hstructure` and `hmake` can't be read by Lua 5.1 at all. A failure at or after the first line
  using one is not counted; the lines before it were checked. That line gets a warning.

The warning goes in the build's report and log, worded so it claims only what was checked: "action/script/c0000.hks
line 12 uses Havok Script syntax (hstructure) that this check can't read; the lines before it were checked." It
does not say the game accepts the line: that depends on the script and, for `hi` literals, on a compiler option
whose state is unknown.

## Why

0006's "would reopen it" condition is met: the game's own lexer (Havok Script 2018.1 in `eldenring.exe`) has the
reserved words `hstructure` and `hmake` and the `hi`/`hl` literals (static reading, 2026-10-12; tools/roundtable-dev
game model, `havok-script.md`). A mod using them would be refused although the game may well load it, while a
broken script would go unnoticed if the check simply stopped at such syntax. Reading the literals as numbers keeps
the check whole for them; for the structure words, checking up to the first one is the most that a Lua 5.1 compiler
can do.

## Limits

- `hl` literals never compile in this game build (it lacks 64-bit integer support), so they are refused; `hi`
  literals need a compiler option whose state for character scripts is unknown, so they stay a warning.
- An `hl` literal is looked for outside `--` comments only; one inside a string is (wrongly) refused too.
- No in-game test has been made with a text `c0000.hks` using `hstructure` or `hmake` (spec §8.11, test 5).

## Would reopen it

A parser that reads Havok Script's full syntax; evidence that the game refuses one of these forms in character
scripts.
