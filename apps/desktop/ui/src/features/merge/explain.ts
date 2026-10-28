import type { BuildReport, Clash, FileFamily, Profile, Rule } from '@/api';
import { FAMILY } from './words';

export const modName = (p: Profile, id?: string) => (id ? p.mods.find((m) => m.id === id)?.name ?? id : '');

/** The rule a clash follows, if any: its own kind's rule, else one it is coupled to. */
export function ruleFor(b: BuildReport, family: FileFamily): { rule: Rule; coupled: boolean } | undefined {
  const own = b.rules.find((r) => r.family === family && !r.dormant);
  if (own) return { rule: own, coupled: false };
  const via = b.rules.find((r) => !r.dormant && r.coupled?.includes(family));
  return via ? { rule: via, coupled: true } : undefined;
}

/** Why the winner won, in a few words. Printed wherever a winner is shown. */
export function reasonText(c: Clash, b: BuildReport): string {
  switch (c.reason) {
    case 'pick': return 'your pick';
    case 'both': return 'both kept, approved by you';
    case 'rule': return `your rule for ${FAMILY[c.family].label}`;
    case 'coupled': { const r = ruleFor(b, c.family); return `kept with your ${r ? FAMILY[r.rule.family].label : ''} rule`; }
    default: return 'loads later';
  }
}

/** The order that settles a kind today, winner first, and where it came from. */
export function kindOrder(p: Profile, b: BuildReport, family: FileFamily): { order: string[]; source: 'rule' | 'coupled' | 'order'; rule?: Rule } {
  const mods = [...new Set(b.clashes.filter((c) => c.family === family).flatMap((c) => c.sides.map((s) => s.modId)))];
  const r = ruleFor(b, family);
  if (r) {
    const rest = mods.filter((m) => !r.rule.order.includes(m));
    return { order: [...r.rule.order.filter((m) => mods.includes(m)), ...rest], source: r.coupled ? 'coupled' : 'rule', rule: r.rule };
  }
  const pos = (id: string) => p.mods.findIndex((m) => m.id === id);
  return { order: mods.sort((x, y) => pos(y) - pos(x)), source: 'order' };
}

/** Kinds with something to decide: at least one clash that is not a whole-file-only kind. Whole-file kinds coupled to a rule show inside that rule's row. */
export function overlapKinds(b: BuildReport): FileFamily[] {
  const fams = [...new Set(b.clashes.map((c) => c.family))];
  return b.families.filter((f) => fams.includes(f) && b.clashes.some((c) => c.family === f && !c.unsupported));
}

/** "its armour stats (EquipParamProtector)" → plain words and the code name, shown apart. */
export const splitWhat = (what: string) => { const m = what.match(/^(.*?)\s*\(([^)]+)\)$/); return m ? { plain: m[1]!, code: m[2] } : { plain: what, code: undefined }; };

/** What still needs a person, by kind. Shared by the page (to place the intro card) and Needs you. */
export function needsOf(b: BuildReport) {
  return {
    dropped: b.dropped.filter((d) => !d.accepted),
    decide: b.clashes.filter((c) => c.unresolved),
    check: b.clashes.filter((c) => c.needsReview && !c.unresolved),
    rules: b.rules.filter((r) => r.meetsNew && !r.dormant),
  };
}
export const needsCount = (b: BuildReport) => { const n = needsOf(b); return n.dropped.length + n.decide.length + n.check.length + n.rules.length; };
export const needsRebuild = (b: BuildReport) => b.state === 'stale' || b.pending.length > 0;

/** "A wins over B, C", the way people say it. */
export const winsOver = (p: Profile, order: string[]) => order.length < 2 ? modName(p, order[0]) : `${modName(p, order[0])} wins over ${order.slice(1).map((id) => modName(p, id)).join(', ')}`;
