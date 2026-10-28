import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { cancelJob, connectEngine, resetEngineState, useLaunchJob } from '@/data/engine';
import { createGateway } from '../hub';
import { createGatewayApi, INVALIDATES, toBackendEvents } from '../gatewayApi';
import { fakeTransport, flush } from '../fakeTransport.test-util';
import type { DesktopActions } from '../transport';
import { answerPrompt } from './shell';

beforeEach(() => resetEngineState());
afterEach(() => resetEngineState());

type Handler = (params: Record<string, unknown> | undefined) => unknown;
/** An operation that starts a job ending as given, a moment after the start call answers. */
interface JobSpec { job: string; title: string; result?: unknown; undo?: Record<string, unknown> }

/** A ready engine whose operations are answered by `ops`; `app` is what Rust offers. */
async function engine(ops: Record<string, Handler | JobSpec>, app?: Partial<DesktopActions>) {
  const t = Object.assign(fakeTransport({ state: 'ready', epoch: 1 }), app ? { app: app as DesktopActions } : {});
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
  return { t, g, api: createGatewayApi(g), asked: (op: string) => t.calls.filter((c) => c.operation === op).map((c) => c.params), next: () => ++seq };
}

const ME3 = 'C:\\me3\\profiles\\Mine.me3';
const profile = (over: Record<string, unknown> = {}) => ({ profile: ME3, kind: 'me3', source: ME3, name: 'Mine', active: false, problems: [], ...over });
const engineGame = (over: Record<string, unknown> = {}) => ({ key: 'eldenring', name: 'Elden Ring', ready: true, installed: 'D:\\ER', current: true, profile: ME3, last_run_build: '1.16.1', ...over });
const checked = (over: Record<string, unknown> = {}) => ({ problems: [], warnings: [], game_running: false, busy: false, installed: true, ...over });
const listed = () => ({ profiles: [profile()] });

describe('games', () => {
  it('lists the engine games by key, and selects one by key', async () => {
    const { api, asked } = await engine({
      games: () => ({ games: [engineGame(), engineGame({ key: 'nightreign', name: 'Nightreign', current: false, profile: null, last_run_build: null, installed: null })] }),
      games_select: () => ({ games: [] }),
    });
    const games = await api.getGames();
    expect(games[0]).toMatchObject({ id: 'eldenring', name: 'Elden Ring', abbr: 'ER', supported: true, current: true, activeProfileId: ME3, lastRunBuild: '1.16.1', installFolder: 'D:\\ER' });
    expect(games[1]).toMatchObject({ id: 'nightreign', abbr: 'NI', current: false });
    expect(games[1]!.activeProfileId).toBeUndefined();
    await api.selectGame('nightreign');
    expect(asked('games_select')).toEqual([{ key: 'nightreign' }]);
  });
});

