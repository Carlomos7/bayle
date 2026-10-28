import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { connectEngine, resetEngineState } from '@/data/engine';
import { GatewayError } from '../transport';
import { createGateway } from '../hub';
import { createGatewayApi } from '../gatewayApi';
import { fakeTransport, flush } from '../fakeTransport.test-util';
import { shareSetupApi } from './shareSetup';
import { forget, readMods, resolvePath, toMods, type EngineEntry, type EnginePageFacts } from './modsCommon';

beforeEach(() => { resetEngineState(); forget(PROFILE); });
afterEach(() => resetEngineState());

type Handler = (params: Record<string, unknown> | undefined) => unknown;
/** An operation that starts a job ending as given, a moment after the start call answers. */
interface JobSpec { job: string; title: string; result?: unknown; undo?: Record<string, unknown>; error?: { code: string; message: string } }

/** A ready engine whose operations are answered by `ops`. A handler may throw a GatewayError (a refusal). */
async function engine(ops: Record<string, Handler | JobSpec>) {
  const t = fakeTransport({ state: 'ready', epoch: 1 });
  const g = createGateway(t);
  connectEngine(g, new QueryClient());
  await flush(); await flush();
  const base = t.call.bind(t);
  let seq = 0;
  const runs: Record<string, number> = {};
  t.call = (async (op: string, params?: Record<string, unknown>, o?: { epoch?: number }) => {
    const h = ops[op];
    if (!h) return base(op, params, o);
    t.calls.push({ operation: op, params, epoch: o?.epoch });
    if (typeof h === 'function') return h(params);
    // A second start of the same operation is a second job (its own id), so no event outlives the test that waited for it.
    const id = (runs[op] = (runs[op] ?? 0) + 1) === 1 ? h.job : `${h.job}.${runs[op]}`;
    setTimeout(() => {
      t.event({ seq: ++seq, type: 'started', job_id: id, data: { title: h.title, quiet: true } });
      if (h.error) t.event({ seq: ++seq, type: 'failed', job_id: id, data: { error: h.error } });
      else t.event({ seq: ++seq, type: 'finished', job_id: id, data: { result: h.result, undo: h.undo ?? null } });
    }, 0);
    return { job_id: id };
  }) as typeof t.call;
  return { t, g, api: createGatewayApi(g), asked: () => t.calls.map((c) => [c.operation, c.params]) };
}

const PROFILE = 'C:\\Profiles\\Main\\Main.me3';
const DIR = 'C:\\Profiles\\Main';
const undo = { type: 'remove', profile: PROFILE, name: 'Alpha' };

const entry = (over: Partial<EngineEntry>): EngineEntry => ({
  kind: 'package', path: 'mods\\Alpha', id: 'alpha', enabled: true, optional: false, load_early: false, initializer: null, finalizer: '',
  load_after: [], load_before: [], index: 0, name: 'alpha', ...over,
});
/** Blocks: 0 alpha (package), 1 beta (package, loads nothing), 2 gamma (package, last), 3 ersc.dll, 4 Tool.dll inside alpha. */
const facts = (over: Partial<EnginePageFacts> = {}): EnginePageFacts => ({
  profile: PROFILE,
  entries: [
    entry({ index: 0 }),
    entry({ index: 1, path: 'mods', id: '', name: 'mods' }),
    entry({ index: 2, path: 'mods\\Gamma', id: 'gamma', name: 'gamma', load_after: [{ id: 'alpha', optional: true }] }),
    entry({ index: 3, kind: 'native', path: 'natives\\Seamless\\ersc.dll', id: '', name: 'ersc.dll', load_early: true, initializer: { function: 'ModInit' } }),
    entry({ index: 4, kind: 'native', path: 'mods\\Alpha\\Tool.dll', id: '', name: 'Tool.dll', enabled: false, optional: true }),
  ],
  display: { package: [0, 1, 2], native: [3, 4] },
  problems: { '2': ["Must load after 'alpha'"] },
  loads_nothing: [1],
  stays_last: [2],
  missing: [4],
  configs: { '3': ['C:\\Profiles\\Main\\natives\\Seamless\\ersc_settings.ini'] },
  shared: { '0': 2 },
  loose_dlls: [],
  ...over,
});
const page = (f: EnginePageFacts = facts()) => ({ profile: PROFILE, has_profile: true, facts: f });

