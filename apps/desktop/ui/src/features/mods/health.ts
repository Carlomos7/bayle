import type { BuildReport, Game, Profile } from '@/api';
import { hasOverhaul } from './status';
import { dllLabel } from './identity';

export type HealthFix =
  | { kind: 'rebuild' }
  | { kind: 'merge' }
  | { kind: 'mod'; modId: string }
  | { kind: 'takeOver' }
  | { kind: 'moveIn' }
  | { kind: 'turnOff'; modIds: string[] };

export interface HealthItem {
  id: string;
  tone: 'info' | 'warn' | 'bad';
  title: string;
  /** One sentence: what it means for playing. */
  detail: string;
  /** The one-click fix, and its button label. */
  fix: HealthFix;
  fixLabel: string;
}

export interface ProfileHealth {
  /** Nothing needs the user. */
  ok: boolean;
  items: HealthItem[];
  /** The one line shown next to Launch. */
  label: string;
}

/**
 * One answer to "can I just play?". The same list feeds the top bar chip and
 * the notices on Mods, so the count never disagrees with the list.
 */
export function profileHealth(game: Game | undefined, profile: Profile | undefined, build: BuildReport | undefined): ProfileHealth {
  const items: HealthItem[] = [];
  if (!game || !profile) return { ok: true, items, label: 'Nothing to fix' };
  const updated = !!(game.build && game.lastRunBuild && game.build !== game.lastRunBuild);
  const risky = profile.mods.filter((m) => m.kind === 'native' && m.enabled && m.native?.afterUpdate === 'may-fail');
  if (updated && risky.length) items.push({ id: 'dll', tone: 'warn', title: `${risky.length === 1 ? `${dllLabel(risky[0]!)} may fail` : `${risky.length} natives may fail`} after the game update`, detail: `${risky.map(dllLabel).join(', ')} hook${risky.length === 1 ? 's' : ''} into code that moved in this game build. The game may crash at start until ${risky.length === 1 ? 'its author updates it' : 'their authors update them'}.`, fix: { kind: 'turnOff', modIds: risky.map((m) => m.id) }, fixLabel: risky.length === 1 ? 'Turn it off for now' : 'Turn them off for now' });
  const unchecked = profile.mods.filter((m) => m.kind === 'native' && m.enabled && (m.native?.afterUpdate === 'unknown' || !m.native?.afterUpdate));
  if (updated && unchecked.length) items.push({ id: 'dll-unknown', tone: 'info', title: `${unchecked.map(dllLabel).join(', ')}: no evidence for this game build`, detail: 'Bayle has not checked this DLL against the new game. It may work or not; a failed launch would say.', fix: { kind: 'mod', modId: unchecked[0]!.id }, fixLabel: 'Show' });
  if (hasOverhaul(profile) && profile.merge === 'needs') items.push({ id: 'stale', tone: 'warn', title: 'Merged game data needs a rebuild', detail: build?.changes.length ? `${build.changes.length === 1 ? build.changes[0]!.title : `${build.changes.length} things changed since the last build`}. Launch rebuilds for you, about 40 s.` : 'Something it was built from changed. Launch rebuilds for you.', fix: { kind: 'rebuild' }, fixLabel: 'Rebuild now' });
  const toCheck = (build?.clashes.filter((c) => c.needsReview || c.unresolved).length ?? 0) + (build?.rules.filter((r) => r.meetsNew && !r.dormant).length ?? 0);
  if (toCheck) items.push({ id: 'picks', tone: 'warn', title: `${toCheck} decision${toCheck === 1 ? ' needs' : 's need'} a look on Merge`, detail: 'A pick whose inputs changed, a rule that settled something new, or a clash Bayle will not settle on its own.', fix: { kind: 'merge' }, fixLabel: 'Look' });
  const open = build?.dropped.filter((d) => !d.accepted) ?? [];
  if (open.length) items.push({ id: 'dropped', tone: 'bad', title: `${open.length} change${open.length === 1 ? '' : 's'} left out of the merge`, detail: open.map((d) => `${profile.mods.find((m) => m.id === d.modId)?.name}: ${d.what}`).join('; ') + '. They are not in the game even though the mod is on.', fix: { kind: 'merge' }, fixLabel: 'See what and why' });
  profile.mods.filter((m) => m.missing).forEach((m) => items.push({ id: `missing:${m.id}`, tone: 'bad', title: `${m.name}'s folder is missing`, detail: `${m.folder} is not there, so Launch leaves it out.`, fix: { kind: 'mod', modId: m.id }, fixLabel: 'Install again or remove' }));
  if (profile.installer) items.push({ id: 'installer', tone: 'warn', title: `${profile.installer.name} was set up by its own installer`, detail: "Bayle can't update or undo it until you take it over.", fix: { kind: 'takeOver' }, fixLabel: 'Take over' });
  if (profile.outsidePath) items.push({ id: 'outside', tone: 'info', title: "This profile is outside Bayle's folder", detail: `${profile.outsidePath}. Moving it in keeps its mods together and every change undoable.`, fix: { kind: 'moveIn' }, fixLabel: 'Move in' });
  const needs = items.filter((i) => i.tone !== 'info');
  // Never "ready": a built profile is not proof it works in game. "Nothing to fix" is what Bayle can actually say.
  const label = !items.length ? 'Nothing to fix' : needs.length ? `${needs.length} thing${needs.length === 1 ? '' : 's'} to fix` : 'Nothing to fix';
  return { ok: !needs.length, items, label };
}
