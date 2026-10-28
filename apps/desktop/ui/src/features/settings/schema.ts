import type { Game, Settings, SettingsPatch } from '@/api';

/**
 * Every row on the Settings page, as data. The page renders these
 * generically, so "changed from default", Reset, and search work the same
 * for every row without per-row code.
 */

export type SectionId = 'locations' | 'launch' | 'backups' | 'appearance' | 'updates' | 'logs' | 'shortcuts' | 'advanced' | 'about';

/** Where a value lives in Settings: [group, key] or [group, key, subKey] for per-game records. */
export type SettingPath = readonly [keyof Settings, string] | readonly [keyof Settings, string, string];

export type RowKind =
  | { type: 'switch' }
  | { type: 'segmented'; options: { value: string; label: string }[]; numeric?: boolean }
  | { type: 'theme' }
  | { type: 'path'; pick: 'folder' | 'file' | 'none'; /** For a file pick: what the dialog offers. */ filters?: { name: string; extensions: string[] }[] }
  | { type: 'perGame' }
  | { type: 'units'; units: string[] }
  | { type: 'action' }
  | { type: 'shortcut'; keys: string[] }
  | { type: 'about' };

export interface RowDef {
  id: string;
  section: SectionId;
  /** Small uppercase sub-header inside the section; rows with the same group share a card. */
  group?: string;
  label: string;
  /** Plain text; `backticks` render as code. */
  help?: string;
  /** Extra words search should match. */
  keywords?: string;
  kind: RowKind;
  /** Values this row edits. Empty for actions. */
  paths: SettingPath[];
  /** Paths the user picked are not "changed from default" and survive Reset all. */
  noDefault?: boolean;
  /** For perGame rows: which game each path belongs to. */
  labels?: string[];
  /** Small tag after the label, e.g. "preview". */
  tag?: string;
}

export interface SectionDef { id: SectionId; title: string; description: string }

export const SECTIONS: SectionDef[] = [
  { id: 'locations', title: 'Games and folders', description: 'Where Bayle finds the games, me3 and your mods.' },
  { id: 'launch', title: 'Launch', description: 'What happens when you press Launch, and after you quit.' },
  { id: 'backups', title: 'Saves and backups', description: 'Keeping your saves safe across sessions and mods.' },
  { id: 'appearance', title: 'Appearance', description: 'How Bayle looks on this computer.' },
  { id: 'updates', title: 'Updates', description: 'Signed updates with automatic rollback if a version fails to start.' },
  { id: 'logs', title: 'Logs and support', description: 'What to send when something goes wrong.' },
  { id: 'shortcuts', title: 'Shortcuts', description: 'Work faster from the keyboard. Right-click works on most rows too.' },
  { id: 'advanced', title: 'Advanced', description: 'For troubleshooting. Your mods and saves are never touched here.' },
  { id: 'about', title: 'About', description: 'A mod launcher and save toolkit for Elden Ring and Nightreign, built on me3.' },
];

const sw = (id: string, section: SectionId, group: string | undefined, label: string, path: SettingPath, help?: string, extra: Partial<RowDef> = {}): RowDef =>
  ({ id, section, group, label, help, kind: { type: 'switch' }, paths: [path], ...extra });

const key = (id: string, group: string, label: string, keys: string[]): RowDef => ({ id, section: 'shortcuts', group, label, kind: { type: 'shortcut', keys }, paths: [], keywords: keys.join(' ') });

