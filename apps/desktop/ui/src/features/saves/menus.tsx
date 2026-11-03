import { Copy, Undo2 } from 'lucide-react';
import type { SaveFile, SlotRef } from '@/api';
import { header, item, sub, type MenuEntry } from '@/components/bayle/menu';
import { planCopy, refKey, type CharSource, type PendingCopy } from './model';

type Plan = (p: PendingCopy | string) => void;

/** "Copy to ▸ save ▸ slot" for a character. Its own slot is left out. */
export function copyToMenu(from: SlotRef, name: string, saves: SaveFile[], onPlan: Plan, label = 'Copy to', icon = <Copy />): MenuEntry {
  return sub(label, saves.map((s) => sub(s.label, [
    item('First empty slot', () => onPlan(planCopy(from, name, s)), { disabled: !s.slots.some((x) => !x.character), why: 'No empty slot' }),
    ...s.slots.filter((sl) => refKey({ saveId: s.id, n: sl.n }) !== refKey(from)).map((sl) =>
      item(`Slot ${sl.n} · ${sl.character ? sl.character.name : 'empty'}`, () => onPlan(planCopy(from, name, s, sl.n)), { hint: sl.character ? 'replaces it, backed up first' : undefined })),
  ])), { icon });
}

export const restoreToMenu = (from: SlotRef, name: string, saves: SaveFile[], onPlan: Plan) => copyToMenu(from, name, saves, onPlan, 'Restore to', <Undo2 />);

/** "Copy a character here…" for an empty slot: every character, grouped by where it lives. */
export function copyHereMenu(to: SaveFile, n: number, sources: CharSource[], onPlan: Plan): MenuEntry[] {
  const groups = new Map<string, CharSource[]>();
  sources.forEach((s) => { if (!groups.has(s.group)) groups.set(s.group, []); groups.get(s.group)!.push(s); });
  return [
    header(`Copy a character into slot ${n}`),
    ...[...groups.entries()].map(([g, list]) => sub(g, list.map((s) => item(s.character.name, () => onPlan(planCopy(s.ref, s.character.name, to, n)), { hint: `Lv ${s.character.level} · ${s.where}` })))),
  ];
}