describe('mods adapter: reading', () => {
  it('maps the page to mods: packages then natives, the configs adapter ids, tags and options', () => {
    const mods = toMods(PROFILE, facts());
    expect(mods.map((m) => m.id)).toEqual([`${DIR}\\mods\\Alpha`, `${DIR}\\mods\\Gamma`, 'seamless', `${DIR}\\mods\\Alpha\\Tool.dll`]);
    expect(mods[0]).toMatchObject({ kind: 'package', packageId: 'alpha', name: 'alpha', shared: true, folder: 'mods\\Alpha', tags: [{ label: 'Shared', tone: 'info' }] });
    expect(mods[1]).toMatchObject({ staysLast: true, loadAfter: [{ packageId: 'alpha', optional: true }], description: "Must load after 'alpha'" });
    expect(mods[2]).toMatchObject({ kind: 'native', file: 'ersc.dll', configs: ['ersc_settings.ini'], native: { loadEarly: true, initializer: { kind: 'function', value: 'ModInit' } } });
    expect(mods[3]).toMatchObject({ enabled: false, missing: true, partOfModId: `${DIR}\\mods\\Alpha`, native: { optional: true } });
  });

  it('resolves a relative path against the profile folder and keeps an absolute one', () => {
    expect(resolvePath(PROFILE, '.\\mods\\X')).toBe(`${DIR}\\mods\\X`);
    expect(resolvePath('/p/Main/Main.me3', 'mods/X')).toBe('/p/Main/mods/X');
    expect(resolvePath(PROFILE, 'D:\\Elsewhere\\X')).toBe('D:\\Elsewhere\\X');
  });

  it('reads the page for a profile and refuses an unreadable one', async () => {
    const { g, asked } = await engine({ mods: () => page() });
    expect((await readMods(g, PROFILE)).length).toBe(4);
    expect(asked()).toEqual([['mods', { profile: PROFILE }]]);
    const bad = await engine({ mods: () => page(facts({ error: 'Not valid TOML.' })) });
    await expect(readMods(bad.g, PROFILE)).rejects.toMatchObject({ code: 'unreadable', message: 'Not valid TOML.' });
  });
});

