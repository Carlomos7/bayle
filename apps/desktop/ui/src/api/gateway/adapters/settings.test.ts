import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { connectEngine, resetEngineState } from '@/data/engine';
import { createGateway } from '../hub';
import { fakeTransport, flush } from '../fakeTransport.test-util';
import { createGatewayApi } from '../gatewayApi';
import type { EngineSettings, EngineSettingsPage } from './settings';

const settle = async () => { await flush(); await flush(); };

const engineSettings: EngineSettings = {
  theme: 'dark', effects: 'full', launcher_channel: 'beta',
  play_update_merge: true, overhaul_install: true, play_boot_boost: true, play_show_logos: false, play_diagnostics: false,
  play_clear_before: true, play_clear_after: false, warn_dead_shells: true,
  offline_strip_overhaul: false, offline_start_steam: true, offline_skip_confirm: false,
  play_backup_before: true, play_repair_after: true, play_repair_after_eldenring: false,
  check_launcher_updates: true, check_me3_updates: false, backups_keep: 12,
  me3_path: '', game_exe: 'D:\\ER\\eldenring.exe', me3_profile_dir: '', profiles_root: null,
};
const page: EngineSettingsPage = { game: 'eldenring', settings: engineSettings, detected: { me3_path: 'C:\\me3\\me3.exe', me3_profile_dir: 'C:\\me3\\profiles' }, backups_folder: 'C:\\data\\saves', overhaul: '', layout: {}, me3_profiles: null, specs: [], steam_options: '', steam_target: '' };

/** A gateway over the fake transport where the named operations answer with the given values. */
function setup(replies: Record<string, unknown> = {}) {
  const t = fakeTransport({ state: 'ready', epoch: 1 });
  const g = createGateway(t);
  const off = connectEngine(g, new QueryClient());
  const call = t.call.bind(t);
  t.call = (async (op: string, params?: Record<string, unknown>, o?: { epoch?: number }) => {
    if (op in replies) { t.calls.push({ operation: op, params, epoch: o?.epoch }); return replies[op]; }
    return call(op, params, o);
  }) as typeof t.call;
  return { t, api: createGatewayApi(g), off };
}
const asked = (t: ReturnType<typeof setup>['t'], op: string) => t.calls.filter((c) => c.operation === op).map((c) => c.params);
const settingsReplies = { settings: page, settings_folder: { path: null }, settings_set: {} };

// The tests run in node: a small in-memory localStorage.
beforeEach(() => {
  resetEngineState();
  const store = new Map<string, string>();
  vi.stubGlobal('localStorage', { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) });
});
afterEach(() => { resetEngineState(); vi.unstubAllGlobals(); });

