import type { Mod, ModKind, Profile } from '@/api';
import type { StatusTone } from '@/components/bayle/badge';
import { dllFile, dllsOf, ownerOf, searchText } from './identity';

export type ModFilter = 'all' | 'on' | 'off' | 'issue';

export interface ModStatus {
  label: 'In place' | 'Overridden' | 'Missing' | 'Needs rebuild' | 'Off';
  tone: StatusTone;
  /** Second line under the name. */
  line: string;
  lineTone?: 'warn' | 'bad';
  /** Counts toward the Issues filter and the attention list. */
  issue: boolean;
  /** What clicking the status does, if anything. */
  action?: 'reinstall' | 'merge';
}

export const hasOverhaul = (p: Profile) => p.mods.some((m) => m.staysLast && m.enabled);

/** The line under a mod's name: what it does, and what it belongs to or comes with. */
export function describe(m: Mod, p: Profile): string {
  const owner = ownerOf(m, p);
  if (owner) return `The DLL part of ${owner.name} · ${m.description}`;
  const dlls = dllsOf(m, p);
  if (dlls.length) return `${m.description} · comes with ${dlls.map(dllFile).join(', ')}`;
  return m.description;
}

/** Pure: one mod's state in its profile. Statuses are states, never verbs. */
export function modStatus(m: Mod, p: Profile): ModStatus {
  if (m.missing) return { label: 'Missing', tone: 'bad', line: `The folder ${m.folder} is not there.`, lineTone: 'bad', issue: true, action: 'reinstall' };
  if (!m.enabled) return { label: 'Off', tone: 'off', line: describe(m, p), issue: false };
  if (m.staysLast && p.merge === 'needs') return { label: 'Needs rebuild', tone: 'warn', line: describe(m, p), issue: true, action: 'merge' };
  const winner = m.overriddenBy ? p.mods.find((x) => x.id === m.overriddenBy && x.enabled) : undefined;
  if (winner) {
    return { label: 'Overridden', tone: 'warn', line: `${m.overriddenFiles ?? 'Some'} of its changes lose to ${winner.name}, which loads later. Settle them on Merge.`, lineTone: 'warn', issue: true, action: 'merge' };
  }
  // "In place", not "Ready": the files are there and will load. Whether the mod works in game is not something Bayle can promise.
  return { label: 'In place', tone: 'ok', line: describe(m, p), issue: false };
}

export function matchesFilter(m: Mod, p: Profile, f: ModFilter, q: string): boolean {
  if (q && !searchText(m, p).includes(q.toLowerCase())) return false;
  if (f === 'on') return m.enabled;
  if (f === 'off') return !m.enabled;
  if (f === 'issue') return modStatus(m, p).issue;
  return true;
}

export const KIND_INFO: Record<ModKind, { title: string; hint: string }> = {
  package: { title: 'Packages', hint: 'Game files me3 overlays. Lower in the list wins a clash.' },
  native: { title: 'Natives', hint: 'DLLs me3 injects, top to bottom.' },
};

export const byKind = (p: Profile, kind: ModKind) => p.mods.filter((m) => m.kind === kind);