/** Build the rows; games decide the per-game rows. */
export function buildSchema(games: Game[]): RowDef[] {
  const playable = games.filter((g) => g.supported);
  return [
    ...playable.map((g): RowDef => ({ id: `game-${g.id}`, section: 'locations', label: g.name, kind: { type: 'path', pick: 'file', filters: [{ name: 'Game program', extensions: ['exe'] }] }, paths: [['paths', 'games', g.id]], noDefault: true, help: g.build ? `Found in the Steam library · build ${g.build}` : undefined, keywords: 'game folder steam exe' })),
    { id: 'me3', section: 'locations', label: 'me3', kind: { type: 'path', pick: 'file' }, paths: [['paths', 'me3']], noDefault: true, keywords: 'mod engine loader', help: 'Bayle never replaces me3 itself.' },
    { id: 'profiles', section: 'locations', label: 'Profiles folder', kind: { type: 'path', pick: 'folder' }, paths: [['paths', 'profiles']], noDefault: true },
    { id: 'sharedMods', section: 'locations', label: 'Shared mods', kind: { type: 'path', pick: 'folder' }, paths: [['paths', 'sharedMods']], noDefault: true, help: 'One folder of mods that every profile can use.', keywords: 'library' },

    sw('autoRebuild', 'launch', 'Merged mods', 'Rebuild merged mods before launch', ['launch', 'autoRebuild'], 'When mods, their order or the game changed, Launch rebuilds first. Off: Launch asks.'),
    sw('installOverhauls', 'launch', 'Merged mods', 'Install overhauls with Bayle', ['launch', 'installOverhauls'], 'Every change is shown first, and each install can be undone from Activity.', { tag: 'preview' }),
    sw('bootBoost', 'launch', 'me3 options', 'Boot boost', ['launch', 'bootBoost'], 'Starts the game faster by keeping a decrypted copy of its archive indexes. Off passes `--no-boot-boost`.'),
    sw('showLogos', 'launch', 'me3 options', 'Show intro logos', ['launch', 'showLogos'], 'me3 skips the publisher logos by default. On passes `--show-logos`.'),
    sw('diagnostics', 'launch', 'me3 options', 'Diagnostics', ['launch', 'diagnostics'], 'More detail for troubleshooting; slower start, bigger log. Passes `--diagnostics`.'),
    sw('closeBefore', 'launch', 'Leftover game processes', 'Close them before launch', ['launch', 'closeLeftoversBefore'], 'Hidden copies of the game stop Steam from starting it.'),
    sw('closeAfter', 'launch', 'Leftover game processes', 'Close them after quitting', ['launch', 'closeLeftoversAfter'], 'So Steam and Discord stop showing the game as running. Needs admin once.'),
    sw('warnLeftovers', 'launch', 'Leftover game processes', 'Warn when one is found', ['launch', 'warnLeftovers'], 'Shows a bar at the top of the window.'),
    sw('offlineSkipOverhaul', 'launch', 'Offline play', 'Skip the overhaul too', ['launch', 'offlineSkipOverhaul'], 'Launch Offline already turns off Seamless Co-op and online play.'),
    sw('offlineStartSteam', 'launch', 'Offline play', 'Start Steam if needed', ['launch', 'offlineStartSteam'], 'Pick Start in Offline Mode if Steam asks.'),
    sw('offlineSkipConfirm', 'launch', 'Offline play', 'Skip the confirmation', ['launch', 'offlineSkipConfirm']),
    { id: 'steamShortcut', section: 'launch', group: 'Steam', label: 'Steam shortcuts', kind: { type: 'action' }, paths: [], help: 'Point them at Bayle so Gaming Mode launches with mods. `--game er --play` runs a session without the window.', keywords: 'deck gaming mode' },

    { id: 'repair', section: 'backups', label: 'Repair saves after quitting', kind: { type: 'perGame' }, paths: playable.map((g): SettingPath => ['saves', 'repairAfterQuit', g.id]), labels: playable.map((g) => g.name), help: "Re-signs the save's encrypted sections so the game accepts it. Leave both on." },
    sw('backupBeforeLaunch', 'backups', undefined, 'Back up saves before launch', ['saves', 'backupBeforeLaunch'], 'Off by default: the game keeps its own backup and each repair makes a copy anyway.'),
    { id: 'keep', section: 'backups', label: 'Keep', kind: { type: 'units', units: ['copies', 'days'] }, paths: [['saves', 'keepCopies'], ['saves', 'keepDays']], help: 'The newest copies of each save, plus everything from recent days.', keywords: 'rotation retention' },
    { id: 'backupsFolder', section: 'backups', label: 'Backups folder', kind: { type: 'path', pick: 'none' }, paths: [['paths', 'backups']], noDefault: true },

    { id: 'theme', section: 'appearance', label: 'Theme', kind: { type: 'theme' }, paths: [['appearance', 'theme']], keywords: 'dark light bayle tarnished colour color' },
    { id: 'effects', section: 'appearance', label: 'Effects', kind: { type: 'segmented', options: [{ value: 'full', label: 'Full' }, { value: 'reduced', label: 'Reduced' }, { value: 'off', label: 'Off' }] }, paths: [['appearance', 'effects']], help: 'Glow and motion. Reduced keeps the fades; Off removes them.', keywords: 'animation' },
    { id: 'density', section: 'appearance', label: 'Density', kind: { type: 'segmented', options: [{ value: 'comfortable', label: 'Comfortable' }, { value: 'compact', label: 'Compact' }] }, paths: [['appearance', 'density']], help: 'Compact fits more rows on screen.' },
    { id: 'tips', section: 'appearance', label: 'First-run tips', kind: { type: 'action' }, paths: [] },

    { id: 'installed', section: 'updates', label: 'Installed', kind: { type: 'action' }, paths: [], keywords: 'version check' },
    { id: 'channel', section: 'updates', label: 'Channel', kind: { type: 'segmented', options: [{ value: 'stable', label: 'Stable' }, { value: 'beta', label: 'Beta' }] }, paths: [['updates', 'channel']], help: 'Beta gets new features first.' },
    sw('checkOnStart', 'updates', undefined, 'Check on start', ['updates', 'checkOnStart'], 'At most once an hour, from GitHub. You choose when to install.'),
    sw('me3Notices', 'updates', undefined, 'Tell me about me3 updates', ['updates', 'me3Notices'], 'Once a day. A notice only; nothing is installed.'),

    { id: 'supportLogs', section: 'logs', label: 'Save logs for support', kind: { type: 'action' }, paths: [], help: 'One .zip with the logs, your profile files and system info. Paths are anonymised.' },
    { id: 'logsFolder', section: 'logs', label: 'Logs folder', kind: { type: 'path', pick: 'none' }, paths: [['paths', 'logs']], noDefault: true },
    { id: 'keepLogs', section: 'logs', label: 'Keep logs for', kind: { type: 'segmented', numeric: true, options: [{ value: '7', label: '7 days' }, { value: '30', label: '30 days' }, { value: '90', label: '90 days' }] }, paths: [['logs', 'keepDays']] },

    key('k-launch', 'Everywhere', 'Launch', ['Ctrl', 'L']),
    key('k-search', 'Everywhere', 'Search anything', ['Ctrl', 'K']),
    key('k-pages', 'Everywhere', 'Go to a page', ['Ctrl', '1…6']),
    key('k-new', 'Everywhere', 'New profile', ['Ctrl', 'N']),
    key('k-install', 'Everywhere', 'Install mod', ['Ctrl', 'O']),
    key('k-rescan', 'Everywhere', 'Rescan mods and saves', ['F5']),
    key('k-help', 'Everywhere', 'How to use', ['F1']),
    key('k-find', 'Everywhere', 'Search this page', ['/']),
    key('k-toggle', 'Mods', 'Turn on or off', ['Space']),
    key('k-select', 'Mods', 'Select a row', ['X']),
    key('k-all', 'Mods', 'Select all shown', ['Ctrl', 'A']),
    key('k-move', 'Mods', 'Move up or down', ['Ctrl', '↑', '↓']),
    key('k-remove', 'Mods', 'Remove', ['Del']),
    key('k-save', 'Mods', 'Save the open panel', ['Ctrl', 'S']),
    key('k-esc', 'Mods', 'Clear selection, close', ['Esc']),

    { id: 'clearCache', section: 'advanced', label: "Clear me3's boot boost cache", kind: { type: 'action' }, paths: [], help: 'me3 rebuilds it on the next launch, which takes a little longer once.' },
    { id: 'settingsFile', section: 'advanced', label: 'Settings file', kind: { type: 'path', pick: 'none' }, paths: [['paths', 'settingsFile']], noDefault: true },
    { id: 'resetAll', section: 'advanced', label: 'Reset every setting', kind: { type: 'action' }, paths: [], help: 'Puts all of the settings above back to their defaults. Folders you picked are kept.' },

    { id: 'about', section: 'about', label: 'Bayle', kind: { type: 'about' }, paths: [], keywords: 'version licence license github' },
  ];
}

