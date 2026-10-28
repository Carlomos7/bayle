/**
 * The Merge page over the gateway, at file level: the build report, what a rebuild needs, and playing without a
 * left-out change. Engine side: routers/builds.py and modules/mods/builds.py. The engine merges in load order, so the
 * report says `choices: false` and the page offers no picks, rules, suggestions or piece search.
 *
 * Mods arrive as profile entry indexes; the page's ids come from the same `mods` read the Mods page uses (modsCommon).
 *
 * Not connected (Phase 2, needs the merger to apply choices and a per-piece record): resolveClash, setRule,
 * confirmRule, discardPending, searchPieces, suggestOrder. They stay "not connected" via the gateway's proxy.
 */
import type { BayleApi } from '../../BayleApi';
import type { BuildCell, BuildChange, BuildPlan, BuildReport, Clash, DroppedChange, FileFamily, ModId, Outcome } from '../../types';
import type { Gateway } from '../hub';
import { modIdOf, readFacts, said } from './modsCommon';

/* ------------------------------------------------------------------ engine shapes (modules/mods/builds.py) */

interface EngineBuildFile {
  path: string; family: FileFamily; mods: number[]; merged: boolean; skipped: string; parts: number;
  clashes: { part: string; mods: number[] }[]; warnings: string[];
}
interface EngineDropped {
  id: string; mod: number; file: string; family: FileFamily; kind: 'whole_copy' | 'left_out' | 'lacks'; detail: string; count: number; accepted: boolean;
}
export interface EngineBuild {
  state: 'single' | 'stacked' | 'current' | 'stale' | 'failed' | null;
  reasons: string[]; built_on: string; mods: { index: number; name: string }[]; files: EngineBuildFile[]; dropped: EngineDropped[];
}
export interface EnginePreview {
  state: EngineBuild['state']; blocked: string; detail: string; tool: string; needs_allow: boolean; problem: string;
  files: string[]; packs: string[]; reasons: string[];
}

const OP = { build: 'builds', preview: 'builds_preview', accept: 'builds_accept_dropped' } as const;

/* ------------------------------------------------------------------ mapping */

/** The engine's reasons are its own sentences; the kind is read off them where they say it plainly. */
export function changeOf(reason: string): BuildChange {
  const kind: BuildChange['kind'] =
    /launcher|earlier version/i.test(reason) ? 'setup-changed'
    : /game was updated|game's own|game's copy/i.test(reason) ? 'game-updated'
    : /load order changed|loads after|now loads after|load after/i.test(reason) ? 'reordered'
    : /not combined|ships .* now|can be merged/i.test(reason) ? 'added'
    : /no longer/i.test(reason) ? 'removed'
    : /changed since|copy changed|copies changed/i.test(reason) ? 'mod-updated'
    : 'setup-changed';
  return { kind, title: reason.charAt(0).toUpperCase() + reason.slice(1) };
}

/** "today, 00:31" for a record's "2026-10-28 00:31:07"; the date as it is when it cannot be read. */
export function builtOn(when: string, now = new Date()): string | undefined {
  if (!when) return undefined;
  const t = new Date(when.replace(' ', 'T'));
  if (Number.isNaN(t.getTime())) return when;
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diff = Math.round((day(now) - day(t)) / 86_400_000);
  const hm = t.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });
  return `${diff === 0 ? 'today' : diff === 1 ? 'yesterday' : t.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}, ${hm}`;
}

function droppedOf(d: EngineDropped, id: ModId): DroppedChange {
  const base = { id: d.id, modId: id, family: d.family, file: d.file, accepted: d.accepted };
  switch (d.kind) {
    case 'whole_copy': return { ...base, what: `its copy of ${d.file}`, reason: `Bayle can't merge this file${d.detail ? ` (${d.detail})` : ''}, so the mod that loads later is used whole.` };
    case 'left_out': return { ...base, what: `${d.count} ${d.count === 1 ? 'part' : 'parts'} of ${d.file} that its copy leaves out`, reason: "Its copy leaves them out, so they are left out of the build too." };
    default: return { ...base, what: `inner files of ${d.file} the game has`, reason: d.detail };
  }
}

