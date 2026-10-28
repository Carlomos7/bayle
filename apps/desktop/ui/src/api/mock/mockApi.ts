/**
 * In-memory backend for development and demos. Behaves like the real one:
 * async, slight latency, every change goes to Activity with a working Undo,
 * long operations run as jobs on the mock engine (progress, Stop). Selected
 * in src/api/index.ts, never inside the desktop app.
 */
import type { BayleApi } from '../BayleApi';
import type { MockEngine } from '../gateway/mock';
import type {
  ActionResult, ActivityEntry, ActivityKind, AppInfo, AppStatus, BackendEvent, BuildChange, BuildReport, Clash, ConfigFile, Rule, ManifestDifference, ModSurvival, OrderSuggestion, SuggestedChange, Suggestion, PieceHit, SetupManifest, ConfigFileRef, GameId, Mod,
  OverhaulSetup, Profile, ProfileId, Settings, Slot,
} from '../types';
import * as seed from './seed';

const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const latency = () => wait(60 + Math.random() * 140);
const clone = <T,>(v: T): T => structuredClone(v);
const now = () => { const d = new Date(); return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; };

export function createMockApi(engine?: MockEngine): BayleApi {
  const db = {
    games: clone(seed.games),
    profiles: clone(seed.profiles),
    saves: clone(seed.saves),
    copies: clone(seed.copies),
    configs: clone(seed.configFiles),
    setups: clone(seed.setups),
    builds: clone(seed.builds),
    activity: clone(seed.activity),
    settings: clone(seed.initialSettings),
    status: { state: 'ready', text: 'Ready to launch' } as AppStatus,
    running: null as GameId | null,
  };
  /** Undo closures for entries made in this session. Seeded entries get generic ones below. */
  const reverts = new Map<string, () => void>();
  const listeners = new Set<(e: BackendEvent) => void>();
  let uid = 1000;
  let picks = 0;
  const id = (p: string) => `${p}${++uid}`;

  const emit = (e: BackendEvent) => listeners.forEach((l) => l(e));
  const setStatus = (status: AppStatus) => { db.status = status; emit({ type: 'status', status }); };
  /** A long operation: a job on the mock engine (progress, Stop), or a plain pause without one. Rejects if stopped. */
  const job = async (title: string, ms: number) => {
    if (!engine) { await wait(ms); return; }
    await engine.runJob(title, { ms, steps: [title, title.replace(/…$/, '') + ': checking', title.replace(/…$/, '') + ': writing'] }).done;
  };

  const profile = (pid: ProfileId): Profile => {
    const p = db.profiles.find((x) => x.id === pid);
    if (!p) throw new Error('That profile no longer exists.');
    return p;
  };
  const recount = (p: Profile) => { p.modCount = p.mods.length; p.enabledCount = p.mods.filter((m) => m.enabled).length; };
  const hasOverhaul = (p: Profile) => p.mods.some((m) => m.staysLast && m.enabled);
  const snapProfile = (p: Profile) => { const before = clone(p); return () => { Object.keys(p).forEach((k) => delete (p as unknown as Record<string, unknown>)[k]); Object.assign(p, before); }; };

  /** Record a change: apply it, keep its revert, add an Activity entry, return what the UI toasts. */
  function record(o: { kind: ActivityKind; gameId: GameId; title: string; detail?: string; message?: string; sub?: string; undoLabel?: string; undoLines?: string[]; revert?: () => void; noUndoReason?: string; ok?: boolean; scope: 'profiles' | 'saves' | 'settings' | 'configs' }): ActionResult {
    const entry: ActivityEntry = {
      id: id('a'), gameId: o.gameId, kind: o.kind, ok: o.ok ?? true, title: o.title, detail: o.detail ?? '', day: 'Today', time: now(), duration: 'under a second', hasLog: false,
      undoable: !!o.revert, undoLabel: o.undoLabel, undoLines: o.undoLines, noUndoReason: o.noUndoReason,
    };
    if (o.revert) reverts.set(entry.id, o.revert);
    db.activity.unshift(entry);
    emit({ type: 'changed', scope: o.scope });
    emit({ type: 'changed', scope: 'activity' });
    return { entry, message: o.message ?? o.title, detail: o.sub ?? (o.revert ? `${o.undoLabel ?? 'Undo'} in Activity.` : undefined) };
  }

  /** The build for a profile; profiles with nothing overlapping get an empty one. */
  const build = (p: Profile): BuildReport => (db.builds[p.id] ??= { profileId: p.id, state: 'none', baseline: { game: 'Elden Ring 1.16.1', exceptions: [] }, changes: [], families: [], cells: [], clashes: [], rules: [], pending: [], dropped: [], kept: [], reportLines: [] });
  /** What each profile's decisions were at its last build, so pending changes can be dropped. */
  const builtDecisions: Record<string, { rules: Rule[]; picks: Record<string, Pick<Clash, 'resolution' | 'pickedId'>> }> = {
    // The seeded Animations rule was set after yesterday's build, and replaced a single pick on the light attack.
    'er-sc': { rules: [], picks: { c2: { resolution: 'pick', pickedId: 'clevers-moveset' }, c5: { resolution: 'pick', pickedId: 'clevers-moveset' } } },
  };
  const snapshotDecisions = (p: Profile, b: BuildReport) => {
    builtDecisions[p.id] = { rules: clone(b.rules), picks: Object.fromEntries(b.clashes.map((c) => [c.id, { resolution: c.resolution, pickedId: c.pickedId }])) };
  };

  /** Everything a mod changes against the original game: every piece in the build's cells, clashes included. */
  const footprint = (b: BuildReport, id: string) => b.cells.filter((c) => c.modId === id).reduce((n, c) => n + c.count, 0);
  /** How much of each overlapping mod gets in: its pieces, minus clashes it loses now, minus what was left out. */
  const survivalOf = (p: Profile, b: BuildReport): ModSurvival[] => {
    const ids = [...new Set(b.cells.map((c) => c.modId))].filter((id) => p.mods.some((m) => m.id === id));
    return ids.map((id) => {
      const lost = b.clashes.filter((c) => c.reason !== 'both' && c.sides.some((x) => x.modId === id) && c.winnerId !== id).map((c) => ({ clashId: c.id, piece: c.piece, toId: c.winnerId }));
      const dropped = b.cells.filter((c) => c.modId === id && c.outcome === 'dropped').reduce((n, c) => n + c.count, 0);
      const total = footprint(b, id);
      return { modId: id, total, kept: Math.max(0, total - lost.length - dropped), lost, dropped };
    });
  };

  /**
   * Who wins each clash and why: a pick, then a kind rule, then a rule it is coupled to, then load order.
   * Also marks rules dormant when one of their mods is off or gone, and lists what a rebuild would change.
   */
  const settle = (p: Profile, b: BuildReport) => {
    const on = (id: string) => p.mods.some((m) => m.id === id && m.enabled && !m.missing);
    const pos = (id: string) => p.mods.findIndex((m) => m.id === id);
    b.rules.forEach((r) => { r.dormant = r.order.filter(on).length < 2; });
    const live = b.rules.filter((r) => !r.dormant);
    b.clashes.forEach((c) => {
      const ids = c.sides.map((x) => x.modId);
      const firstOf = (order: string[]) => order.find((id) => ids.includes(id) && on(id));
      const rule = live.find((r) => r.family === c.family);
      const coupled = live.find((r) => r.coupled?.includes(c.family));
      if (c.resolution === 'both') { c.winnerId = undefined; c.reason = 'both'; }
      else if (c.resolution === 'pick' && c.pickedId && ids.includes(c.pickedId)) { c.winnerId = c.pickedId; c.reason = 'pick'; }
      else if (rule && firstOf(rule.order)) { c.winnerId = firstOf(rule.order); c.reason = 'rule'; }
      else if (coupled && firstOf(coupled.order)) { c.winnerId = firstOf(coupled.order); c.reason = 'coupled'; }
      else { c.winnerId = [...ids].sort((x, y) => pos(x) - pos(y)).pop(); c.reason = 'order'; }
    });
    b.pending = b.clashes.filter((c) => c.winnerId !== c.builtWinnerId).map((c) => ({ clashId: c.id, piece: c.piece, fromId: c.builtWinnerId, toId: c.winnerId }));
    const d = builtDecisions[p.id];
    const ruleKey = (r: Rule) => `${r.family}:${r.order.join()}:${(r.coupled ?? []).join()}`;
    const builtRules = new Set((d?.rules ?? []).map(ruleKey));
    const nowRules = new Set(b.rules.map(ruleKey));
    b.choicesSinceBuild = d ? [...nowRules].filter((k) => !builtRules.has(k)).length + [...builtRules].filter((k) => !nowRules.has(k)).length
      + b.clashes.filter((c) => { const x = d.picks[c.id] ?? { resolution: 'order' }; return x.resolution !== c.resolution || x.pickedId !== c.pickedId; }).length : 0;
    b.survival = survivalOf(p, b);
    return b;
  };

  /** Mark a build stale with a reason, if the profile has one. */
  const stale = (p: Profile, change: BuildChange) => {
    const b = build(p); if (b.state === 'none') return;
    b.state = 'stale'; b.changes.push(change); p.merge = 'needs';
    b.clashes.forEach((c) => { if (c.resolution !== 'order') c.needsReview = true; });
  };
  const markMerge = (p: Profile, mods: Mod[], change?: BuildChange) => { if (hasOverhaul(p) && mods.some((m) => m.kind === 'package' && !m.staysLast)) stale(p, change ?? { kind: 'toggled', title: 'Mods changed' }); };

  const api: BayleApi = {
    async getAppInfo(): Promise<AppInfo> { await latency(); return { version: '3.14.1', me3Version: '0.9.2', me3Latest: '0.9.3', update: { version: '3.15.0', channel: 'beta' }, platform: 'Windows 11 · Qt 6.11', dataFolder: '%LOCALAPPDATA%\\Carlomos7.Bayle' }; },
    async getStatus() { return clone(db.status); },
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },

    async getGames() { await latency(); return clone(db.games); },
    async setActiveProfile(gameId, profileId) { await latency(); const g = db.games.find((x) => x.id === gameId); if (g) g.activeProfileId = profileId; emit({ type: 'changed', scope: 'profiles' }); },
    async listProfiles(gameId) { await latency(); return db.profiles.filter((p) => p.gameId === gameId).map(({ id: pid, gameId: gid, name, modCount, enabledCount }) => ({ id: pid, gameId: gid, name, modCount, enabledCount })); },
    async getProfile(pid) { await latency(); return clone(profile(pid)); },
    async createProfile(gameId, name, copyFrom) {
      await latency();
      if (db.profiles.some((p) => p.gameId === gameId && p.name === name)) throw new Error(`There is already a profile called ${name}.`);
      const src = copyFrom ? profile(copyFrom) : null;
      const p: Profile = { id: id('p'), gameId, name, merge: 'none', onlineAccepted: false, mods: src ? clone(src.mods) : [], modCount: 0, enabledCount: 0, saveId: src?.saveId };
      recount(p); db.profiles.push(p);
      return { ...record({ kind: 'profile', gameId, title: `Created profile ${name}`, detail: src ? `copied from ${src.name}` : 'empty', scope: 'profiles', revert: () => { db.profiles = db.profiles.filter((x) => x !== p); }, undoLines: [`${name} is deleted again`] }), profileId: p.id };
    },
    async renameProfile(pid, name) {
      await latency(); const p = profile(pid); const old = p.name; p.name = name;
      return record({ kind: 'profile', gameId: p.gameId, title: `Renamed profile ${old} to ${name}`, scope: 'profiles', undoLabel: 'Undo rename', revert: () => { p.name = old; }, undoLines: [`The profile is called ${old} again`] });
    },
    async deleteProfile(pid) {
      await latency(); const p = profile(pid); const i = db.profiles.indexOf(p); db.profiles.splice(i, 1);
      return record({ kind: 'profile', gameId: p.gameId, title: `Deleted profile ${p.name}`, scope: 'profiles', undoLabel: 'Restore', revert: () => { db.profiles.splice(i, 0, p); }, undoLines: [`${p.name} comes back with its mods`] });
    },
    async moveProfileIn(pid) {
      await job('Moving the profile in…', 900);
      const p = profile(pid); const was = p.outsidePath; p.outsidePath = undefined;
      return record({ kind: 'profile', gameId: p.gameId, title: `Moved ${p.name} into Bayle's folder`, detail: `from ${was}`, scope: 'profiles', revert: () => { p.outsidePath = was; }, undoLines: [`Everything moves back to ${was}`] });
    },
    async takeOverInstaller(pid) {
      await job('Taking over the installer setup…', 1200);
      const p = profile(pid); const revert = snapProfile(p);
      const ins = p.installer; p.installer = undefined;
      p.mods.forEach((m) => { if (m.installerMade) { m.installerMade = false; m.tags = m.tags.filter((t) => t.label !== 'Installer-made'); } });
      return record({ kind: 'install', gameId: p.gameId, title: `Took over ${ins?.name ?? 'the installer setup'}`, detail: p.name, scope: 'profiles', revert, undoLabel: 'Put it back', undoLines: ["The installer's changes come back exactly as they were"] });
    },

    async setModsEnabled(pid, modIds, enabled) {
      await latency(); const p = profile(pid); const revert = snapProfile(p);
      const todo = p.mods.filter((m) => modIds.includes(m.id) && !m.missing && m.enabled !== enabled);
      if (!todo.length) throw new Error(enabled ? 'Nothing to turn on.' : 'Nothing to turn off.');
      todo.forEach((m) => { m.enabled = enabled; }); recount(p);
      const one = todo.length === 1 ? todo[0]!.name : `${todo.length} mods`;
      markMerge(p, todo, { kind: 'toggled', title: `You turned ${enabled ? 'on' : 'off'} ${one}`, detail: enabled ? 'Its files join the merge.' : 'Its files leave the merge.' });
      return record({ kind: 'profile', gameId: p.gameId, title: `${enabled ? 'Turned on' : 'Turned off'} ${one}`, detail: p.name, message: `${one} ${todo.length === 1 ? 'is' : 'are'} ${enabled ? 'on' : 'off'}`, scope: 'profiles', revert, undoLines: todo.map((m) => `${m.name} is turned ${enabled ? 'off' : 'on'} again`) });
    },
    async reorderMods(pid, kind, orderedIds) {
      await latency(); const p = profile(pid); const revert = snapProfile(p);
      const ofKind = p.mods.filter((m) => m.kind === kind);
      let next = orderedIds.map((mid) => ofKind.find((m) => m.id === mid)).filter((m): m is Mod => !!m);
      const last = next.filter((m) => m.staysLast); next = [...next.filter((m) => !m.staysLast), ...last];
      p.mods = kind === 'package' ? [...next, ...p.mods.filter((m) => m.kind !== 'package')] : [...p.mods.filter((m) => m.kind !== 'native'), ...next];
      if (kind === 'package') markMerge(p, next, { kind: 'reordered', title: 'You changed the load order', detail: 'Order decides who wins a clash.' });
      return record({ kind: 'profile', gameId: p.gameId, title: 'Changed the load order', detail: p.name, message: 'Load order changed', scope: 'profiles', revert, undoLines: ['The load order goes back to what it was'] });
    },
    async removeMods(pid, modIds, opts) {
      await latency(); const p = profile(pid); const revert = snapProfile(p);
      const gone = p.mods.filter((m) => modIds.includes(m.id)); p.mods = p.mods.filter((m) => !modIds.includes(m.id));
      if (hasOverhaul(p) && gone.some((m) => m.kind === 'package') && !opts?.rebuild) stale(p, { kind: 'removed', title: `You removed ${gone.map((m) => m.name).join(', ')}`, detail: 'Its changes leave the merge.' });
      recount(p);
      const one = gone.length === 1 ? gone[0]!.name : `${gone.length} mods`;
      return record({ kind: 'profile', gameId: p.gameId, title: `Removed ${one}`, detail: p.name, scope: 'profiles', undoLabel: 'Restore', sub: 'Folders are in the Recycle Bin. Restore in Activity.', revert, undoLines: gone.map((m) => `${m.name} goes back where it was in the load order`) });
    },
    async addModsToProfile(targetId, fromId, modIds) {
      await latency(); const to = profile(targetId); const from = profile(fromId); const revert = snapProfile(to);
      const add = from.mods.filter((m) => modIds.includes(m.id) && !to.mods.some((x) => x.id === m.id)).map(clone);
      if (!add.length) throw new Error(`${to.name} already has them.`);
      const pk = add.filter((m) => m.kind === 'package'); const na = add.filter((m) => m.kind === 'native');
      const lastIdx = to.mods.findIndex((m) => m.kind === 'package' && m.staysLast); const firstNat = to.mods.findIndex((m) => m.kind === 'native');
      to.mods.splice(lastIdx >= 0 ? lastIdx : firstNat >= 0 ? firstNat : to.mods.length, 0, ...pk); to.mods.push(...na); recount(to);
      return record({ kind: 'profile', gameId: to.gameId, title: `Added ${add.length} mod${add.length === 1 ? '' : 's'} to ${to.name}`, detail: add.map((m) => m.name).join(', '), sub: 'Shared, not copied: both profiles use the same folders.', scope: 'profiles', revert, undoLines: [`${add.map((m) => m.name).join(', ')} leave ${to.name}`] });
    },
    async upgradeMod(pid, modId) {
      const p = profile(pid); const m = p.mods.find((x) => x.id === modId); if (!m?.update) throw new Error('That mod has no newer release.');
      await job(`Updating ${m.name} to ${m.update.version}…`, 1200);
      const revert = snapProfile(p); const b = build(p); const before = clone(b);
      const u = m.update; const was = m.version; m.version = u.version; m.update = undefined;
      b.clashes.forEach((c) => { if (c.sides.some((s) => s.modId === modId) && c.resolution !== 'order') c.needsReview = true; });
      stale(p, { kind: 'mod-updated', title: `${m.name} updated ${was} → ${u.version}`, detail: `${u.changes.map((c) => `${c.count} ${c.unit}`).join(', ')} differ.` });
      return record({ kind: 'install', gameId: p.gameId, title: `Updated ${m.name} to ${u.version}`, detail: p.name, message: `${m.name} is now ${u.version}`, sub: 'Your settings and picks are kept. The merge is rebuilt at launch.', scope: 'profiles', revert: () => { revert(); db.builds[p.id] = before; }, undoLines: [`${m.name} goes back to ${was}`] });
    },
    async updateMod(pid, modId, patch) {
      await latency(); const p = profile(pid); const revert = snapProfile(p); const m = p.mods.find((x) => x.id === modId);
      if (!m) throw new Error('That mod is no longer in the profile.');
      Object.assign(m, clone(patch));
      if (patch.name && m.kind === 'native') m.nameSource = 'you';
      if ('staysLast' in patch) { m.tags = m.tags.filter((t) => t.label !== 'Stays last'); }
      if (m.kind === 'package') markMerge(p, [m]); recount(p);
      const what = patch.name ? `Renamed to ${patch.name}` : `${m.name}: options saved`;
      return record({ kind: 'profile', gameId: p.gameId, title: patch.name ? `Renamed a mod to ${patch.name}` : `Changed the options of ${m.name}`, detail: p.name, message: what, sub: 'They apply at the next launch. Undo in Activity.', scope: 'profiles', revert, undoLines: [`${m.name}'s options go back to what they were`] });
    },
    async listModFiles(pid, modId) { await latency(); const m = profile(pid).mods.find((x) => x.id === modId); return m ? seed.modFiles(m) : []; },
    async attachConfig(pid, modId, names) {
      await latency(); const p = profile(pid); const m = p.mods.find((x) => x.id === modId); if (!m) throw new Error('That mod is no longer in the profile.');
      const before = [...m.configs]; m.configs.push(...names.filter((n) => !m.configs.includes(n)));
      return record({ kind: 'profile', gameId: p.gameId, title: `Attached ${names.join(', ')} to ${m.name}`, message: names.length > 1 ? `${names.length} files attached to ${m.name}` : `${names[0]} attached to ${m.name}`, sub: 'Edit it on Mod Configs. Undo in Activity.', scope: 'configs', revert: () => { m.configs = before; }, undoLines: [`${names.join(', ')} detached again`] });
    },
    async detachConfig(pid, modId, name) {
      await latency(); const p = profile(pid); const m = p.mods.find((x) => x.id === modId); if (!m) throw new Error('That mod is no longer in the profile.');
      const before = [...m.configs]; m.configs = m.configs.filter((c) => c !== name);
      return record({ kind: 'profile', gameId: p.gameId, title: `Detached ${name} from ${m.name}`, message: `${name} detached`, sub: 'The file stays where it is. Undo in Activity.', scope: 'configs', revert: () => { m.configs = before; }, undoLines: [`${name} is attached to ${m.name} again`] });
    },
    async listAttachableConfigs(pid, modId) {
      await latency(); const m = profile(pid).mods.find((x) => x.id === modId); if (!m) return [];
      return seed.modFiles(m).map((f) => f.path.split('\\').pop() ?? f.path).filter((n) => /\.(ini|toml|json|txt|cfg)$/i.test(n) && !m.configs.includes(n) && !/\.log$/i.test(n));
    },
    async previewInstall(source) {
      await wait(500); const name = source.path.split(/[\\/]/).pop()?.replace(/\.(zip|7z|rar)$/i, '') ?? 'New mod'; const isDll = /\.dll$/i.test(source.path);
      const overhaul = Object.values(db.setups).find((x) => name.toLowerCase().includes(x.id));
      if (overhaul) return { source: source.path, detectedAs: 'overhaul' as const, name: overhaul.name, version: overhaul.version, setupId: overhaul.id, items: [{ path: overhaul.gameDir, what: `${overhaul.files.length} game files`, include: true, size: '640 MB' }, ...overhaul.dlls.map((d) => ({ path: d.name, what: 'its native', include: true, size: '4 MB' }))], warnings: overhaul.ownInstaller ? [`It comes with its own installer (${overhaul.ownInstaller}). Bayle sets it up instead, so it can be updated and undone.`] : [] };
      return { source: source.path, detectedAs: isDll ? 'native' : 'package', name: name.replace(/[-_.]\d.*$/, ''), version: name.match(/\d+(\.\d+)+/)?.[0],
        items: isDll ? [{ path: name, what: 'the native me3 injects', include: true, size: '2 MB' }] : [{ path: 'regulation.bin', what: "the game's rules", include: true, size: '4 MB' }, { path: 'msg\\engus\\item.msgbnd.dcx', what: 'item text', include: true, size: '1 MB' }, { path: 'README.txt', what: 'readme', include: false, size: '2 KB' }],
        warnings: [] };
    },
    async install(pid, preview) {
      await job(`Installing ${preview.name}…`, 1100);
      const p = profile(pid); const revert = snapProfile(p);
      const isDll = preview.detectedAs === 'native'; const dllName = preview.source.split(/[\\/]/).pop();
      const m: Mod = { id: id('m'), packageId: preview.name.toLowerCase().replace(/[^a-z0-9]+/g, '-'), name: isDll ? dllName ?? preview.name : preview.name, ...(isDll ? { file: dllName, nameSource: 'file' as const } : {}), kind: isDll ? 'native' : 'package', enabled: true, version: preview.version, folder: `mods/${preview.name.replace(/\s+/g, '')}`, size: '5 MB', addedOn: 'today', description: `Installed from ${preview.source.split(/[\\/]/).pop()}`, tags: [], configs: [], loadAfter: [], ...(preview.detectedAs === 'native' ? { native: { loadEarly: false, optional: false, initializer: { kind: 'none', value: '' }, finalizer: '' } } : {}) };
      if (m.kind === 'package') { const last = p.mods.findIndex((x) => x.kind === 'package' && x.staysLast); const firstNat = p.mods.findIndex((x) => x.kind === 'native'); p.mods.splice(last >= 0 ? last : firstNat >= 0 ? firstNat : p.mods.length, 0, m); markMerge(p, [m]); }
      else p.mods.push(m);
      recount(p);
      return record({ kind: 'install', gameId: p.gameId, title: `Installed ${m.name}`, detail: `from ${preview.source.split(/[\\/]/).pop()} · ${p.name}`, message: `${m.name} is installed`, scope: 'profiles', undoLabel: 'Undo install', revert, undoLines: [`${m.name} leaves ${p.name}`, 'The files the install added are removed'] });
    },
    async rebuildMerged(pid) {
      const p = profile(pid); if (!hasOverhaul(p)) throw new Error('Nothing in this profile overlaps, so there is nothing to rebuild.');
      await job('Rebuilding merged game data…', 1600);
      const was = p.merge; const b = build(p); const before = clone(b);
      settle(p, b);
      p.merge = 'ok'; b.state = 'ready'; b.changes = []; b.builtOn = `today, ${now()}`; b.durationSec = 38;
      b.clashes.forEach((c) => { c.needsReview = false; c.builtWinnerId = c.winnerId; });
      b.rules.forEach((r) => { r.meetsNew = 0; r.metIds = undefined; }); b.pending = [];
      snapshotDecisions(p, b);
      b.reportLines = b.reportLines.map((l, i) => (i === 0 ? l.replace(/built .*$/, `built today ${now()} in 38 s`) : l.replace(' (now 1.16.1: stale)', '').replace('1.16.0', '1.16.1')));
      const n = b.clashes.length;
      return record({ kind: 'rebuild', gameId: p.gameId, title: 'Rebuilt merged game data', detail: `${p.name} · ${n ? `${n} clash${n === 1 ? '' : 'es'}, all settled` : 'no clashes'}${b.dropped.length ? ` · ${b.dropped.length} change${b.dropped.length === 1 ? '' : 's'} dropped` : ''}`, message: 'Merged game data rebuilt', sub: n || b.dropped.length ? 'See Merge for what was kept and what was not.' : undefined, scope: 'profiles', revert: () => { p.merge = was; db.builds[p.id] = before; }, undoLines: ['The previous merged game data is put back'] });
    },

    async getBuild(pid) { await latency(); const p = profile(pid); return clone(settle(p, build(p))); },
    async setRule(pid, family, order, coupled) {
      await latency(); const p = profile(pid); const b = build(p); const before = clone(b);
      const name = (id: string) => p.mods.find((m) => m.id === id)?.name ?? id;
      const fam = { params: 'Balance', text: 'Text', animations: 'Animations', behaviour: 'Behaviour', scripts: 'Scripts', textures: 'Textures', other: 'Other' }[family];
      b.rules = b.rules.filter((r) => r.family !== family);
      if (order) b.rules.push({ id: id('r'), family, order, coupled: coupled?.length ? coupled : undefined });
      // A kind with its own rule cannot also follow another rule's coupling.
      if (order) b.rules.forEach((r) => { if (r.coupled) r.coupled = r.coupled.filter((f) => f !== family); });
      // Single picks in this kind give way to the new rule, as the rule is the newer, broader choice.
      b.clashes.forEach((c) => { if (c.family === family && c.resolution === 'pick') { c.resolution = 'order'; c.pickedId = undefined; } c.needsReview = c.family === family ? false : c.needsReview; });
      settle(p, b);
      if (b.state !== 'none' && b.pending.length) { b.state = 'stale'; p.merge = 'needs'; }
      const what = order ? `${fam}: ${order.map(name).join(', then ')}${coupled?.length ? ` (with ${coupled.map((f) => f).join(', ')})` : ''}` : `${fam}: back to load order`;
      return record({ kind: 'rebuild', gameId: p.gameId, title: `Set a rule. ${what}`, detail: p.name, message: what, sub: '', scope: 'profiles', revert: () => { db.builds[p.id] = before; }, undoLines: ['The rule goes back to how it was'] });
    },
    async confirmRule(pid, ruleId) { await latency(); const b = build(profile(pid)); const r = b.rules.find((x) => x.id === ruleId); if (r) { r.meetsNew = 0; r.metIds = undefined; } emit({ type: 'changed', scope: 'profiles' }); },
    async acceptDropped(pid, droppedId) {
      await latency(); const p = profile(pid); const d = build(p).dropped.find((x) => x.id === droppedId);
      if (!d) throw new Error('That change is no longer left out.');
      d.accepted = true;
      const mod = p.mods.find((m) => m.id === d.modId)?.name ?? d.modId;
      return record({ kind: 'rebuild', gameId: p.gameId, title: `Playing without ${mod}'s ${d.what.replace(/ \(.*\)$/, '')}`, detail: p.name, message: 'OK, playing without it', sub: '', scope: 'profiles', revert: () => { d.accepted = false; }, undoLines: ['It asks again on Merge'] });
    },
    async discardPending(pid) {
      await latency(); const p = profile(pid); const b = build(p); const before = clone(b);
      const d = builtDecisions[p.id];
      if (d) { b.rules = clone(d.rules); b.clashes.forEach((c) => { const x = d.picks[c.id]; if (x) { c.resolution = x.resolution; c.pickedId = x.pickedId; } }); }
      settle(p, b);
      const n = before.pending.length;
      return record({ kind: 'rebuild', gameId: p.gameId, title: 'Dropped choices not built yet', detail: p.name, message: `${n} change${n === 1 ? '' : 's'} dropped`, sub: 'Rules and picks are back to the last build.', scope: 'profiles', revert: () => { db.builds[p.id] = before; }, undoLines: ['The dropped rules and picks come back'] });
    },
    async previewBuild(pid) {
      await wait(400); const p = profile(pid); const b = settle(p, build(p));
      const pk = p.mods.filter((m) => m.kind === 'package' && m.enabled && !m.missing);
      const ovh = pk.find((m) => m.staysLast);
      return {
        estimateSec: b.durationSec ?? 40,
        steps: [
          { title: `Read ${pk.length} packages in load order`, detail: pk.map((m) => m.name).join(' → ') },
          { title: `Compare each shared file with the game's original (${b.baseline.game})`, detail: `${b.families.length} kinds of file overlap.${b.baseline.exceptions.length ? ` ${b.baseline.exceptions.map((e) => p.mods.find((m) => m.id === e.modId)?.name).join(', ')}: base not stated, compared against vanilla anyway.` : ''}` },
          { title: `Merge ${b.kept.map((k) => `${k.count.toLocaleString()} ${k.unit}`).join(', ')}` },
          { title: `Settle ${b.clashes.length} clashes`, detail: `${b.clashes.filter((c) => c.reason === 'order').length} by load order, ${b.clashes.filter((c) => c.reason === 'rule' || c.reason === 'coupled').length} by your rules, ${b.clashes.filter((c) => c.reason === 'pick' || c.reason === 'both').length} by single picks. ${b.clashes.filter((c) => c.unsupported).length} whole file: one copy used, compatibility unknown.` },
          ...(b.pending.length ? [{ title: `Change the winner of ${b.pending.length} piece${b.pending.length === 1 ? '' : 's'}`, detail: b.pending.map((x) => x.piece).join('; ') }] : []),
          ...(b.dropped.length ? [{ title: `Leave out ${b.dropped.length} change${b.dropped.length === 1 ? '' : 's'} that cannot be merged`, detail: b.dropped.map((d) => `${p.mods.find((m) => m.id === d.modId)?.name}: ${d.what}`).join('; ') }] : []),
          { title: ovh ? `Write the result into ${ovh.folder}` : 'Write the combined package', detail: 'Built beside the old one, checked, then swapped in. The old build is kept for Undo.' },
          { title: 'Update the profile', detail: 'The .me3 file keeps your comments; only the merged entries change.' },
        ],
      };
    },
    async resolveClash(pid, clashId, resolution, pickedId) {
      await latency(); const p = profile(pid); const b = build(p); const c = b.clashes.find((x) => x.id === clashId);
      if (!c) throw new Error('That clash is no longer there. The build may have changed.');
      if (resolution === 'both' && !c.canKeepBoth) throw new Error('Only rows or lines that both mods added can be kept side by side.');
      if (resolution === 'both' && c.unsupported) throw new Error('This kind of file cannot be merged.');
      const before = { ...c }; const wasState = b.state; const wasChanges = clone(b.changes);
      c.resolution = resolution; c.pickedId = resolution === 'pick' ? pickedId : undefined; c.needsReview = false; c.unresolved = false;
      settle(p, b);
      const name = (mid?: string) => p.mods.find((m) => m.id === mid)?.name ?? mid ?? '';
      const how = resolution === 'both' ? 'both are kept' : resolution === 'pick' ? `${name(pickedId)} wins` : `${name(c.winnerId)} wins, ${c.reason === 'rule' || c.reason === 'coupled' ? 'by your rule' : 'as it loads later'}`;
      if (b.state === 'ready' && b.pending.length) { b.state = 'stale'; p.merge = 'needs'; b.changes.push({ kind: 'pick-changed', title: `You settled ${c.piece}`, detail: how }); }
      return record({ kind: 'rebuild', gameId: p.gameId, title: `Settled a clash: ${c.piece}`, detail: `${p.name} · ${how}`, message: `${c.piece.split(' · ').slice(-1)[0]}: ${how}`, sub: '', scope: 'profiles', revert: () => { Object.assign(c, before); b.state = wasState; b.changes = wasChanges; p.merge = wasState === 'ready' ? 'ok' : p.merge; settle(p, b); }, undoLines: ['The clash goes back to how it was settled before'] });
    },

    async searchPieces(pid, query) {
      await wait(120); const p = profile(pid); const b = settle(p, build(p)); const q = query.trim().toLowerCase();
      if (!q) return [];
      const name = (id: string) => p.mods.find((m) => m.id === id)?.name ?? id;
      const hits: PieceHit[] = b.clashes.map((c) => {
        const winnerId = c.winnerId ?? c.sides[c.sides.length - 1]!.modId;
        const win = c.sides.find((s) => s.modId === winnerId) ?? c.sides[c.sides.length - 1]!;
        return { family: c.family, file: c.file, piece: c.piece, changedBy: c.sides.map((s) => s.modId), value: c.resolution === 'both' ? c.sides.map((s) => `${s.value} (${name(s.modId)})`).join(' and ') : win.value, winnerId, clashId: c.id };
      });
      // A few pieces only one mod touches, so the search is useful beyond clashes.
      const solo: PieceHit[] = seed.soloPieces.filter((x) => p.mods.some((m) => m.id === x.winnerId && m.enabled));
      return [...hits, ...solo].filter((h) => `${h.piece} ${h.file} ${h.value}`.toLowerCase().includes(q)).slice(0, 30);
    },
    async suggestOrder(pid): Promise<OrderSuggestion> {
      await wait(500); const p = profile(pid); const b = settle(p, build(p));
      const on = (id?: string) => p.mods.some((m) => m.id === id && m.enabled && !m.missing);
      const name = (id?: string) => p.mods.find((m) => m.id === id)?.name ?? id ?? '';
      const foot = (id: string) => footprint(b, id);
      const n = (x: number) => x.toLocaleString('en-US');
      const fam = (f: string) => ({ params: 'Balance', text: 'Text', animations: 'Animations', behaviour: 'Behaviour', scripts: 'Scripts', textures: 'Textures', other: 'Other' } as Record<string, string>)[f] ?? f;
      const effectOf = (ch: SuggestedChange[]) => {
        const e = new Map<string, number>();
        ch.forEach((c) => { if (c.toId) e.set(c.toId, (e.get(c.toId) ?? 0) + 1); if (c.fromId) e.set(c.fromId, (e.get(c.fromId) ?? 0) - 1); });
        return [...e].map(([modId, delta]) => ({ modId, delta }));
      };
      const suggestions: Suggestion[] = [];
      const leftAlone: string[] = [];
      // Only clashes that load order decides are open to a suggestion. Picks, rules and decisions Bayle won't make are left alone.
      const open = b.clashes.filter((c) => c.reason === 'order' && !c.unresolved);

      // 1. Load order, where mods can move. Broad mods first, specific ones later: a mod that changes a few things exists for those
      //    things, and a big one barely notices losing them. A mod's own "load after" comes first. Stays-last mods keep their place.
      const pk = p.mods.filter((m) => m.kind === 'package');
      const movable = pk.filter((m) => !m.staysLast && on(m.id) && foot(m.id) > 0);
      const placed: Mod[] = []; const left = [...movable];
      while (left.length) {
        const ready = left.filter((m) => m.loadAfter.every((l) => !left.some((x) => x.packageId === l.packageId)));
        const next = (ready.length ? ready : left).sort((x, y) => foot(y.id) - foot(x.id))[0]!;
        placed.push(next); left.splice(left.indexOf(next), 1);
      }
      let k = 0;
      const ordered = pk.map((m) => (movable.includes(m) ? placed[k++]! : m));
      const at = (id: string) => ordered.findIndex((m) => m.id === id);
      const lastOf = (c: Clash) => c.sides.map((x) => x.modId).filter(on).sort((x, y) => at(x) - at(y)).pop();
      const orderChanges = open.filter((c) => !c.unsupported).flatMap((c) => { const w = lastOf(c); return w !== c.winnerId ? [{ clashId: c.id, piece: c.piece, fromId: c.winnerId, toId: w }] : []; });
      const moves = ordered.map((m, to) => ({ modId: m.id, from: pk.indexOf(m), to })).filter((x) => x.from !== x.to);
      if (orderChanges.length) {
        suggestions.push({ id: 'order', kind: 'order', modKind: 'package', orderedIds: ordered.map((m) => m.id), moves, title: `Move ${moves.length} mod${moves.length === 1 ? '' : 's'} in the load order`,
          reason: 'Mods that change fewer things go later, so they keep what they are for. The big ones barely notice.', changes: orderChanges, effect: effectOf(orderChanges) });
      } else if (moves.length) {
        leftAlone.push(`Reordering ${movable.map((m) => m.name).join(', ')} would change nothing: they don't share anything with each other.`);
      }

      // 2. Kind rules, where order cannot help: a specific mod losing to one that has to load last.
      const winnerNow = (c: Clash) => (orderChanges.find((x) => x.clashId === c.id)?.toId ?? c.winnerId)!;
      const byFamily = new Map<string, Clash[]>();
      open.filter((c) => !c.unsupported).forEach((c) => {
        const w = winnerNow(c);
        if (!p.mods.find((m) => m.id === w)?.staysLast) return;
        if (!c.sides.some((x) => x.modId !== w && on(x.modId) && foot(x.modId) < foot(w))) return;
        byFamily.set(c.family, [...(byFamily.get(c.family) ?? []), c]);
      });
      byFamily.forEach((cs, f) => {
        if (b.rules.some((r) => !r.dormant && r.coupled?.includes(f as Rule['family']))) return;
        const w = winnerNow(cs[0]!);
        const losers = [...new Set(cs.flatMap((c) => c.sides.map((x) => x.modId)))].filter((id) => id !== w && on(id) && foot(id) < foot(w)).sort((x, y) => foot(x) - foot(y));
        const order = [...losers, w];
        const changes = b.clashes.filter((c) => c.family === f && c.reason === 'order' && !c.unresolved && !c.unsupported).flatMap((c) => {
          const to = order.find((id) => c.sides.some((x) => x.modId === id)); return to && to !== c.winnerId ? [{ clashId: c.id, piece: c.piece, fromId: c.winnerId, toId: to }] : [];
        });
        if (!changes.length) return;
        const L = losers[0]!; const lostHere = changes.filter((c) => c.toId === L).length;
        const share = lostHere / foot(w);
        const both = cs.filter((c) => c.canKeepBoth).map((c) => c.piece);
        const coupled = f === 'animations' && b.clashes.some((c) => c.family === 'behaviour') ? ['behaviour' as const] : undefined;
        suggestions.push({
          id: `rule:${f}`, kind: 'rule', family: f as Rule['family'], order, coupled,
          title: `${fam(f)}: let ${losers.map(name).join(', ')} win over ${name(w)}`,
          reason: `${name(L)} changes ${n(foot(L))} things and loses ${lostHere} of them here. ${name(w)} changes ${n(foot(w))}, so giving ${lostHere === 1 ? 'it' : 'them'} up ${share < 0.01 ? 'barely registers' : `is ${Math.round(share * 100)}% of it`}. ${name(w)} has to load last, so only a rule can do this.${both.length ? ` For ${both.join(', ')}, keeping both is also possible on Merge (it asks first).` : ''}`,
          changes, effect: effectOf(changes),
        });
      });

      const picks = b.clashes.filter((c) => c.reason === 'pick' || c.reason === 'both').length;
      if (picks) leftAlone.push(`Your ${picks} single pick${picks === 1 ? '' : 's'} stay${picks === 1 ? 's' : ''} as ${picks === 1 ? 'it is' : 'they are'}.`);
      b.rules.filter((r) => !r.dormant).forEach((r) => leftAlone.push(`Your ${fam(r.family)} rule stays as it is.`));
      b.clashes.filter((c) => c.unresolved).forEach((c) => leftAlone.push(`${c.piece}: one mod removes what the other changes. Bayle won't pick for you; decide it on Merge.`));
      b.clashes.filter((c) => c.unsupported && c.reason === 'order').forEach((c) => leftAlone.push(`${c.file} is used whole, not merged. Bayle doesn't suggest a winner for it.`));
      return { suggestions, survival: (b.survival ?? []).filter((x) => x.lost.length || x.dropped || b.clashes.some((c) => c.sides.some((y) => y.modId === x.modId))), leftAlone };
    },

    async exportManifest(pid) {
      await latency(); const p = profile(pid); const g = db.games.find((x) => x.id === p.gameId);
      const hash = (s: string) => { let h = 0; for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return h.toString(16).padStart(8, '0') + 'a3f1'; };
      const m: SetupManifest = {
        profileName: p.name, game: `${g?.name ?? ''} ${g?.build ?? ''}`.trim(), me3Version: '0.9.2', madeOn: `today, ${now()}`,
        launch: { mode: 'Profile', online: false },
        mods: p.mods.map((x, i) => ({ name: x.name, version: x.version, kind: x.kind, enabled: x.enabled, hash: hash(x.id + (x.version ?? '')), order: i + 1 })),
        configs: p.mods.flatMap((x) => x.configs.map((c) => ({ file: c, hash: hash(c + x.id) }))),
      };
      return m;
    },
    async saveManifest(pid) { await latency(); const p = profile(pid); return `C:\\Users\\you\\Desktop\\${p.name.replace(/[^\w]+/g, '-')}.bayle-setup.json`; },
    async compareManifest(pid) {
      await wait(400); const mine = await api.exportManifest(pid);
      // The mock's "friend" is this profile with a few things off, the way it usually goes.
      const theirs: SetupManifest = clone(mine);
      theirs.profileName = 'Carlos co-op'; theirs.madeOn = 'yesterday, 21:04'; theirs.me3Version = '0.9.1';
      const conv = theirs.mods.find((m) => m.name === 'Convergence'); if (conv) { conv.version = '2.4'; conv.hash = 'c0ffee12a3f1'; }
      theirs.mods = theirs.mods.filter((m) => m.name !== 'Detailed Item Descriptions');
      const ersc = theirs.configs.find((c) => c.file === 'ersc_settings.ini'); if (ersc) ersc.hash = 'd15c0rd0a3f1';
      const differences: ManifestDifference[] = [];
      if (mine.me3Version !== theirs.me3Version) differences.push({ kind: 'loader', subject: 'me3', mine: mine.me3Version, theirs: theirs.me3Version, effect: 'Usually fine. Match it if a launch fails on one side.' });
      for (const m of mine.mods) {
        const t = theirs.mods.find((x) => x.name === m.name);
        if (!t) { differences.push({ kind: 'missing-there', subject: m.name, mine: m.version ?? 'installed', theirs: 'not installed', effect: m.kind === 'package' ? 'Game data differs between you. Co-op may desync or refuse to connect.' : 'A DLL only one of you runs. Fine for most, not for Seamless Co-op.' }); continue; }
        if (m.version !== t.version) differences.push({ kind: 'version', subject: m.name, mine: m.version ?? '', theirs: t.version ?? '', effect: 'Different game data. Both of you should be on the same version.' });
        else if (m.hash !== t.hash) differences.push({ kind: 'hash', subject: m.name, mine: 'files differ', theirs: 'files differ', effect: 'Same version, different files. One of you has an edited or partial copy.' });
        if (m.enabled !== t.enabled) differences.push({ kind: 'enabled', subject: m.name, mine: m.enabled ? 'on' : 'off', theirs: t.enabled ? 'on' : 'off', effect: 'One of you plays with it, one without.' });
      }
      for (const t of theirs.mods) if (!mine.mods.some((m) => m.name === t.name)) differences.push({ kind: 'missing-here', subject: t.name, mine: 'not installed', theirs: t.version ?? 'installed', effect: 'They have a mod you do not.' });
      for (const c of mine.configs) { const t = theirs.configs.find((x) => x.file === c.file); if (t && t.hash !== c.hash) differences.push({ kind: 'config', subject: c.file, mine: 'your settings', theirs: 'their settings', effect: c.file.startsWith('ersc') ? 'Seamless Co-op settings differ: check the password and the scaling options.' : 'Settings differ. Usually fine.' }); }
      return { theirs, differences };
    },

    async launch(gameId, pid, mode) {
      const p = profile(pid); const g = db.games.find((x) => x.id === gameId);
      if (mode !== 'Vanilla' && p.merge === 'needs' && hasOverhaul(p) && db.settings.launch.autoRebuild) { await api.rebuildMerged(pid); }
      setStatus({ state: 'busy', text: `Starting ${g?.name}…` }); await wait(900);
      db.running = gameId; setStatus({ state: 'running', text: `${g?.name} is running · leave Bayle open` });
      await wait(4000);
      db.running = null; setStatus({ state: 'ready', text: 'Ready to launch' });
      db.saves.filter((s) => s.gameId === gameId && s.health === 'repair' && mode !== 'Vanilla').forEach((s) => { s.health = 'ok'; s.slots.forEach((sl) => { delete sl.problem; }); });
      if (g) { g.lastRunBuild = g.build; g.lastPlayed = 'last played today, ' + now(); }
      db.activity.unshift({ id: id('a'), gameId, kind: 'launch', ok: true, title: `Played ${g?.name}`, detail: `${mode === 'Vanilla' ? 'vanilla, no mods' : p.name}${mode === 'Offline' ? ' · offline' : ''} · saves repaired`, day: 'Today', time: now(), duration: '6 s', hasLog: true, undoable: false, noUndoReason: 'A session cannot be undone' });
      emit({ type: 'game-closed', gameId, summary: 'Saves repaired · 1 leftover process closed' });
      emit({ type: 'changed', scope: 'activity' }); emit({ type: 'changed', scope: 'saves' }); emit({ type: 'changed', scope: 'profiles' });
    },

    async listSaves(gameId) { await latency(); return clone(db.saves.filter((s) => s.gameId === gameId)); },
    async listCopies(gameId) { await latency(); return clone(db.copies.filter((c) => c.gameId === gameId)); },
    async repairSave(saveId) {
      await job('Repairing the save…', 800);
      const s = db.saves.find((x) => x.id === saveId); if (!s) throw new Error('That save is gone.');
      const before = clone(s); s.health = 'ok'; s.slots.forEach((sl) => { delete sl.problem; });
      db.copies.unshift({ id: id('b'), gameId: s.gameId, kind: 'backup', fromFile: s.fileName, name: `Today ${now()}`, note: 'before repair', when: `Today ${now()}`, size: s.size, slots: clone(before.slots.filter((x) => x.character)) });
      return record({ kind: 'save', gameId: s.gameId, title: `Repaired ${s.fileName}`, detail: 'a backup was kept first', scope: 'saves', revert: () => Object.assign(s, before), undoLines: ['The save goes back to how it was before the repair'] });
    },
    async keepCopy(saveId, name) {
      await latency(); const s = db.saves.find((x) => x.id === saveId); if (!s) throw new Error('That save is gone.');
      const c = { id: id('c'), gameId: s.gameId, kind: 'library' as const, fromFile: s.fileName, name, note: 'whole file', when: `Today ${now()}`, slots: clone(s.slots.filter((x) => x.character)) };
      db.copies.unshift(c);
      return record({ kind: 'save', gameId: s.gameId, title: `Kept a copy of ${s.fileName}`, detail: name, message: `Copy kept: ${name}`, scope: 'saves', revert: () => { db.copies = db.copies.filter((x) => x !== c); }, undoLines: [`The copy ${name} is removed`] });
    },
    async copyCharacter(from, to) {
      await wait(400);
      const src: Slot | undefined = 'saveId' in from ? db.saves.find((s) => s.id === from.saveId)?.slots.find((x) => x.n === from.n) : db.copies.find((c) => c.id === from.copyId)?.slots.find((x) => x.n === from.n);
      const dst = db.saves.find((s) => s.id === to.saveId); const slot = dst?.slots.find((x) => x.n === to.n);
      if (!src?.character || !dst || !slot) throw new Error('That character or slot is gone.');
      const before = clone(slot); slot.character = clone(src.character); delete slot.problem; delete slot.stale;
      return record({ kind: 'save', gameId: dst.gameId, title: `Copied ${src.character.name} into ${dst.label}, slot ${to.n}`, detail: before.character ? `replaced ${before.character.name}, backed up first` : 'into an empty slot', message: `${src.character.name} copied to slot ${to.n}`, scope: 'saves', revert: () => { Object.keys(slot).forEach((k) => delete (slot as unknown as Record<string, unknown>)[k]); Object.assign(slot, before); }, undoLines: [before.character ? `${before.character.name} comes back to slot ${to.n}` : `Slot ${to.n} is empty again`] });
    },
    async deleteCharacter(saveId, n) {
      await latency(); const s = db.saves.find((x) => x.id === saveId); const slot = s?.slots.find((x) => x.n === n);
      if (!s || !slot?.character) throw new Error('That character is gone.');
      const before = clone(slot); delete slot.character; delete slot.problem; delete slot.stale;
      return record({ kind: 'save', gameId: s.gameId, title: `Deleted ${before.character?.name} from ${s.label}`, detail: 'backed up first', scope: 'saves', undoLabel: 'Restore', revert: () => Object.assign(slot, before), undoLines: [`${before.character?.name} comes back to slot ${n}`] });
    },
    async restoreCopy(copyId, saveId) {
      await job('Restoring…', 700);
      const c = db.copies.find((x) => x.id === copyId); const s = db.saves.find((x) => x.id === saveId);
      if (!c || !s) throw new Error('That copy or save is gone.'); if (c.missing) throw new Error("This copy's file is missing.");
      const before = clone(s.slots); const g = db.games.find((x) => x.id === s.gameId);
      s.slots = Array.from({ length: g?.slotsPerSave ?? 10 }, (_, i) => clone(c.slots.find((x) => x.n === i + 1) ?? { n: i + 1 }));
      return record({ kind: 'save', gameId: s.gameId, title: `Restored ${c.name} over ${s.fileName}`, detail: 'the save was backed up first', scope: 'saves', revert: () => { s.slots = before; }, undoLines: [`${s.fileName} goes back to how it was`] });
    },
    async renameCopy(copyId, name) {
      await latency(); const c = db.copies.find((x) => x.id === copyId); if (!c) throw new Error('That copy is gone.');
      const old = c.name; c.name = name;
      return record({ kind: 'save', gameId: c.gameId, title: `Renamed copy ${old} to ${name}`, scope: 'saves', revert: () => { c.name = old; }, undoLines: [`It is called ${old} again`] });
    },
    async removeCopy(copyId) {
      await latency(); const i = db.copies.findIndex((x) => x.id === copyId); const c = db.copies[i]; if (!c) throw new Error('That copy is gone.');
      db.copies.splice(i, 1);
      return record({ kind: 'save', gameId: c.gameId, title: `Removed ${c.name}`, scope: 'saves', undoLabel: 'Restore', sub: 'Its file is in the Recycle Bin.', revert: () => { db.copies.splice(i, 0, c); }, undoLines: [`${c.name} comes back`] });
    },
    async pinBackup(copyId, pinned) {
      await latency(); const c = db.copies.find((x) => x.id === copyId); if (!c) throw new Error('That backup is gone.');
      const was = c.pinned; c.pinned = pinned;
      return record({ kind: 'save', gameId: c.gameId, title: `${pinned ? 'Kept' : 'Stopped keeping'} backup ${c.name}`, message: pinned ? 'Kept forever' : 'Back in rotation', scope: 'saves', revert: () => { c.pinned = was; } });
    },
    async importSave(gameId, path) {
      await wait(500); const name = path.split(/[\\/]/).pop() ?? 'Imported save';
      const c = { id: id('c'), gameId, kind: 'library' as const, fromFile: name, name: name.replace(/\.\w+$/, ''), note: 'imported', when: `Today ${now()}`, slots: [] as Slot[] };
      db.copies.unshift(c);
      return record({ kind: 'save', gameId, title: `Imported ${name}`, detail: 'into the library', scope: 'saves', revert: () => { db.copies = db.copies.filter((x) => x !== c); }, undoLines: ['The imported copy is removed'] });
    },
    async backupNow(gameId) {
      await wait(500); const made = db.saves.filter((s) => s.gameId === gameId).map((s) => ({ id: id('b'), gameId, kind: 'backup' as const, fromFile: s.fileName, name: `Today ${now()}`, note: 'by hand', when: `Today ${now()}`, size: s.size, slots: clone(s.slots.filter((x) => x.character)) }));
      db.copies.unshift(...made);
      return record({ kind: 'save', gameId, title: `Backed up ${made.length} save${made.length === 1 ? '' : 's'}`, scope: 'saves', noUndoReason: 'Backups cannot be taken back' });
    },

    async listConfigFiles(pid) {
      await latency(); const p = profile(pid); const out: ConfigFileRef[] = [];
      p.mods.forEach((m) => {
        m.configs.forEach((n) => { const owner = p.mods.find((x) => x.id === m.partOfModId); out.push({ id: seed.configIdByName[n] ?? `gen:${m.id}:${n}`, modId: m.id, modName: owner?.name ?? m.name, name: n, groupId: owner?.id, viaFile: m.kind === 'native' ? m.file : undefined }); });
        if (m.setupId && db.setups[m.setupId]) out.push({ id: `setup:${m.setupId}`, modId: m.id, modName: m.name, name: 'Overhaul setup', isSetup: true });
      });
      return out;
    },
    async getConfigFile(pid, cid) {
      await latency(); const known = db.configs[cid]; if (known) return clone(known);
      const [, modId, name] = cid.split(':'); const m = profile(pid).mods.find((x) => x.id === modId);
      const gen: ConfigFile = { id: cid, modId: modId ?? '', modName: m?.name ?? '', name: name ?? cid, path: `${m?.folder ?? ''}/${name}`, format: 'text', text: `; ${name}\n; Bayle shows files it doesn't know as text.\n` };
      db.configs[cid] = gen; return clone(gen);
    },
    async saveConfigFile(pid, cid, change) {
      await latency(); const f = db.configs[cid]; if (!f) throw new Error('That file is gone.'); const before = clone(f);
      if ('text' in change) f.text = change.text;
      else Object.entries(change.values).forEach(([k, v]) => { const [sec, key] = k.split('.'); const field = f.sections?.find((s) => s.name === sec)?.fields.find((x) => x.key === key); if (field) field.value = v; });
      const p = profile(pid);
      return record({ kind: 'profile', gameId: p.gameId, title: `Saved ${f.name}`, detail: f.modName, scope: 'configs', revert: () => { db.configs[cid] = before; }, undoLines: [`${f.name} goes back to what it was`] });
    },

    async getSetup(sid) { await latency(); const s = db.setups[sid]; if (!s) throw new Error('No saved setup for that overhaul.'); return clone(s); },
    async setupUsers(sid) { await latency(); return db.profiles.filter((p) => p.mods.some((m) => m.setupId === sid && !m.installerMade)).map((p) => ({ profileId: p.id, name: p.name, running: db.running === p.gameId && db.games.find((g) => g.id === p.gameId)?.activeProfileId === p.id })); },
    async saveSetup(setup) {
      const users = await api.setupUsers(setup.id);
      await job(`Saving ${setup.name}'s setup and rebuilding ${users.length} profile${users.length === 1 ? '' : 's'}…`, 1200);
      const before = clone(db.setups[setup.id]); db.setups[setup.id] = { ...clone(setup), savedOn: 'today' };
      return record({ kind: 'rebuild', gameId: db.profiles.find((p) => p.id === users[0]?.profileId)?.gameId ?? 'er', title: `Saved ${setup.name}'s setup to ${users.length} profile${users.length === 1 ? '' : 's'}`, detail: users.map((u) => u.name).join(', '), scope: 'configs', revert: () => { if (before) db.setups[setup.id] = before; }, undoLines: [`Every profile goes back to the previous ${setup.name} setup`] });
    },
    async installOverhaul(pid, setup) {
      await job(`Building ${setup.name}: merged rules, animations and menu text…`, 1800);
      const p = profile(pid); const revert = snapProfile(p); const beforeSetup = clone(db.setups[setup.id]);
      p.mods = p.mods.filter((m) => m.setupId !== setup.id && m.partOfSetupId !== setup.id); p.installer = undefined;
      const pk: Mod = { id: setup.id, packageId: setup.id, name: setup.name, kind: 'package', enabled: true, version: setup.version, folder: setup.gameDir.replace(/\\$/, ''), size: '640 MB', addedOn: 'today', description: 'Loads last, built on top of the mods above it', tags: [{ label: 'Loads last', tone: 'vio' }], configs: [], loadAfter: [], setupId: setup.id, staysLast: true, rebuildFile: 'regulation.bin' };
      const firstNat = p.mods.findIndex((m) => m.kind === 'native'); p.mods.splice(firstNat >= 0 ? firstNat : p.mods.length, 0, pk);
      setup.dlls.forEach((d, i) => p.mods.push({ id: `${setup.id}-dll${i}`, packageId: d.name, name: setup.name, file: d.name, nameSource: 'install', partOfModId: p.mods.find((x) => x.setupId === setup.id)?.id, kind: 'native', enabled: true, folder: `${setup.gameDir}${d.name}`, size: '4 MB', addedOn: 'today', description: d.loadEarly ? 'Starts early' : 'Starts normally', tags: [], configs: [], loadAfter: [], partOfSetupId: setup.id, native: { loadEarly: d.loadEarly, optional: false, initializer: { kind: 'function', value: d.initFunction }, finalizer: '' } }));
      p.merge = 'ok'; recount(p); db.setups[setup.id] = { ...clone(setup), savedOn: 'today' };
      return record({ kind: 'install', gameId: p.gameId, title: `Installed ${setup.name} ${setup.version}`, detail: `${p.name} · regulation.bin combined${setup.languages ? `, menu text in ${setup.languages} languages` : ''}`, message: `${setup.name} is installed`, sub: 'Merged files built. Undo install in Activity.', scope: 'profiles', undoLabel: 'Undo install', revert: () => { revert(); if (beforeSetup) db.setups[setup.id] = beforeSetup; }, undoLines: [`${setup.name} leaves ${p.name}`, 'Its merged files and folder are removed', 'The saved setup goes back to what it was'] });
    },
    async removeOverhaul(pid, sid) {
      await wait(600); const p = profile(pid); const revert = snapProfile(p); const name = db.setups[sid]?.name ?? sid;
      p.mods = p.mods.filter((m) => m.setupId !== sid && m.partOfSetupId !== sid); p.merge = 'none'; recount(p);
      return record({ kind: 'install', gameId: p.gameId, title: `Removed ${name}`, detail: p.name, scope: 'profiles', undoLabel: 'Restore', revert, undoLines: [`${name} comes back to ${p.name}, with its merged files`] });
    },

    async listActivity() { await latency(); return clone(db.activity); },
    async undo(entryId) {
      await latency(); const e = db.activity.find((x) => x.id === entryId);
      if (!e || !e.undoable || e.undone) throw new Error('That can no longer be undone.');
      const r = reverts.get(entryId); r?.(); e.undone = true;
      const entry: ActivityEntry = { id: id('a'), gameId: e.gameId, kind: e.kind, ok: true, title: `Undid: ${e.title}`, detail: '', day: 'Today', time: now(), duration: 'under a second', hasLog: false, undoable: false, noUndoReason: 'An undo cannot be undone; make the change again instead' };
      db.activity.unshift(entry);
      (['profiles', 'saves', 'configs', 'settings', 'activity'] as const).forEach((scope) => emit({ type: 'changed', scope }));
      return { entry, message: `Undone: ${e.title}` };
    },
    async getLog(entryId) {
      await latency(); const e = db.activity.find((x) => x.id === entryId);
      if (e?.kind === 'rebuild') return ['22:15:02 rebuild: Convergence (tool: ConvergenceMerge.exe)', '22:15:09 merging regulation.bin from 3 mods', '22:15:16 error: ConvergenceMerge.exe exited with code 1', '22:15:16 the previous merged game data was kept'];
      if (e?.kind === 'install') return ['18:10:04 import: GrandMerchant-1.2.zip', '18:10:05 copying mods/GrandMerchant/regulation.bin', '18:10:06 error: the file is being used by another process (eldenring.exe)', '18:10:06 nothing was changed'];
      return ['00:38:00 me3 launch --game er --profile "Seamless + Convergence"', '02:49:12 game closed · exit code 0', '02:49:14 save repaired: ER0000.co2', '02:49:14 closed 1 leftover process'];
    },

    async getSettings() { await latency(); return clone(db.settings); },
    async getDefaultSettings() { return clone(seed.defaultSettings); },
    async updateSettings(patch) {
      await latency();
      (Object.keys(patch) as (keyof Settings)[]).forEach((k) => { Object.assign(db.settings[k], patch[k]); });
      emit({ type: 'changed', scope: 'settings' }); return clone(db.settings);
    },
    async clearBootBoostCache() { await wait(300); },
    async saveSupportLogs() { await wait(600); return 'C:\\Users\\you\\Desktop\\bayle-support.zip'; },
    async checkForUpdates() { await wait(700); return api.getAppInfo(); },

    // Alternates between a plain mod and an overhaul so both install paths can be tried in the mock.
    async pickFile(opts) { await latency(); if (opts.title.toLowerCase().includes('save')) return 'C:\\Users\\you\\Downloads\\ER0000_friend.sl2'; picks += 1; return picks % 2 ? 'C:\\Users\\you\\Downloads\\GrandMerchant-1.3.zip' : 'C:\\Users\\you\\Downloads\\NightreignRevive-1.4.zip'; },
    async pickFolder() { await latency(); return 'D:\\Mods\\NewFolder'; },
    async openPath() { await latency(); },
    async openUrl(url) { window.open(url, '_blank', 'noopener'); },
    async windowControl() { /* the mock runs in a browser tab */ },
  };

  // Seeded entries that say they can be undone get a no-op revert so the button works in the demo.
  db.activity.filter((e) => e.undoable).forEach((e) => reverts.set(e.id, () => {}));
  return api;
}

export type { OverhaulSetup };