describe('profiles', () => {
  it('uses the profile source as its id, and remembers the active one by source', async () => {
    const { api, asked } = await engine({ launch_profiles: listed, launch_set_profile: () => ({ profiles: [] }) });
    expect(await api.listProfiles('eldenring')).toEqual([{ id: ME3, gameId: 'eldenring', name: 'Mine', modCount: 0, enabledCount: 0 }]);
    await api.setActiveProfile('eldenring', ME3);
    expect(asked('launch_set_profile')).toEqual([{ source: ME3 }]);
  });

  it('reads a profile with its mods and the current game', async () => {
    const entry = { kind: 'package', path: 'mods\\A', id: 'A', enabled: true, optional: false, load_early: false, initializer: null, finalizer: '', load_after: [], load_before: [], index: 0, name: 'A' };
    const facts = { profile: ME3, entries: [entry], display: { package: [0] }, problems: {}, loads_nothing: [], stays_last: [], missing: [], configs: {} };
    const { api } = await engine({ launch_profiles: listed, games: () => ({ games: [engineGame()] }), mods: () => ({ profile: ME3, has_profile: true, facts }) });
    const p = await api.getProfile(ME3);
    expect(p).toMatchObject({ id: ME3, gameId: 'eldenring', name: 'Mine', modCount: 1, enabledCount: 1, merge: 'none' });
    expect(p.mods).toHaveLength(1);
  });

  it('creates an empty profile and answers its path as the id', async () => {
    const { api, asked } = await engine({ launch_create_profile: () => ({ profile: 'C:\\p\\New.me3' }) });
    expect(await api.createProfile('eldenring', 'New')).toMatchObject({ profileId: 'C:\\p\\New.me3', message: 'Created New' });
    expect(asked('launch_create_profile')).toEqual([{ name: 'New' }]);
  });

  it('duplicates sharing mods, then renames when the name differs from "<name> copy"', async () => {
    const copy = 'C:\\me3\\profiles\\Mine copy.me3';
    const named = 'C:\\me3\\profiles\\Coop.me3';
    const { api, asked } = await engine({
      launch_profiles: listed,
      mods_profile_block: () => ({ reason: '' }),
      mods_duplicate_profile: { job: 'j1', title: 'Copying', result: { profile: copy, name: 'Mine copy' } },
      mods_profile_name_check: () => ({ code: '', reason: '' }),
      mods_rename_profile: { job: 'j2', title: 'Renaming', result: { profile: named, name: 'Coop' }, undo: { type: 'rename' } },
    });
    const r = await api.createProfile('eldenring', 'Coop', ME3);
    expect(asked('mods_duplicate_profile')).toEqual([{ profile: ME3, kind: 'me3', source: ME3, share: true }]);
    expect(asked('mods_rename_profile')).toEqual([{ profile: copy, kind: 'me3', source: copy, name: 'Coop' }]);
    expect(r).toMatchObject({ profileId: named, message: 'Created Coop', entry: { undoable: true } });
  });

  it('renames after the block and name checks, and says why when they refuse', async () => {
    const rename = { job: 'j3', title: 'Renaming', result: { profile: 'C:\\p\\Co-op.me3', name: 'Co-op' } };
    const ok = await engine({ launch_profiles: listed, mods_profile_block: () => ({ reason: '' }), mods_profile_name_check: () => ({ code: '', reason: '' }), mods_rename_profile: rename });
    expect(await ok.api.renameProfile(ME3, 'Co-op')).toMatchObject({ message: 'Renamed Mine to Co-op' });
    expect(ok.asked('mods_rename_profile')).toEqual([{ profile: ME3, kind: 'me3', source: ME3, name: 'Co-op' }]);

    const blocked = await engine({ launch_profiles: listed, mods_profile_block: () => ({ reason: 'game-running' }) });
    await expect(blocked.api.renameProfile(ME3, 'x')).rejects.toMatchObject({ code: 'profile_blocked', message: 'Close the game first.' });
    const bad = await engine({ launch_profiles: listed, mods_profile_block: () => ({ reason: '' }), mods_profile_name_check: () => ({ code: 'invalid', reason: 'A name cannot contain a slash.' }) });
    await expect(bad.api.renameProfile(ME3, 'a/b')).rejects.toMatchObject({ code: 'invalid_name', message: 'A name cannot contain a slash.' });
    expect(bad.asked('mods_rename_profile')).toEqual([]);
  });

  it('deletes with the stamp the check gave', async () => {
    const { api, asked } = await engine({ launch_profiles: listed, mods_check_delete_profile: () => ({ name: 'Mine', keeps: '', stamp: [5, 6] }), mods_delete_profile: { job: 'j4', title: 'Deleting', result: { moved_to: 'x' } } });
    expect(await api.deleteProfile(ME3)).toMatchObject({ message: 'Deleted Mine' });
    expect(asked('mods_delete_profile')).toEqual([{ profile: ME3, kind: 'me3', source: ME3, expect: [5, 6] }]);
  });

  it('moves a profile in with the stamp, or says what refuses it', async () => {
    const move = { job: 'j5', title: 'Moving', result: { profile: 'C:\\in\\Mine.me3' } };
    const ok = await engine({ launch_profiles: listed, mods_profile_block: () => ({ reason: '' }), mods_check_move_in: () => ({ refusals: [], stamp: [1, 2] }), mods_move_in: move });
    expect(await ok.api.moveProfileIn(ME3)).toMatchObject({ message: "Moved Mine into Bayle's folder" });
    expect(ok.asked('mods_move_in')).toEqual([{ profile: ME3, kind: 'me3', source: ME3, expect: [1, 2] }]);
    const no = await engine({ launch_profiles: listed, mods_profile_block: () => ({ reason: '' }), mods_check_move_in: () => ({ refusals: ['A folder with that name is already there.'], stamp: null }) });
    await expect(no.api.moveProfileIn(ME3)).rejects.toMatchObject({ code: 'cannot_move_in', message: 'A folder with that name is already there.' });
  });
});

