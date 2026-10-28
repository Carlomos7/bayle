import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { connectEngine, resetEngineState } from '@/data/engine';
import { GatewayError } from '../transport';
import { createGateway } from '../hub';
import { createGatewayApi } from '../gatewayApi';
import { fakeTransport, flush } from '../fakeTransport.test-util';
import { forget, toMods, type EngineEntry, type EnginePageFacts } from './modsCommon';

const PROFILE = 'C:\\Profiles\\Main\\Main.me3';
beforeEach(() => { resetEngineState(); forget(PROFILE); });
afterEach(() => resetEngineState());

type Handler = (params: Record<string, unknown> | undefined) => unknown;
interface JobSpec { job: string; title: string; result?: unknown; undo?: Record<string, unknown> }

/** A ready engine whose operations are answered by `ops`. A handler may throw a GatewayError (a refusal). */
async function engine(ops: Record<string, Handler | JobSpec>) {
  const t = fakeTransport({ state: 'ready', epoch: 1 });
  const g = createGateway(t);
  connectEngine(g, new QueryClient());
  await flush(); await flush();
  const base = t.call.bind(t);
  let seq = 0;
  t.call = (async (op: string, params?: Record<string, unknown>, o?: { epoch?: number }) => {
    const h = ops[op];
    if (!h) return base(op, params, o);
    t.calls.push({ operation: op, params, epoch: o?.epoch });
    if (typeof h === 'function') return h(params);
    setTimeout(() => {
      t.event({ seq: ++seq, type: 'started', job_id: h.job, data: { title: h.title, quiet: true } });
      t.event({ seq: ++seq, type: 'finished', job_id: h.job, data: { result: h.result, undo: h.undo ?? null } });
    }, 0);
    return { job_id: h.job };
  }) as typeof t.call;
  return { api: createGatewayApi(g), asked: () => t.calls.map((c) => [c.operation, c.params]) };
}

const undo = { type: 'overhaul-install' };
const setupRow = { file: 'regulation.bin', kind: 'regulation', action: 'merge', choices: ['merge', 'whole', 'leave'], target: '' };
const choices = {
  natives: [{ file: 'conv.dll', load_early: false, initializer: null, after_others: true }],
  files: [setupRow, { file: 'settings.ini', kind: 'settings', action: 'copy', choices: ['copy', 'keep', 'place', 'leave'], target: '' }],
  texts: [{ file: 'msg/{each}/item.msgbnd.dcx', table: 'Goods.fmg', tables: ['Goods.fmg'] }],
};
const form = (over: Record<string, unknown> = {}) => ({
  setup: { config: { id: 'conv', label: 'Convergence', basic: { version: '1.2' } }, verified: false, level: 'basic', folder: 'C:\\lib\\conv', path: 'C:\\lib\\conv.toml', sha: 'abc', ...over },
  choices, values: {}, new: false,
});