describe('mods adapter: writes by index', () => {
  it('switches mods on and off by block index with the name as expect, reading the page once', async () => {
    const { api, g, asked } = await engine({ mods: () => page(), mods_set_enabled: () => ({ name: 'alpha' }) });
    await readMods(g, PROFILE);
    const r = await api.setModsEnabled(PROFILE, [`${DIR}\\mods\\Alpha`, 'seamless'], false);
    expect(asked()).toEqual([
      ['mods', { profile: PROFILE }],
      ['mods_set_enabled', { profile: PROFILE, index: 0, enabled: false, expect: 'alpha' }],
      ['mods_set_enabled', { profile: PROFILE, index: 3, enabled: false, expect: 'ersc.dll' }],
    ]);
    expect(r).toEqual({ message: 'Turned off 2 mods' });
  });

  it('reads the page first when it has not been read, and says so when the mod is gone', async () => {
    const { api, asked } = await engine({ mods: () => page(), mods_set_enabled: () => ({}) });
    await api.setModsEnabled(PROFILE, [`${DIR}\\mods\\Gamma`], true);
    expect(asked()[0]).toEqual(['mods', { profile: PROFILE }]);
    await expect(api.setModsEnabled(PROFILE, ['C:\\nope'], true)).rejects.toMatchObject({ code: 'not_found', message: 'That mod is no longer in the profile.' });
  });

  it('refuses a stale index: the engine\'s refusal reaches the caller and the next call reads the page again', async () => {
    let stale = true;
    const { api, g, asked } = await engine({
      mods: () => page(),
      mods_set_enabled: () => { if (stale) throw new GatewayError({ code: 'stale', message: 'The profile changed; look again.' }); return {}; },
    });
    await readMods(g, PROFILE);
    await expect(api.setModsEnabled(PROFILE, [`${DIR}\\mods\\Alpha`], false)).rejects.toMatchObject({ code: 'stale' });
    stale = false;
    await api.setModsEnabled(PROFILE, [`${DIR}\\mods\\Alpha`], false);
    expect(asked().filter((c) => c[0] === 'mods')).toHaveLength(2);
  });

  it('reorders with one move: the position counts the entries that load nothing', async () => {
    const after = facts({ display: { package: [2, 1, 0], native: [3, 4] } });
    const answers = [page(), page(after)];
    const { api, asked } = await engine({ mods: () => answers.shift(), mods_move: () => ({ moved: true, name: 'gamma', problem: '', decided_by: -1 }) });
    const r = await api.reorderMods(PROFILE, 'package', [`${DIR}\\mods\\Gamma`, `${DIR}\\mods\\Alpha`]);
    expect(asked().filter((c) => c[0] === 'mods_move')).toEqual([['mods_move', { profile: PROFILE, index: 2, to: 0, expect: 'gamma' }]]);
    expect(r.message).toBe('Load order changed');
  });

  it('says why the engine would not keep a mod there', async () => {
    const { api } = await engine({ mods: () => page(), mods_move: () => ({ moved: false, name: 'gamma', problem: 'It must load after alpha.', decided_by: 0 }) });
    await expect(api.reorderMods(PROFILE, 'package', [`${DIR}\\mods\\Gamma`, `${DIR}\\mods\\Alpha`])).rejects.toMatchObject({ code: 'move_refused', message: 'It must load after alpha.' });
  });
});

describe('mods adapter: remove (a job with Undo)', () => {
  it('removes one mod: confirmed, the entry comes from the job and offers Undo', async () => {
    const { api, asked } = await engine({ mods: () => page(), mods_remove: { job: 'j1', title: 'Removing alpha...', result: { name: 'alpha', undo }, undo } });
    const r = await api.removeMods(PROFILE, [`${DIR}\\mods\\Alpha`]);
    expect(asked()[1]).toEqual(['mods_remove', { profile: PROFILE, index: 0, name: 'alpha', confirmed: true }]);
    expect(r).toMatchObject({ message: 'Removed alpha', entry: { id: 'j1', kind: 'profile', title: 'Removing alpha...', undoable: true } });
  });

  it('removes several from the last block to the first, with no single Undo', async () => {
    const { api, asked } = await engine({ mods: () => page(), mods_remove: { job: 'j2', title: 'Removing...', result: { name: 'x', undo } } });
    const r = await api.removeMods(PROFILE, [`${DIR}\\mods\\Alpha`, `${DIR}\\mods\\Gamma`]);
    expect(asked().filter((c) => c[0] === 'mods_remove').map((c) => (c[1] as { index: number }).index)).toEqual([2, 0]);
    expect(r.entry).toBeUndefined();
    expect(r.message).toBe('Removed 2 mods');
  });

  it('turns a failed removal into the engine\'s error', async () => {
    const { api } = await engine({ mods: () => page(), mods_remove: { job: 'j3', title: 'Removing...', error: { code: 'remove_failed', message: 'A file was in use.' } } });
    await expect(api.removeMods(PROFILE, [`${DIR}\\mods\\Alpha`])).rejects.toMatchObject({ code: 'remove_failed', message: 'A file was in use.' });
  });
});

