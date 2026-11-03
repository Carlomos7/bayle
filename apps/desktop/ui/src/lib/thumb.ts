/** Small words that make poor initials: "The Convergence Mod" → "C", not "TC". */
const SKIP = new Set(['the', 'a', 'an', 'of', 'and', 'for', 'mod', 'mods', '+', '&']);

/** Up to two letters from a mod's name: "Seamless Co-op" → "SC", "Convergence" → "Co", "PieGuy's Pack" → "PP". */
export function initials(name: string) {
  const words = name.replace(/['’]s\b/g, '').split(/[\s\-_.:]+/).filter((w) => w && !SKIP.has(w.toLowerCase()) && /[\p{L}\p{N}]/u.test(w));
  if (!words.length) return name.slice(0, 2).toUpperCase() || '?';
  if (words.length === 1) { const w = words[0]!; return w[0]!.toUpperCase() + (w[1]?.toLowerCase() ?? ''); }
  return (words[0]![0]! + words[1]![0]!).toUpperCase();
}

/** A stable hue per name, so a mod keeps its colour everywhere and across sessions. */
export function hueOf(name: string) {
  let h = 2166136261;
  for (const ch of name.toLowerCase()) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return (h >>> 0) % 360;
}
