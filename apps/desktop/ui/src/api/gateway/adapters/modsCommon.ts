/**
 * What the Mods page adapters share: the engine's `mods` page read, the id → block index map, job running and the
 * sentences for the engine's codes. Read from apps/engine/src/bayle/api/routers/mods.py and
 * modules/mods/mods_page.py + profile_mods.py (PageFacts), which type `entries` as a loose dict.
 *
 * Ids. A profile is its .me3 path. A mod's id is what Mod Configs attaches files to (adapters/configs.ts modIdOf):
 * the DLL's or package folder's absolute path, or `seamless` for the Seamless Co-op DLL. The engine addresses an entry
 * by its block `index`, which moves when the profile changes, so the last read is kept per profile and every write
 * sends the entry's name as `expect` (the engine refuses a changed profile as `stale`).
 */
import { awaitJob } from '@/data/engine';
import type { ActivityEntry, ActivityKind, Mod, ModId, ModKind } from '../../types';
import type { components } from '../engine.gen';
import type { Gateway } from '../hub';
import { GatewayError } from '../transport';

export const OP = {
  mods: 'mods',
  setEnabled: 'mods_set_enabled',
  remove: 'mods_remove',
  move: 'mods_move',
  options: 'mods_options',
  saveOptions: 'mods_save_options',
  rebuild: 'mods_rebuild',
  checkAllowTool: 'mods_check_allow_tool',
} as const;

/* ------------------------------------------------------------------ engine shapes */

type S = components['schemas'];
type EngineDependency = S['Dependency-Output'];
/** One block of the profile (adapters/formats/me3_profile.py entries, minus `row`); the contract has no schema for it (PageFacts types `entries` as a dict). */
export interface EngineEntry {
  kind: ModKind;
  path: string;
  id: string;
  enabled: boolean;
  optional?: boolean;
  load_early?: boolean;
  initializer?: { function?: string; delay?: { ms: number } } | null;
  finalizer?: string;
  load_after: EngineDependency[];
  load_before: EngineDependency[];
  index: number;
  name: string;
}
/** PageFacts (profile_mods.py); a dict keyed by entry index arrives with string keys. */
export interface EnginePageFacts extends Omit<S['PageFacts'], 'entries'> {
  entries: EngineEntry[];
  /** The page's `overhaul` (the profile has one the launcher knows), carried here by readFacts. */
  overhaul?: { label: string } | null;
}
export interface EngineModsPage extends Omit<S['ModsPageState'], 'facts' | 'overhaul'> { facts?: EnginePageFacts | null; overhaul?: { label: string } | null }
/** mods_options (OptionsView). */
export interface EngineOptions extends Omit<S['OptionsView'], 'kind'> { kind: ModKind }

/* ------------------------------------------------------------------ small helpers */

// shortcut: no games route yet to say which DLL is the game's Seamless Co-op; upgrade with it (modules/games/catalog.py coop_dll).
const COOP_DLLS = new Set(['ersc.dll', 'nrsc.dll']);

export const baseName = (p: string) => p.split(/[\\/]/).pop() ?? p;
const isAbsolute = (p: string) => /^([a-zA-Z]:[\\/]|[\\/])/.test(p);

/** profile_edit.resolve: a relative entry path is relative to the profile's folder. */
export function resolvePath(profileId: string, path: string): string {
  if (isAbsolute(path)) return path;
  const cut = Math.max(profileId.lastIndexOf('\\'), profileId.lastIndexOf('/'));
  const dir = profileId.slice(0, cut);
  const sep = profileId.includes('\\') ? '\\' : '/';
  return `${dir}${sep}${path.replace(/^\.[\\/]/, '').replaceAll(/[\\/]/g, sep)}`;
}

const same = (a: string, b: string) => a.replaceAll('\\', '/').toLowerCase() === b.replaceAll('\\', '/').toLowerCase();
const inside = (child: string, folder: string) => same(child.slice(0, folder.length + 1), `${folder}/`);

export const modIdOf = (profileId: string, e: Pick<EngineEntry, 'kind' | 'path'>): ModId =>
  e.kind === 'native' && COOP_DLLS.has(baseName(e.path).toLowerCase()) ? 'seamless' : resolvePath(profileId, e.path);

export const bytes = (n: number) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : n < 1024 ** 3 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${(n / 1024 ** 3).toFixed(1)} GB`);

export const notWired = (what: string) => new GatewayError({ code: 'not_wired', message: `This part of Bayle isn't connected to the engine yet (${what}).` });

