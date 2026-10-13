# 0008 The 64 KB zstd rule is about how far back the data reaches

**Status:** in use. Corrects the reason given in [0001](0001-regulation-zstd-window.md); its rule is unchanged.

## Decision

`regulation.bin` stays compressed with zstd's `window_log` 16 and no content size, as 0001 decided. Only the reason
changes: what the game needs is that the compressed data never refers more than 64 KB back, not a particular window
value in the frame header.

## Why

- The game's own `regulation.bin` declares a **64 MB** window in its zstd frame (window descriptor 0x80, windowLog 26,
  level 21, no content size), and the game loads it. So the header's window field is not what the game enforces.
- Static reading of the game (2026-10-12) suggested its regulation path decodes through a fixed 64 KB history, so a
  frame whose matches reach further back reads outside it: an access violation, the crash 0001 saw, not a zstd error.
- In game on Windows (2026-10-13): the game's regulation recompressed with a 64 KB window but its header patched to
  claim 64 MB **loaded**. That confirms it: the limit is match distance.
- Compressing with `window_log` 16 keeps every match within 64 KB, which is why 0001's rule works.
