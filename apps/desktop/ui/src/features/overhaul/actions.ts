import type { FileAction, OverhaulSetup, SetupFile } from '@/api';

/** What Bayle does with a file, in the words shown in the "Bayle will" select. */
export const ACTION_LABEL: Record<FileAction, string> = {
  combine: 'Combine rules with other mods',
  merge: 'Merge with other mods',
  copy: 'Copy into game files',
  place: 'Place at a path',
  keep: 'Keep your copy on update',
  text: 'Build menu text',
  leave: 'Leave out',
};

/** Short past-tense words for chips and folder summaries. */
export const ACTION_SHORT: Record<FileAction, string> = {
  combine: 'combined', merge: 'merged', copy: 'copied', place: 'placed', keep: 'kept', text: 'menu text', leave: 'left out',
};

export const PICKABLE: Exclude<FileAction, 'leave'>[] = ['combine', 'merge', 'copy', 'place', 'keep', 'text'];

/** A setup file plus the action it had before being left out, so ticking it again restores it. */
export interface DraftFile extends SetupFile { before?: FileAction }

export interface Draft extends Omit<OverhaulSetup, 'files'> { files: DraftFile[] }

export const toDraft = (s: OverhaulSetup): Draft => structuredClone(s);

export const fromDraft = (d: Draft): OverhaulSetup => ({
  ...d,
  files: d.files.map(({ before: _before, ...f }) => f),
});

/** Equality that ignores the remembered "before" action. */
export const sameSetup = (a: OverhaulSetup, b: Draft) => JSON.stringify(a) === JSON.stringify(fromDraft(b));

export function countByAction(files: SetupFile[]): [FileAction, number][] {
  const m = new Map<FileAction, number>();
  files.forEach((f) => m.set(f.action, (m.get(f.action) ?? 0) + 1));
  return [...m.entries()].sort((a, b) => b[1] - a[1]);
}
