/** The presenter's pure text helpers (views/profile_transfer.py), kept the same so both apps read alike. */
export const LARGE_MOD = 1024 ** 3; // a mod this big is marked in the checklist
export const LARGE_EXPORT = 2 * 1024 ** 3; // an export this big warns (and the backend asks once)

export function sizeText(n: number): string {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return n ? `${Math.max(1, Math.floor(n / 1024))} KB` : "0 KB";
}

export function seconds(s: number): string {
  s = Math.round(s);
  if (s < 60) return `${Math.max(1, s)} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ${s % 60} s`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

export const total = (n: number, size: number) => `${n} ${n === 1 ? "mod" : "mods"} · ${sizeText(size)}`;

/** The starting README of an export (services/profile_transfer.py readme_text). */
export function readmeText(name: string, version: string, author: string, mods: { name: string; enabled: boolean }[]) {
  const who = [version ? `Version ${version}` : "", author ? `by ${author}` : ""].filter(Boolean).join(" · ");
  const lines = [`# ${name || "Profile"}`, "", ...(who ? [who, ""] : []), "## Mods", ""];
  return [...lines, ...mods.map((m) => `- ${m.name}${m.enabled ? "" : " (off)"}`)].join("\n") + "\n";
}

export const bigWarning = (biggest: { name: string; size: number }[]) =>
  `The biggest: ${biggest.map((m) => `${m.name} (${sizeText(m.size)})`).join(", ")}. Untick mods your friend already has to make it smaller.`;

export function progressText(done: number, total: number, n: number, count: number, elapsed: number) {
  const pct = total ? Math.floor((100 * done) / total) : 0;
  const left = done && elapsed >= 2 ? (elapsed / done) * (total - done) : -1;
  return {
    pct,
    title: `${pct}%  ·  file ${n} of ${count}`,
    bytes: `${sizeText(done)} of ${sizeText(total)}`,
    eta: left >= 0 ? `About ${seconds(left)} left` : "Working out the time left...",
  };
}

export const doneText = (path: string, size: number, took: number) =>
  `Done: ${path.split(/[\\/]/).pop()} (${sizeText(size)}, took ${seconds(took)}).`;