describe('mods adapter: options', () => {
  const options = { index: 3, name: 'ersc.dll', kind: 'native', enabled: true, id: '', load_after: [], load_before: [{ id: 'x', optional: false }], optional: false, load_early: true, init_kind: 1, init_value: 'ModInit', finalizer: '', rebuild_file: '' };

  it('saves a patch on top of the engine\'s options, never sends staysLast, and turns a wait into init_kind 2', async () => {
    const { api, asked } = await engine({ mods: () => page(), mods_options: () => options, mods_save_options: () => ({ name: 'ersc.dll' }) });
    await api.updateMod(PROFILE, 'seamless', { staysLast: true, native: { loadEarly: true, optional: true, initializer: { kind: 'delay', value: '500' }, finalizer: 'Done' } });
    expect(asked()[2]).toEqual(['mods_save_options', {
      profile: PROFILE, index: 3, enabled: true, id: '', load_after: [], load_before: [{ id: 'x', optional: false }], optional: true, load_early: true,
      finalizer: 'Done', init_kind: 2, init_value: '500', rebuild_file: '', expect: 'ersc.dll',
    }]);
  });

  it('maps package id and load-after, and refuses when the entry changed under the page', async () => {
    const { api, asked } = await engine({ mods: () => page(), mods_options: () => ({ ...options, index: 0, name: 'renamed' }), mods_save_options: () => ({}) });
    await expect(api.updateMod(PROFILE, `${DIR}\\mods\\Alpha`, { packageId: 'a2' })).rejects.toMatchObject({ code: 'stale' });
    expect(asked().some((c) => c[0] === 'mods_save_options')).toBe(false);
    const ok = await engine({ mods: () => page(), mods_options: () => ({ ...options, index: 0, name: 'alpha', kind: 'package', id: 'alpha' }), mods_save_options: () => ({}) });
    await ok.api.updateMod(PROFILE, `${DIR}\\mods\\Alpha`, { packageId: 'a2', loadAfter: [{ packageId: 'b', optional: true }], rebuildFile: 'regulation.bin' });
    expect(ok.asked()[2]![1]).toMatchObject({ id: 'a2', load_after: [{ id: 'b', optional: true }], rebuild_file: 'regulation.bin', expect: 'alpha' });
  });

  it('an enabled-only patch is a plain switch; a display name is not connected', async () => {
    const { api, asked } = await engine({ mods: () => page(), mods_set_enabled: () => ({}) });
    await api.updateMod(PROFILE, `${DIR}\\mods\\Alpha`, { enabled: false });
    expect(asked()[1]).toEqual(['mods_set_enabled', { profile: PROFILE, index: 0, enabled: false, expect: 'alpha' }]);
    await expect(api.updateMod(PROFILE, `${DIR}\\mods\\Alpha`, { name: 'Nice' })).rejects.toMatchObject({ code: 'not_wired' });
  });
});