export function toBuildReport(profileId: string, e: EngineBuild, idOf: (index: number) => ModId | undefined): BuildReport {
  const id = (i: number) => idOf(i);
  const none = e.state === null || (e.state === 'single' && !e.reasons.length);
  const state: BuildReport['state'] = none ? 'none' : e.state === 'current' ? 'ready' : 'stale';
  const mods = (list: number[]) => list.map(id).filter((x): x is ModId => !!x);

  const sums = new Map<string, BuildCell>();
  const add = (modId: ModId, family: FileFamily, outcome: Outcome, count: number) => {
    const key = `${modId}\n${family}\n${outcome}`;
    const cell = sums.get(key) ?? { modId, family, outcome, count: 0 };
    cell.count += count;
    sums.set(key, cell);
  };
  const clashes: Clash[] = [];
  const reportLines: string[] = [];
  for (const f of e.files) {
    const owners = mods(f.mods);
    if (f.merged) {
      owners.forEach((m) => add(m, f.family, 'merged', 1));
      // The record keeps which mods met at a part, so a part is won by the last of them and lost by the others.
      const groups = new Map<string, number[]>();
      for (const c of f.clashes) groups.set(c.mods.join(','), c.mods);
      for (const [key, who] of groups) {
        const involved = mods(who);
        const parts = f.clashes.filter((c) => c.mods.join(',') === key).length;
        involved.forEach((m, i) => add(m, f.family, i === involved.length - 1 ? 'won' : 'lost', parts));
        if (involved.length < 2) continue;
        const winnerId = involved[involved.length - 1]!;
        clashes.push({
          id: `${f.path}#${key}`, family: f.family, file: f.path, piece: `${f.path}: ${parts} ${parts === 1 ? 'part' : 'parts'}`,
          sides: involved.map((modId) => ({ modId, value: '' })), resolution: 'order', winnerId, reason: 'order',
        });
      }
      reportLines.push(`${f.path}: merged from ${owners.length} mods; ${f.parts} ${f.parts === 1 ? 'part' : 'parts'} changed, ${f.clashes.length} changed by more than one mod (the later one's used)`);
    } else {
      owners.forEach((m) => add(m, f.family, 'unsupported', 1));
      if (owners.length > 1) {
        clashes.push({
          id: `${f.path}#whole`, family: f.family, file: f.path, piece: f.path, unsupported: true,
          sides: owners.map((modId) => ({ modId, value: '' })), resolution: 'order', winnerId: owners[owners.length - 1], reason: 'order',
        });
      }
      reportLines.push(`${f.path}: not merged${f.skipped ? ` (${f.skipped})` : ''}; the last of ${owners.length} mods' copies is used`);
    }
    f.warnings.forEach((w) => reportLines.push(`  warning: ${w}`));
  }

  const dropped = e.dropped.flatMap((d) => { const m = id(d.mod); return m ? [droppedOf(d, m)] : []; });
  return {
    profileId, state,
    // shortcut: the record names no game version; "the game" until it does.
    baseline: { game: 'the game', exceptions: [] },
    builtOn: builtOn(e.built_on),
    changes: state === 'stale' ? (e.reasons.length ? e.reasons : ['Packages ship parameters that are not combined']).map(changeOf) : [],
    families: [...new Set(e.files.map((f) => f.family))],
    cells: [...sums.values()],
    clashes,
    // shortcut: kind rules and per-piece picks need the merger to apply them (Phase 2), so none exist.
    rules: [], pending: [], dropped, kept: [], reportLines, choices: false,
  };
}

export function toBuildPlan(p: EnginePreview): BuildPlan {
  const steps: BuildPlan['steps'] = [];
  const list = (xs: string[]) => xs.slice(0, 3).join(', ') + (xs.length > 3 ? ` and ${xs.length - 3} more` : '');
  if (p.blocked === 'rebuild_game_running') steps.push({ title: 'Close the game first', detail: 'It has the files a rebuild replaces open.' });
  else if (p.blocked === 'rebuild_blocked') steps.push({ title: "A rebuild can't start", detail: p.detail });
  else if (p.blocked === 'nothing_to_rebuild') steps.push({ title: 'Nothing to rebuild', detail: 'No packages share a file or parameters that could be combined.' });
  if (p.problem) steps.push({ title: "The rebuild tool can't run", detail: p.problem });
  else if (p.needs_allow) steps.push({ title: `Ask before running ${p.tool}`, detail: "Bayle has not run this version of the tool yet, so it asks first." });
  if (p.packs.length > 1) steps.push({ title: `Combine the parameters of ${p.packs.length} packs`, detail: list(p.packs) });
  if (p.files.length) steps.push({ title: `Merge ${p.files.length} game ${p.files.length === 1 ? 'file' : 'files'} that more than one mod ships`, detail: list(p.files) });
  if (!p.blocked) steps.push({ title: 'Check the result, then put it in place', detail: 'The old build is kept for Undo.' });
  return { steps };
}

/* ------------------------------------------------------------------ the adapter */

export function buildsApi(gateway: Gateway): Partial<BayleApi> {
  const call = <T>(operation: string, params?: Record<string, unknown>) => gateway.call<T>(operation, params).catch((e: unknown) => { throw said(e); });
  return {
    async getBuild(profileId) {
      const [facts, build] = await Promise.all([readFacts(gateway, profileId), call<EngineBuild>(OP.build, { profile: profileId })]);
      const ids = new Map(facts.entries.map((x) => [x.index, modIdOf(profileId, x)]));
      return toBuildReport(profileId, build, (i) => ids.get(i));
    },
    async previewBuild(profileId) {
      return toBuildPlan(await call<EnginePreview>(OP.preview, { profile: profileId }));
    },
    async acceptDropped(profileId, droppedId) {
      await call(`${OP.accept}`, { profile: profileId, dropped_id: droppedId });
      return { message: 'Playing without it' };
    },
    // shortcut: resolveClash, setRule, confirmRule, discardPending, searchPieces and suggestOrder stay not connected;
    // upgrade in Phase 2, when the merger applies picks and rules and the build keeps a per-piece record.
  };
}
