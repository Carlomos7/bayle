import type { Character, SaveCopy, SaveFile, Slot, SlotRef } from '@/api';

/** What the right-hand column shows. */
export type Selection = { kind: 'save'; id: string } | { kind: 'copy'; id: string };

export const sameSel = (a: Selection | null, b: Selection | null) => !!a && !!b && a.kind === b.kind && a.id === b.id;

export const usedSlots = (slots: Slot[]) => slots.filter((s) => s.character).length;

export const firstEmpty = (s: SaveFile) => s.slots.find((x) => !x.character)?.n;

/** A character that can be copied somewhere, wherever it lives. */
export interface CharSource {
  ref: SlotRef;
  character: Character;
  /** Where it lives, e.g. "Seamless Co-op, slot 2" */
  where: string;
  group: string;
}

export const refKey = (r: SlotRef) => ('saveId' in r ? `s:${r.saveId}:${r.n}` : `c:${r.copyId}:${r.n}`);

export function allSources(saves: SaveFile[], copies: SaveCopy[]): CharSource[] {
  const out: CharSource[] = [];
  saves.forEach((s) => s.slots.forEach((sl) => { if (sl.character) out.push({ ref: { saveId: s.id, n: sl.n }, character: sl.character, where: `${s.label}, slot ${sl.n}`, group: s.label }); }));
  copies.filter((c) => !c.missing).forEach((c) => c.slots.forEach((sl) => { if (sl.character) out.push({ ref: { copyId: c.id, n: sl.n }, character: sl.character, where: `${c.name}, slot ${sl.n}`, group: `${c.kind === 'backup' ? 'Backup' : 'Copy'}: ${c.name}` }); }));
  return out;
}

/** A copy waiting for the user to confirm. */
export interface PendingCopy {
  from: SlotRef;
  name: string;
  saveId: string;
  saveLabel: string;
  n: number;
  /** The character that slot holds now, if any. */
  replaces?: string;
}

/** Build a pending copy into a given slot, or the first empty one. Returns a sentence when there is no room. */
export function planCopy(from: SlotRef, name: string, to: SaveFile, n?: number): PendingCopy | string {
  const slot = n ?? firstEmpty(to);
  if (!slot) return `${to.label} has no empty slot. Open it and drop onto a slot to replace a character.`;
  return { from, name, saveId: to.id, saveLabel: to.label, n: slot, replaces: to.slots.find((x) => x.n === slot)?.character?.name };
}

/* ------------------------------------------------------------------ drag and drop payloads */

export interface DragChar { ref: SlotRef; name: string; level: number }

export type DropTarget = { type: 'list'; sel: Selection } | { type: 'slot'; saveId: string; n: number };