describe('mods adapter: rebuild, take over, add to profile', () => {
  it('rebuilds as a job; a tool that is not allowed yet is said plainly', async () => {
    const { api, asked } = await engine({ mods_rebuild: { job: 'j4', title: 'Rebuilding...', result: {} } });
    expect(await api.rebuildMerged(PROFILE)).toMatchObject({ message: 'Rebuilt the merged game data', entry: { id: 'j4', kind: 'rebuild' } });
    expect(asked()).toEqual([['mods_rebuild', { profile: PROFILE }]]);
    const asks = await engine({ mods_rebuild: () => { throw new GatewayError({ code: 'needs_confirmation', message: 'x', details: { reason: 'allow_tool', tool: { label: 'MergeTool' } } }); } });
    await expect(asks.api.rebuildMerged(PROFILE)).rejects.toMatchObject({ message: expect.stringContaining('MergeTool') });
  });

  it('takes over an installer with the rows it ticked and the check\'s stamp', async () => {
    const { api, asked } = await engine({
      mod_install_takeover_choices: () => ({ label: 'Convergence', rows: ['a', 'b'], ticked: [0] }),
      mod_install_check_takeover: () => ({ label: 'Convergence', lines: [], notes: [], refusals: [], asked: [], update: false, stamp: [5, 6] }),
      mod_install_takeover: { job: 'j5', title: 'Taking over...', result: {}, undo },
    });
    const r = await api.takeOverInstaller(PROFILE);
    expect(asked()).toEqual([
      ['mod_install_takeover_choices', { profile: PROFILE }],
      ['mod_install_check_takeover', { profile: PROFILE, chosen: [0] }],
      ['mod_install_takeover', { profile: PROFILE, chosen: [0], revert: false, expect: [5, 6] }],
    ]);
    expect(r).toMatchObject({ message: 'Took over Convergence', entry: { id: 'j5', undoable: true } });
  });

  it('adds a Shared mod to another profile through the library, and not a Separate one', async () => {
    const TARGET = 'C:\\Profiles\\Other\\Other.me3';
    const { api, asked } = await engine({
      mods: () => page(),
      mod_library_use_choices: () => ({ name: 'Alpha', mod_id: 'alpha', version: '1', profiles: [{ profile: TARGET, name: 'Other', has_copy: false, uses: false }] }),
      mod_library_use: { job: 'j6', title: 'Linking...', result: {}, undo },
    });
    const r = await api.addModsToProfile(TARGET, PROFILE, [`${DIR}\\mods\\Alpha`]);
    expect(asked().slice(1)).toEqual([
      ['mod_library_use_choices', { profile: PROFILE, index: 0 }],
      ['mod_library_use', { profile: PROFILE, index: 0, targets: [TARGET] }],
    ]);
    expect(r).toMatchObject({ message: 'Added 1 mod to Other', entry: { id: 'j6', undoable: true } });
    const sep = await engine({ mods: () => page(), mod_library_use_choices: () => { throw new GatewayError({ code: 'not_shared', message: 'x' }); } });
    await expect(sep.api.addModsToProfile(TARGET, PROFILE, [`${DIR}\\mods\\Alpha`])).rejects.toMatchObject({ code: 'not_wired' });
  });

  it('keeps the gaps not connected', async () => {
    const { api, asked } = await engine({});
    await expect(api.listModFiles(PROFILE, 'x')).rejects.toMatchObject({ code: 'not_wired' });
    await expect(api.upgradeMod(PROFILE, 'x')).rejects.toMatchObject({ code: 'not_wired' });
    expect(asked()).toEqual([]);
  });
});

describe('mods adapter: the install dialog', () => {
  const SRC = 'C:\\Downloads\\Cool.zip';
  const plan = (over: Record<string, unknown> = {}) => ({
    kind: 'package', name: 'Cool', id: 'cool', variant: '', id_taken: false, option: 'plain', already_listed: [],
    contents: [{ name: 'parts', group: 'game', size: 2048, on: true }, { name: 'README.txt', group: 'doc', size: 100, on: false }], ...over,
  });

  it('opens, plans again for a typed name, and finishes with what was ticked', async () => {
    const { api, asked } = await engine({
      mod_install_sources: () => ({ usable: [SRC], skipped: [] }),
      mod_install_open: () => ({ install_id: 'i1', plan: plan(), overhaul_on: false, stamp: [7, 8] }),
      mod_install_replan: () => ({ plan: plan({ name: 'Cooler', id: 'cooler' }) }),
      mod_install_finish: { job: 'j7', title: 'Installing Cooler...', result: { name: 'Cooler', overhaul: false, update: false }, undo },
    });
    const preview = await api.previewInstall({ path: SRC, profileId: PROFILE });
    expect(preview).toMatchObject({ source: SRC, detectedAs: 'package', name: 'Cool', items: [{ path: 'parts', what: 'game files', include: true, size: '2 KB' }, { path: 'README.txt', include: false }] });
    const r = await api.install(PROFILE, { ...preview, name: 'Cooler', items: preview.items.map((i) => ({ ...i, include: i.path === 'parts' })) });
    expect(asked()).toEqual([
      ['mod_install_sources', { paths: [SRC] }],
      ['mod_install_open', { profile: PROFILE, source: SRC }],
      ['mod_install_replan', { install_id: 'i1', name: 'Cooler', id: '', variant: null }],
      ['mod_install_finish', { install_id: 'i1', choices: { name: 'Cooler', id: 'cooler', variant: null, exclude: ['README.txt'] }, expect: [7, 8] }],
    ]);
    expect(r).toMatchObject({ message: 'Installed Cooler', entry: { id: 'j7', kind: 'install', undoable: true } });
  });

  it('closes the open install when another download is read, warns about a taken id and says why a finish is refused', async () => {
    let n = 0;
    const { api, asked } = await engine({
      mod_install_sources: () => ({ usable: ['x'], skipped: [] }),
      mod_install_open: () => ({ install_id: `i${++n}`, plan: plan({ id_taken: true }), overhaul_on: false, stamp: null }),
      mod_install_close: () => ({}),
      mod_install_finish: () => { throw new GatewayError({ code: 'not_ready', message: 'The install is not ready.', details: { reason: 'id_taken' } }); },
    });
    const a = await api.previewInstall({ path: SRC, profileId: PROFILE });
    expect(a.warnings).toEqual(['Another mod in this profile already uses the id "cool".']);
    await api.previewInstall({ path: 'C:\\Other.zip', profileId: PROFILE });
    expect(asked().filter((c) => c[0] === 'mod_install_close')).toEqual([['mod_install_close', { install_id: 'i1' }]]);
    await expect(api.install(PROFILE, { ...a, source: 'C:\\Other.zip' })).rejects.toMatchObject({ code: 'not_ready', message: 'Another mod in this profile already uses that id.' });
  });

  it('refuses a path the engine cannot install and a dialog without a profile', async () => {
    const { api } = await engine({ mod_install_sources: () => ({ usable: [], skipped: ['C:\\a.txt'] }) });
    await expect(api.previewInstall({ path: 'C:\\a.txt', profileId: PROFILE })).rejects.toMatchObject({ code: 'not_installable' });
    await expect(api.previewInstall({ path: SRC })).rejects.toMatchObject({ code: 'invalid_params' });
    await expect(api.install(PROFILE, { source: 'never opened', detectedAs: 'package', name: 'x', items: [], warnings: [] })).rejects.toMatchObject({ code: 'unknown_install' });
  });
});