describe('launch', () => {
  it('maps the modes, checks first, and refuses with a sentence', async () => {
    const e = await engine({ launch_check: () => checked({ problems: [{ code: 'me3_missing', path: 'x', detail: '' }] }) });
    await expect(e.api.launch('eldenring', ME3, 'Profile')).rejects.toMatchObject({ code: 'cannot_launch', message: "Bayle can't find me3. Choose it in Settings." });
    expect(e.asked('launch_play')).toEqual([]);
    const running = await engine({ launch_check: () => checked({ game_running: true }) });
    await expect(running.api.launch('eldenring', ME3, 'Vanilla')).rejects.toMatchObject({ code: 'game_running' });
    expect(running.asked('launch_check')).toEqual([{ mode: 'vanilla', source: '' }]);
  });

  it('plays as a job, asks a question, sends the answer back, and ends with the job', async () => {
    const e = await engine({ launch_check: () => checked(), launch_play: () => ({ job_id: 'p1' }), answer_prompt: () => ({ ok: true }) });
    const done = e.api.launch('eldenring', ME3, 'Offline');
    await flush(); await flush();
    expect(e.asked('launch_play')).toEqual([{ mode: 'offline', source: ME3 }]);
    expect(useLaunchJob.getState().ref).toEqual({ epoch: 1, id: 'p1' });
    e.t.event({ seq: e.next(), type: 'started', job_id: 'p1', data: { title: 'Starting Elden Ring...', quiet: true } });
    e.t.event({ seq: e.next(), type: 'prompt', job_id: 'p1', data: { prompt_id: 'q1', kind: 'question', code: 'offline_confirm', facts: {}, options: [{ key: 'go', role: 'primary' }, { key: 'cancel', role: 'normal' }] } });
    await answerPrompt(e.g, 'q1', 'go');
    expect(e.asked('answer_prompt')).toEqual([{ prompt_id: 'q1', choice: 'go' }]);
    e.t.event({ seq: e.next(), type: 'finished', job_id: 'p1', data: { result: { mode: 'offline' } } });
    await expect(done).resolves.toBeUndefined();
    expect(useLaunchJob.getState().ref).toBeUndefined();
  });

  it('Stop asks the engine to cancel and Play ends as stopped', async () => {
    const e = await engine({ launch_check: () => checked(), launch_play: () => ({ job_id: 'p2' }), cancel_job: () => ({ id: 'p2', title: 'x', state: 'running' }) });
    const done = e.api.launch('eldenring', ME3, 'Profile');
    done.catch(() => {});
    await flush(); await flush();
    e.t.event({ seq: e.next(), type: 'started', job_id: 'p2', data: { title: 'Starting Elden Ring...', quiet: true } });
    await cancelJob(e.g, useLaunchJob.getState().ref!);
    expect(e.asked('cancel_job')).toEqual([{ job_id: 'p2' }]);
    e.t.event({ seq: e.next(), type: 'cancelled', job_id: 'p2', data: { error: { code: 'cancelled', message: 'Play was cancelled.' } } });
    await expect(done).rejects.toMatchObject({ code: 'cancelled' });
    expect(useLaunchJob.getState().ref).toBeUndefined();
  });
});

describe('desktop actions', () => {
  it('passes the pickers, open path and support logs to Rust, and maps the window buttons', async () => {
    const seen: unknown[] = [];
    const app: Partial<DesktopActions> = {
      pickFile: async (o) => { seen.push(['file', o]); return 'D:\\ER\\eldenring.exe'; },
      pickFolder: async (o) => { seen.push(['folder', o]); return null; },
      openPath: async (p) => { seen.push(['open', p]); },
      windowAction: async (a) => { seen.push(['window', a]); },
      saveSupportLogs: async () => 'C:\\logs.zip',
    };
    const { api } = await engine({}, app);
    const filters = [{ name: 'Game program', extensions: ['exe'] }];
    expect(await api.pickFile({ title: 'Game', filters })).toBe('D:\\ER\\eldenring.exe');
    expect(await api.pickFolder({ title: 'Folder' })).toBeNull();
    await api.openPath('C:\\x');
    await api.windowControl('maximize');
    await api.windowControl('minimize');
    expect(await api.saveSupportLogs()).toBe('C:\\logs.zip');
    expect(seen).toEqual([['file', { title: 'Game', filters }], ['folder', { title: 'Folder' }], ['open', 'C:\\x'], ['window', 'toggle_maximize'], ['window', 'minimize']]);
  });

  it('says "not connected yet" when Rust is not there', async () => {
    const { api } = await engine({});
    await expect(api.pickFile({ title: 'x' })).rejects.toMatchObject({ code: 'not_wired' });
    await expect(api.windowControl('close')).rejects.toMatchObject({ code: 'not_wired' });
  });
});

describe('invalidation mapping', () => {
  it('maps every name the engine sends to cache scopes, and ignores unknown ones', () => {
    const scopes = (what: string[]) => toBackendEvents({ epoch: 1, seq: 1, job_id: null, type: 'invalidated', data: { what } }).map((e) => e.type === 'changed' && e.scope);
    expect(Object.keys(INVALIDATES).sort()).toEqual(['game', 'pages', 'shell', 'updates']);
    expect(scopes(['shell'])).toEqual(['profiles', 'settings']);
    expect(scopes(['game'])).toEqual(['profiles', 'saves', 'settings']);
    expect(scopes(['updates', 'shell'])).toEqual(['settings', 'profiles']);
    expect(scopes(['nothing'])).toEqual([]);
  });
});