const INIT_KINDS = ['none', 'function', 'delay'] as const;

/** The page's rows: packages first, then natives, each in the order the page shows. Entries that load nothing have no row. */
export function toMods(profileId: string, facts: EnginePageFacts): Mod[] {
  const byIndex = new Map(facts.entries.map((e) => [e.index, e]));
  const hidden = new Set(facts.loads_nothing);
  const at = (list: number[] | undefined, i: number) => list?.includes(i) ?? false;
  const packages = facts.entries.filter((e) => e.kind === 'package' && !hidden.has(e.index));
  const out: Mod[] = [];
  for (const kind of ['package', 'native'] as const) {
    const shown = facts.display[kind] ?? facts.entries.filter((e) => e.kind === kind).map((e) => e.index);
    for (const i of shown) {
      const e = byIndex.get(i);
      if (!e || hidden.has(i)) continue;
      const file = baseName(e.path);
      const id = modIdOf(profileId, e);
      const owner = kind === 'native' ? packages.find((p) => p.path && inside(resolvePath(profileId, e.path), resolvePath(profileId, p.path))) : undefined;
      const problem = facts.problems[i]?.[0] ?? '';
      const init = e.initializer?.function ? { kind: INIT_KINDS[1], value: e.initializer.function } : e.initializer?.delay ? { kind: INIT_KINDS[2], value: String(e.initializer.delay.ms) } : { kind: INIT_KINDS[0], value: '' };
      const mod: Mod = {
        id,
        packageId: kind === 'package' ? e.id || file : file,
        name: kind === 'package' ? e.name : file,
        kind,
        enabled: e.enabled,
        folder: e.path,
        // shortcut: the engine reads no sizes, dates, versions or thumbnails per entry; shown empty until it does.
        size: '',
        addedOn: '',
        description: problem,
        tags: [
          ...(at(facts.stays_last, i) ? [{ label: 'Loads last', tone: 'vio' as const }] : []),
          ...(String(i) in (facts.shared ?? {}) ? [{ label: 'Shared', tone: 'info' as const }] : []),
          ...(at(facts.loose_dlls, i) ? [{ label: 'No folder', tone: 'warn' as const }] : []),
          ...(kind === 'native' && e.load_early ? [{ label: 'Loads early' }] : []),
          ...(kind === 'native' && e.optional ? [{ label: 'Optional' }] : []),
        ],
        configs: (facts.configs[i] ?? []).map(baseName),
        loadAfter: e.load_after.map((d) => ({ packageId: d.id, optional: d.optional })),
      };
      if (at(facts.missing, i)) mod.missing = true;
      if (String(i) in (facts.shared ?? {})) mod.shared = true;
      if (at(facts.stays_last, i)) mod.staysLast = true;
      // The package that stays last is the profile's overhaul: the sheet and Remove address it as the profile's own.
      if (kind === 'package' && facts.overhaul && at(facts.stays_last, i)) mod.setupId = 'overhaul';
      if (kind === 'native') {
        mod.file = file;
        mod.nameSource = 'file';
        if (owner) { mod.partOfModId = modIdOf(profileId, owner); mod.nameSource = 'install'; }
        mod.native = { loadEarly: !!e.load_early, optional: !!e.optional, initializer: init, finalizer: e.finalizer ?? '' };
      }
      out.push(mod);
    }
  }
  return out;
}

/* ------------------------------------------------------------------ the id → index map */

interface Row { index: number; name: string; kind: ModKind; path: string }
const seen = new Map<string, Map<ModId, Row>>();
/** Forget what was read: the profile changed (a stale refusal, or a write that moves indexes). */
export const forget = (profileId: string) => { seen.delete(profileId); };

/** Read the profile's page (one engine pass) and remember each mod's index. */
export async function readFacts(gateway: Gateway, profileId: string): Promise<EnginePageFacts> {
  const page = await gateway.call<EngineModsPage>(OP.mods, { profile: profileId });
  if (!page.has_profile || !page.facts) throw new GatewayError({ code: 'not_found', message: 'That profile is not there.' });
  if (page.facts.error) throw new GatewayError({ code: 'unreadable', message: page.facts.error });
  const map = new Map<ModId, Row>();
  for (const e of page.facts.entries) if (!page.facts.loads_nothing.includes(e.index)) map.set(modIdOf(profileId, e), { index: e.index, name: e.name, kind: e.kind, path: e.path });
  seen.set(profileId, map);
  return page.overhaul ? { ...page.facts, overhaul: page.overhaul } : page.facts;
}