describe('overhaul adapter: the profile\'s own setup', () => {
  it('reads the form as the UI\'s setup, saves it against the sha it read and applies it as a job', async () => {
    const { api, asked } = await engine({
      mod_configs_overhaul_form: () => form(),
      mod_configs_save_setup: () => ({ name: 'conv.toml', overhaul_id: 'conv' }),
      mod_configs_apply_setup: { job: 'j1', title: 'Applying', result: { profiles: ['Main'] }, undo },
    });
    const s = await api.getSetup('C:\\lib\\conv.toml', PROFILE);
    expect(s).toMatchObject({
      name: 'Convergence', version: '1.2', gameDir: 'C:\\lib\\conv', recipe: { source: 'yours', forVersion: '1.2', check: 'match' },
      dlls: [{ name: 'conv.dll', loadEarly: false, loadAfterOthers: true, initFunction: '' }],
      files: [{ path: 'regulation.bin', action: 'combine' }, { path: 'settings.ini', action: 'copy' }, { path: 'msg/{each}/item.msgbnd.dcx', action: 'text' }],
    });
    const edited = { ...s, dlls: [{ ...s.dlls[0]!, loadEarly: true, initFunction: 'Init' }], files: s.files.map((f) => (f.path === 'settings.ini' ? { ...f, action: 'place' as const, target: 'cfg/settings.ini' } : f)) };
    const r = await api.saveSetup(edited);
    expect(asked()).toEqual([
      ['mod_configs_overhaul_form', { profile: PROFILE }],
      ['mod_configs_save_setup', { profile: PROFILE, path: 'C:\\lib\\conv.toml', expect: 'abc', form: {
        natives: [{ file: 'conv.dll', load_early: true, initializer: 'Init', after_others: true }],
        files: { 'regulation.bin': 'merge', 'settings.ini': 'place:cfg/settings.ini' },
        tables: { 'msg/{each}/item.msgbnd.dcx': 'Goods.fmg' },
      } }],
      ['mod_configs_apply_setup', { profile: PROFILE, overhaul_id: 'conv' }],
    ]);
    expect(r).toMatchObject({ message: "Saved Convergence's setup", detail: 'Applied to Main', entry: { id: 'j1', kind: 'rebuild', undoable: true } });
    // The sha moved with the write: saving the same read again is refused here, before the engine is asked.
    await expect(api.saveSetup(edited)).rejects.toMatchObject({ code: 'stale' });
  });

  it('passes the engine\'s stale refusal on, and refuses a setup written by hand or never opened', async () => {
    const { api, asked } = await engine({
      mod_configs_overhaul_form: (p) => form(p?.profile === 'hand' ? { level: 'advanced' } : {}),
      mod_configs_save_setup: () => { throw new GatewayError({ code: 'stale', message: 'The setup changed on disk since it was read.' }); },
    });
    const s = await api.getSetup('conv', PROFILE);
    await expect(api.saveSetup(s)).rejects.toMatchObject({ code: 'stale', message: 'The setup changed on disk since it was read.' });
    expect(asked().filter((c) => c[0] === 'mod_configs_apply_setup')).toEqual([]);
    await expect(api.getSetup('conv', 'hand')).rejects.toMatchObject({ code: 'advanced_setup' });
    await expect(api.saveSetup({ ...s, id: 'never' })).rejects.toMatchObject({ code: 'stale' });
    await expect(api.setupUsers('conv')).rejects.toMatchObject({ code: 'not_wired' });
  });
});

describe('overhaul adapter: setting a profile mod up as its overhaul', () => {
  const FOLDER = 'C:\\Profiles\\Main\\mods\\Conv';
  const candidates = { mods: [{ name: 'Conv', id: 'conv', folder: FOLDER }] };

  it('checks the plan, then installs with the stamp the check gave', async () => {
    const { api, asked } = await engine({
      mod_configs_setup_candidates: () => candidates,
      mod_configs_overhaul_form: () => ({ ...form({ path: null, sha: null }), new: true }),
      mod_configs_check_install_setup: () => ({ label: 'Conv', lines: [], notes: [], refusals: [], stamp: [5, 6] }),
      mod_configs_install_setup: { job: 'j2', title: 'Installing Conv as an overhaul...', result: { name: 'Conv' }, undo },
    });
    const s = await api.getSetup(`mod:${FOLDER.toLowerCase()}`, PROFILE);
    expect(s).toMatchObject({ name: 'Conv', savedOn: null });
    expect(s.recipe).toBeUndefined();
    const r = await api.installOverhaul(PROFILE, s);
    const body = { profile: PROFILE, folder: FOLDER, name: 'Conv', overhaul_id: 'conv', form: { natives: choices.natives, files: { 'regulation.bin': 'merge', 'settings.ini': 'copy' }, tables: { 'msg/{each}/item.msgbnd.dcx': 'Goods.fmg' } } };
    expect(asked().slice(1)).toEqual([
      ['mod_configs_overhaul_form', { profile: PROFILE, folder: FOLDER, name: 'Conv', overhaul_id: 'conv' }],
      ['mod_configs_check_install_setup', body],
      ['mod_configs_install_setup', { ...body, expect: [5, 6] }],
    ]);
    expect(r).toMatchObject({ message: 'Installed Conv', entry: { id: 'j2', kind: 'install', undoable: true } });
  });

  it('starts no job when the check refuses', async () => {
    const { api, asked } = await engine({
      mod_configs_setup_candidates: () => candidates,
      mod_configs_overhaul_form: () => form(),
      mod_configs_check_install_setup: () => ({ label: 'Conv', lines: [], notes: [], refusals: ['Close the game first.'], stamp: null }),
    });
    const s = await api.getSetup(`mod:${FOLDER}`, PROFILE);
    await expect(api.installOverhaul(PROFILE, s)).rejects.toMatchObject({ code: 'cannot_set_up', message: 'Close the game first.' });
    expect(asked().some((c) => c[0] === 'mod_configs_install_setup')).toBe(false);
  });
});