describe('settings over the engine', () => {
  it('reads the page and the settings folder, and maps the keys to the UI settings', async () => {
    const { t, api, off } = setup({ settings: page, settings_folder: { path: 'C:\\data' } });
    await settle();
    const s = await api.getSettings();
    expect(asked(t, 'settings_folder')).toEqual([{ kind: 'settings' }]);
    expect(s.launch).toMatchObject({ autoRebuild: true, installOverhauls: true, closeLeftoversAfter: false, warnLeftovers: true, offlineStartSteam: true });
    expect(s.saves).toMatchObject({ backupBeforeLaunch: true, keepCopies: 12, repairAfterQuit: { eldenring: false } });
    expect(s.updates).toEqual({ channel: 'beta', checkOnStart: true, me3Notices: false });
    expect(s.appearance).toEqual({ theme: 'dark', effects: 'full', density: 'comfortable' });
    expect(s.paths).toMatchObject({ games: { eldenring: 'D:\\ER\\eldenring.exe' }, me3: 'C:\\me3\\me3.exe', profiles: 'C:\\me3\\profiles', backups: 'C:\\data\\saves', settingsFile: 'C:\\data' });
    off();
  });

  it('sends one settings_set per changed setting, skipping values that are the same', async () => {
    const { t, api, off } = setup(settingsReplies);
    await settle();
    await api.updateSettings({ launch: { autoRebuild: false, bootBoost: true }, saves: { keepCopies: 30 }, updates: { channel: 'stable' }, paths: { me3: 'D:\\me3.exe' } });
    expect(asked(t, 'settings_set')).toEqual([
      { key: 'play_update_merge', value: false },
      { key: 'backups_keep', value: 30 },
      { key: 'launcher_channel', value: 'stable' },
      { key: 'me3_path', value: 'D:\\me3.exe' },
    ]);
    off();
  });

  it('reads and saves the update channel in the desktop app, not the engine', async () => {
    const t = fakeTransport({ state: 'ready', epoch: 1 });
    const setChannel = vi.fn(async () => {});
    Object.assign(t, { app: { info: async () => ({ version: '6.0.0-beta.1', channel: 'stable', dataFolder: '', platform: 'windows' }), setChannel } });
    const call = t.call.bind(t);
    t.call = (async (op: string, params?: Record<string, unknown>, o?: { epoch?: number }) => {
      if (op in settingsReplies) { t.calls.push({ operation: op, params, epoch: o?.epoch }); return settingsReplies[op as keyof typeof settingsReplies]; }
      return call(op, params, o);
    }) as typeof t.call;
    const g = createGateway(t);
    const off = connectEngine(g, new QueryClient());
    const api = createGatewayApi(g);
    await settle();
    expect((await api.getSettings()).updates.channel).toBe('stable');
    await api.updateSettings({ updates: { channel: 'beta' } });
    expect(setChannel).toHaveBeenCalledWith('beta');
    expect(t.calls.filter((c) => c.operation === 'settings_set')).toEqual([]);
    off();
  });

  it('saves the repair switch and the game folder for the current game only', async () => {
    const { t, api, off } = setup(settingsReplies);
    await settle();
    await api.updateSettings({ saves: { repairAfterQuit: { eldenring: true } }, paths: { games: { eldenring: 'E:\\ER\\eldenring.exe' } } } as never);
    expect(asked(t, 'settings_set')).toEqual([{ key: 'play_repair_after', value: true }, { key: 'game_exe', value: 'E:\\ER\\eldenring.exe' }]);
    await expect(api.updateSettings({ saves: { repairAfterQuit: { nightreign: false } } } as never)).rejects.toMatchObject({ code: 'not_wired' });
    off();
  });

  it('keeps UI-only settings in this browser, and Bayle as a look on the dark theme', async () => {
    const { t, api, off } = setup(settingsReplies);
    await settle();
    await api.updateSettings({ appearance: { density: 'compact', theme: 'bayle' }, saves: { keepDays: 90 }, logs: { keepDays: 7 } });
    expect(asked(t, 'settings_set')).toEqual([{ key: 'theme', value: 'dark' }]);
    // 'bayle' reads back while the engine says dark
    const s = await api.getSettings();
    expect(s.appearance).toMatchObject({ theme: 'bayle', density: 'compact' });
    expect(s.saves.keepDays).toBe(90);
    expect(s.logs.keepDays).toBe(7);
    off();
  });

  it('leaves folder changes as a plain setting and the boot boost cache not connected', async () => {
    const { t, api, off } = setup(settingsReplies);
    await settle();
    await expect(api.updateSettings({ paths: { profiles: 'D:\\profiles' } })).rejects.toMatchObject({ code: 'not_wired' });
    await expect(api.clearBootBoostCache()).rejects.toMatchObject({ code: 'not_wired' });
    expect(asked(t, 'settings_set')).toEqual([]);
    off();
  });

  it('moves the Profiles folder: the facts first, then the relocate job from the folder the engine stores', async () => {
    const { t, api, off } = setup({
      settings: { ...page, settings: { ...engineSettings, profiles_root: 'C:\\old' } },
      settings_check_relocate: { folder: 'D:\\profiles', profiles: 3, size: 2 ** 30, free: null },
      settings_relocate: { job_id: 'm1' },
    });
    await settle();
    expect(await api.checkMoveProfiles('D:\\profiles')).toEqual({ profiles: 3, size: 2 ** 30, free: null });
    const done = api.moveProfiles('D:\\profiles');
    await settle();
    expect(asked(t, 'settings_relocate')).toEqual([{ folder: 'D:\\profiles', expect_root: 'C:\\old' }]);
    t.event({ seq: 1, type: 'started', job_id: 'm1', data: { title: 'Moving profiles and mods...' } });
    t.event({ seq: 2, type: 'finished', job_id: 'm1', data: { result: { undo: { type: 'layout-relocate' } }, undo: null } });
    expect(await done).toMatchObject({ message: 'Moved the profiles to D:\\profiles', entry: { undoable: true } });
    off();
  });

  it('answers the defaults from the engine defaults', async () => {
    // A fresh settings file, as settings_defaults reports it (not the page's own, changed values).
    const fresh: EngineSettings = { ...engineSettings, launcher_channel: 'stable', overhaul_install: false, play_backup_before: false, play_clear_after: true, check_me3_updates: true, backups_keep: 20, game_exe: '' };
    const { t, api, off } = setup({ settings: page, settings_defaults: { settings: fresh } });
    await settle();
    const d = await api.getDefaultSettings();
    expect(asked(t, 'settings_defaults')).toEqual([undefined]);
    expect(d.launch.installOverhauls).toBe(false);
    expect(d.saves).toMatchObject({ keepCopies: 20, repairAfterQuit: { eldenring: false } });
    expect(d.updates.channel).toBe('stable');
    expect(d.appearance.density).toBe('comfortable');
    off();
  });
});