/** The UI's Mod list for a profile (getProfile's `mods`). */
export async function readMods(gateway: Gateway, profileId: string): Promise<Mod[]> {
  return toMods(profileId, await readFacts(gateway, profileId));
}

/** The engine row a mod id stands for: from the last read, else a fresh one. The engine checks its name (`expect`). */
export async function rowOf(gateway: Gateway, profileId: string, modId: ModId): Promise<Row> {
  let row = seen.get(profileId)?.get(modId);
  if (!row) {
    await readMods(gateway, profileId);
    row = seen.get(profileId)?.get(modId);
  }
  if (!row) throw new GatewayError({ code: 'not_found', message: 'That mod is no longer in the profile.' });
  return row;
}

/** Run a call that addresses entries by index: a refused index (stale, not_found) drops the remembered map. */
export async function guarded<T>(profileId: string, fn: () => Promise<T>): Promise<T> {
  try { return await fn(); } catch (e) {
    if (e instanceof GatewayError && (e.code === 'stale' || e.code === 'not_found')) forget(profileId);
    throw e;
  }
}

/* ------------------------------------------------------------------ sentences for the engine's codes */

const NOT_READY: Record<string, string> = {
  plan_error: "Bayle can't install this download.",
  name_blank: 'Give the mod a name.',
  overhaul_refused: "This download can't be set up as an overhaul.",
  name_problem: 'Pick another folder name for this mod.',
  library_blocked: "A shared copy of this mod can't be updated from here. Install it as a separate copy.",
  id_blank: 'The mod needs an id.',
  id_taken: 'Another mod in this profile already uses that id.',
  nothing_loaded: 'Nothing the game loads is ticked.',
};

/** The engine words nothing (routers/mods.py), so codes whose message is not a sentence for the player get one here. */
export function said(e: unknown): unknown {
  if (!(e instanceof GatewayError)) return e;
  const d = e.details ?? {};
  const as = (message: string) => new GatewayError({ code: e.code, message, details: e.details });
  switch (e.code) {
    case 'not_ready': return as(NOT_READY[String(d.reason)] ?? e.message);
    case 'already_listed': return as(`${String(d.name ?? 'That mod')} is already in this profile.`);
    case 'unknown_install': return as('The download was closed. Read it again.');
    case 'rebuild_game_running': return as('Close the game, then rebuild.');
    case 'rebuild_blocked': case 'nothing_to_rebuild': return as(`${e.message}${d.detail ? ` ${String(d.detail)}` : ''}`);
    case 'tool_cannot_run': return as(`The rebuild tool ${String(d.tool ?? '')} cannot run: ${String(d.why ?? 'see Activity')}.`);
    case 'needs_confirmation': return d.reason === 'allow_tool' ? as(`Rebuilding runs ${String((d.tool as { label?: string } | undefined)?.label ?? 'a tool')} that came with a mod, and Bayle has not been allowed to run it yet.`) : e;
    default: return e;
  }
}

/* ------------------------------------------------------------------ jobs */

/**
 * Start a job and wait for it. The ActionResult's entry is the job's Activity entry; it is undoable when the engine
 * kept an undo record for it (the job's own, or the one a result carries).
 */
export async function runJob(gateway: Gateway, operation: string, params: Record<string, unknown>, kind: ActivityKind): Promise<{ result: unknown; entry: ActivityEntry }> {
  const epoch = gateway.current()?.epoch;
  if (epoch === undefined) throw new GatewayError({ code: 'engine_unavailable', message: "Bayle's engine isn't ready." });
  const { job_id } = await gateway.call<{ job_id: string }>(operation, params, { epoch }).catch((e) => { throw said(e); });
  const job = await awaitJob({ epoch, id: job_id });
  const now = new Date();
  const result = job.result as { undo?: unknown } | undefined;
  const entry: ActivityEntry = {
    id: job.id, gameId: '', kind, ok: true, title: job.title, detail: '', day: 'Today',
    time: now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false }),
    duration: '', hasLog: true, undoable: !!job.undo || !!result?.undo,
  };
  return { result: job.result, entry };
}