describe('overhaul adapter: an overhaul download', () => {
  const SRC = 'C:\\Downloads\\Conv.zip';
  const plan = (option: string) => ({ kind: 'package', name: 'Conv', id: 'conv', variant: '', id_taken: false, option, already_listed: [], contents: [], unpacked: 'C:\\tmp\\conv' });
  const preview = (over: Record<string, unknown> = {}) => ({ mode: 'matched', lines: [], notes: [], refusals: [], ...choices, editable: true, ...over });
  const open = (option: string, on = true) => ({
    mod_install_sources: () => ({ usable: [SRC], skipped: [] }),
    mod_install_open: () => ({ install_id: 'i1', plan: plan(option), overhaul_on: on, stamp: [7, 8] }),
  });

  it('opens the sheet for a matched download and finishes it as an overhaul; an unchanged form sends no setup', async () => {
    const { api, asked } = await engine({
      ...open('matched'),
      mod_install_preview: () => preview(),
      mod_install_finish: { job: 'j3', title: 'Installing Conv as an overhaul...', result: { name: 'Conv', overhaul: true, update: false }, undo },
    });
    const p = await api.previewInstall({ path: SRC, profileId: PROFILE });
    expect(p).toMatchObject({ detectedAs: 'overhaul', setupId: 'install:i1', warnings: [] });
    const s = await api.getSetup(p.setupId!, PROFILE);
    expect(s).toMatchObject({ name: 'Conv', savedOn: null, gameDir: 'C:\\tmp\\conv', recipe: { source: 'yours', check: 'match' } });
    const r = await api.installOverhaul(PROFILE, s);
    expect(asked().slice(2)).toEqual([
      ['mod_install_preview', { install_id: 'i1', name: 'Conv' }],
      ['mod_install_preview', { install_id: 'i1', name: 'Conv' }],
      ['mod_install_finish', { install_id: 'i1', choices: { name: 'Conv', id: 'conv', variant: null, exclude: [], overhaul: true }, expect: [7, 8] }],
    ]);
    expect(r).toMatchObject({ message: 'Installed Conv', entry: { id: 'j3', kind: 'install' } });
    // The install ended with the job: its sheet cannot be opened again.
    await expect(api.getSetup('install:i1', PROFILE)).rejects.toMatchObject({ code: 'unknown_install' });
  });

  it('sends the setup when the player changed it, and refuses on the engine\'s refusals', async () => {
    let refusals: string[] = [];
    const { api, asked } = await engine({
      ...open('matched'),
      mod_install_preview: () => preview({ refusals }),
      mod_install_finish: { job: 'j4', title: 'x', result: { name: 'Conv', overhaul: true, update: false }, undo },
    });
    const p = await api.previewInstall({ path: SRC, profileId: PROFILE });
    const s = await api.getSetup(p.setupId!, PROFILE);
    const left = { ...s, files: s.files.map((f) => (f.path === 'settings.ini' ? { ...f, action: 'leave' as const } : f)) };
    refusals = ['Choose the table.'];
    await expect(api.installOverhaul(PROFILE, left)).rejects.toMatchObject({ code: 'cannot_install', message: 'Choose the table.' });
    expect(asked().some((c) => c[0] === 'mod_install_finish')).toBe(false);
    refusals = [];
    await api.installOverhaul(PROFILE, left);
    const sent = asked().filter((c) => c[0] === 'mod_install_finish')[0]![1] as { choices: { setup: { files: Record<string, string> } } };
    expect(sent.choices.setup.files).toEqual({ 'regulation.bin': 'merge', 'settings.ini': 'leave' });
  });

  it('shows a refusal as a download that does not match, and keeps a mere hint an ordinary install', async () => {
    const { api } = await engine({ ...open('matched'), mod_install_preview: () => preview({ refusals: ['Wrong version.'] }) });
    const p = await api.previewInstall({ path: SRC, profileId: PROFILE });
    const s = await api.getSetup(p.setupId!, PROFILE);
    expect(s.recipe).toMatchObject({ check: 'mismatch', differences: ['Wrong version.'] });

    const hint = await engine(open('suggested'));
    expect(await hint.api.previewInstall({ path: SRC, profileId: PROFILE })).toMatchObject({ detectedAs: 'package', warnings: ['This download looks like an overhaul. It installs as an ordinary mod here.'] });
    const off = await engine(open('matched', false));
    expect((await off.api.previewInstall({ path: SRC, profileId: PROFILE })).detectedAs).toBe('package');
  });
});