/* ------------------------------------------------------------------ reading + writing values */

export type SettingValue = string | number | boolean;

export function getValue(s: Settings, path: SettingPath): SettingValue | undefined {
  const group = s[path[0]] as unknown as Record<string, unknown>;
  const v = group?.[path[1]];
  if (path.length === 3) return (v as Record<string, SettingValue> | undefined)?.[path[2]];
  return v as SettingValue | undefined;
}

/** A patch that sets one value. Per-game records are sent whole, so other games keep theirs. */
export function patchFor(s: Settings, path: SettingPath, value: SettingValue): SettingsPatch {
  if (path.length === 3) {
    const current = ((s[path[0]] as unknown as Record<string, unknown>)[path[1]] ?? {}) as Record<string, SettingValue>;
    return { [path[0]]: { [path[1]]: { ...current, [path[2]]: value } } } as SettingsPatch;
  }
  return { [path[0]]: { [path[1]]: value } } as SettingsPatch;
}

export function isChanged(row: RowDef, s: Settings, d: Settings): boolean {
  if (row.noDefault) return false;
  return row.paths.some((p) => getValue(s, p) !== getValue(d, p));
}

/** One patch that puts these rows back to their defaults (per-game records are sent whole). */
export function resetPatch(rows: RowDef[], s: Settings, d: Settings): SettingsPatch {
  const next = structuredClone(s) as unknown as Record<string, Record<string, unknown>>;
  const touched = new Set<string>();
  rows.forEach((r) => r.paths.forEach((p) => {
    const def = getValue(d, p);
    if (def === undefined) return;
    const group = next[p[0]]!;
    if (p.length === 3) group[p[1]] = { ...(group[p[1]] as object), [p[2]]: def };
    else group[p[1]] = def;
    touched.add(`${p[0]}.${p[1]}`);
  }));
  const out: Record<string, Record<string, unknown>> = {};
  touched.forEach((k) => { const [g, f] = k.split('.') as [string, string]; (out[g] ??= {})[f] = next[g]![f]; });
  return out as SettingsPatch;
}

export function rowMatches(row: RowDef, q: string, sectionTitle: string): boolean {
  if (!q) return true;
  const hay = `${row.label} ${row.help ?? ''} ${row.keywords ?? ''} ${row.group ?? ''} ${sectionTitle}`.toLowerCase();
  return q.toLowerCase().split(/\s+/).every((w) => hay.includes(w));
}

/** Help line that depends on live info. */
export function liveHelp(row: RowDef, me3Version?: string): string | undefined {
  if (row.id === 'me3' && me3Version) return `Version ${me3Version}. ${row.help ?? ''}`;
  if (row.id === 'installed') return 'Checked a few minutes ago. Bayle checks again on the next start.';
  return row.help;
}