describe('mods adapter: Share setup', () => {
  const listing = { mods: [{ key: 'package:0', name: 'Alpha', enabled: true, size: 10 }, { key: 'native:1', name: 'Tool', enabled: false, size: 5 }], save_name: 'ER0000.sl2' };

  it('shows the share list as the setup', async () => {
    const { api, asked } = await engine({ profile_transfer: () => listing });
    const m = await api.exportManifest(PROFILE);
    expect(asked()).toEqual([['profile_transfer', { profile: PROFILE }]]);
    expect(m).toMatchObject({ profileName: 'Main', mods: [{ name: 'Alpha', kind: 'package', enabled: true, order: 1 }, { name: 'Tool', kind: 'native', enabled: false, order: 2 }], configs: [] });
  });

  it('exports a share list into the picked folder, without settings contents, and returns the file', async () => {
    const { g, asked } = await engine({
      profile_transfer: () => listing,
      profile_transfer_check_export: () => ({ size: 15, big: false }),
      profile_transfer_export: { job: 'j8', title: 'Exporting a profile...', result: { path: 'C:\\Share\\Main.json', size: 300 } },
    });
    // The pickers are the desktop adapter's; the finished api hands them in, the test hands in fakes.
    const share = shareSetupApi(g, { pickFile: async () => null, pickFolder: async () => 'C:\\Share' });
    expect(await share.saveManifest!(PROFILE)).toBe('C:\\Share\\Main.json');
    expect(asked().slice(1)).toEqual([
      ['profile_transfer_check_export', { profile: PROFILE, kind: 'list', chosen: ['package:0', 'native:1'] }],
      ['profile_transfer_export', { profile: PROFILE, kind: 'list', name: 'Main', folder: 'C:\\Share', chosen: ['package:0', 'native:1'], with_configs: false, with_save: false, password: false, expect: 15 }],
    ]);
    const none = shareSetupApi(g, { pickFile: async () => null, pickFolder: async () => null });
    expect(await none.saveManifest!(PROFILE)).toBeNull();
  });

  it('does not connect the comparison of two setups', async () => {
    const { api, asked } = await engine({});
    await expect(api.compareManifest(PROFILE)).rejects.toMatchObject({ code: 'not_wired' });
    expect(asked()).toEqual([]);
  });
});