describe('overhaul adapter: removing, and leftovers', () => {
  it('removes the overhaul after a check, with the rows the engine ticked', async () => {
    const { api, asked } = await engine({
      mod_install_overhaul_remove_choices: () => ({ label: 'Conv', rows: ['a', 'b'], ticked: [1] }),
      mod_install_check_overhaul_remove: () => ({ label: 'Conv', lines: [], notes: [], refusals: [], asked: [], update: false, stamp: [9, 9] }),
      mod_install_overhaul_remove: { job: 'j5', title: 'Removing Conv...', result: { note: 'removed Conv' }, undo },
    });
    const r = await api.removeOverhaul(PROFILE, 'overhaul');
    expect(asked()).toEqual([
      ['mod_install_overhaul_remove_choices', { profile: PROFILE }],
      ['mod_install_check_overhaul_remove', { profile: PROFILE, chosen: [1] }],
      ['mod_install_overhaul_remove', { profile: PROFILE, chosen: [1], revert: false, expect: [9, 9] }],
    ]);
    expect(r).toMatchObject({ message: 'Removed Conv', entry: { id: 'j5', undoable: true } });
  });

  it('starts no removal the check refuses', async () => {
    const { api, asked } = await engine({
      mod_install_overhaul_remove_choices: () => ({ label: 'Conv', rows: [], ticked: [] }),
      mod_install_check_overhaul_remove: () => ({ label: 'Conv', lines: [], notes: [], refusals: ['Close the game.'], asked: [], update: false, stamp: null }),
    });
    await expect(api.removeOverhaul(PROFILE, 'overhaul')).rejects.toMatchObject({ code: 'cannot_remove', message: 'Close the game.' });
    expect(asked().some((c) => c[0] === 'mod_install_overhaul_remove')).toBe(false);
  });

  it('lists leftovers and cleans the chosen ones', async () => {
    const { api, asked } = await engine({
      mod_install_leftovers: () => ({ folders: [{ path: 'C:\\P\\Conv', label: 'Conv', size: 3 * 1024 * 1024 }], backups: [{ path: 'C:\\P\\bak', label: '', size: 2048 }] }),
      mod_install_leftovers_clean: { job: 'j6', title: 'Moving leftovers to the Recycle Bin...', result: { note: '1 moved to the Recycle Bin' } },
    });
    expect(await api.listLeftovers(PROFILE)).toEqual([
      { path: 'C:\\P\\Conv', label: 'Conv', size: '3.0 MB', backup: false },
      { path: 'C:\\P\\bak', label: 'bak', size: '2 KB', backup: true },
    ]);
    const r = await api.cleanLeftovers(PROFILE, ['C:\\P\\Conv']);
    expect(asked()[1]).toEqual(['mod_install_leftovers_clean', { profile: PROFILE, paths: ['C:\\P\\Conv'] }]);
    expect(r).toMatchObject({ message: 'Moved the leftover to the Recycle Bin', entry: { id: 'j6', undoable: false } });
  });
});

describe('overhaul adapter: the Mods page marks the overhaul', () => {
  const e = (over: Partial<EngineEntry>): EngineEntry => ({ kind: 'package', path: 'mods\\A', id: 'a', enabled: true, load_after: [], load_before: [], index: 0, name: 'a', ...over });
  const facts = (overhaul: EnginePageFacts['overhaul']): EnginePageFacts => ({
    profile: PROFILE, entries: [e({ index: 0 }), e({ index: 1, path: 'mods\\Conv', id: 'conv', name: 'conv' })], display: { package: [0, 1], native: [] },
    problems: {}, loads_nothing: [], stays_last: [1], missing: [], configs: {}, overhaul,
  });

  it('gives only the last-loading package a setup id, and only when the engine knows an overhaul', () => {
    expect(toMods(PROFILE, facts({ label: 'Conv' })).map((m) => m.setupId)).toEqual([undefined, 'overhaul']);
    expect(toMods(PROFILE, facts(null)).map((m) => m.setupId)).toEqual([undefined, undefined]);
  });
});