describe('Undo over the engine', () => {
  const undo = { type: 'rebuild', folder: 'x' };

  it('starts activity_undo with the whole undo record, waits for the job and reports what it said', async () => {
    const { t, api, off } = setup({ activity: { jobs: [{ id: 'a1', undo }], unseen: 0 }, activity_undo: { job_id: 'j7' } });
    await settle();
    const done = api.undo('a1');
    await settle();
    expect(t.calls.find((c) => c.operation === 'activity_undo')).toMatchObject({ params: { job_id: 'a1', expect: undo }, epoch: 1 });
    t.event({ seq: 1, type: 'started', job_id: 'j7', data: { title: 'Undoing…' } });
    t.event({ seq: 2, type: 'finished', job_id: 'j7', data: { result: { said: 'The merged data is back as it was.' } } });
    const r = await done;
    expect(r.message).toBe('The merged data is back as it was.');
    expect(r.entry).toBeUndefined();
    off();
  });

  it('rejects with the engine code when the undo job fails', async () => {
    const { t, api, off } = setup({ activity: { jobs: [{ id: 'a1', undo }], unseen: 0 }, activity_undo: { job_id: 'j8' } });
    await settle();
    const done = api.undo('a1');
    await settle();
    t.event({ seq: 1, type: 'started', job_id: 'j8', data: { title: 'Undoing…' } });
    t.event({ seq: 2, type: 'failed', job_id: 'j8', data: { error: { code: 'stale', message: 'Things changed since you were asked.' } } });
    await expect(done).rejects.toMatchObject({ code: 'stale' });
    off();
  });

  it('does not call the engine for an entry that has nothing to undo', async () => {
    const { t, api, off } = setup({ activity: { jobs: [{ id: 'a1' }, { id: 'a2', undo, undone: true }], unseen: 0 } });
    await settle();
    await expect(api.undo('a1')).rejects.toMatchObject({ code: 'not_undoable' });
    await expect(api.undo('a2')).rejects.toMatchObject({ code: 'not_undoable' });
    expect(asked(t, 'activity_undo')).toEqual([]);
    off();
  });
});
