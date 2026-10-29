/**
 * The Settings page and Activity Undo over the engine: getSettings, getDefaultSettings, updateSettings
 * (settings, settings_defaults, settings_set, settings_folder) and undo (activity_undo, a job).
 *
 * Moving the Profiles folder is its own pair (checkMoveProfiles, moveProfiles: settings_check_relocate + the relocate job).
 * Not connected (they reject with not_wired): Shared mods, Backups folder, Logs folder and Settings file (the engine's
 * rename-layout operations are not on the gateway allowlist yet),
 * clearBootBoostCache (no engine route) (checkForUpdates is adapters/appInfo.ts).
 */
import { awaitJob } from '@/data/engine';
import type { BayleApi } from '../../BayleApi';
import type { Settings, SettingsPatch } from '../../types';
import type { EngineActivityRecord } from '../gatewayApi';
import type { components } from '../engine.gen';
import type { Gateway } from '../hub';
import { GatewayError } from '../transport';
import { runJob, said } from './modsCommon';

// Operation ids stay local so three wiring batches don't all edit OPERATIONS in protocol.ts.
const OP = { activity: 'activity', undo: 'activity_undo', settings: 'settings', set: 'settings_set', folder: 'settings_folder', defaults: 'settings_defaults', checkRelocate: 'settings_check_relocate', relocate: 'settings_relocate' } as const;

const notWired = (what: string) => new GatewayError({ code: 'not_wired', message: `This part of Bayle isn't connected to the engine yet (${what}).` });

/* ------------------------------------------------------------------ engine shapes (modules/settings/models.py LauncherSettings, routers/settings.py) */

/** The fields of GET /v1/settings → settings (typed dict[str, Any] by the engine) that the UI reads. */
export interface EngineSettings {
  theme: 'dark' | 'tarnished' | 'light' | 'system';
  effects: 'full' | 'reduced' | 'off';
  launcher_channel: 'stable' | 'beta';
  play_update_merge: boolean; overhaul_install: boolean; play_boot_boost: boolean; play_show_logos: boolean; play_diagnostics: boolean;
  play_clear_before: boolean; play_clear_after: boolean; warn_dead_shells: boolean;
  offline_strip_overhaul: boolean; offline_start_steam: boolean; offline_skip_confirm: boolean;
  play_backup_before: boolean; play_repair_after: boolean; play_repair_after_eldenring: boolean;
  check_launcher_updates: boolean; check_me3_updates: boolean;
  backups_keep: number;
  me3_path: string; game_exe: string; me3_profile_dir: string; profiles_root: string | null;
}

export interface EngineSettingsPage extends Omit<components['schemas']['SettingsPage'], 'settings'> { settings: EngineSettings }

/* ------------------------------------------------------------------ the key table: UI setting → engine key */

type Group = 'launch' | 'saves' | 'appearance' | 'updates';
/** Settings that map one-to-one onto an engine key (SWITCH_KEYS and the schema in modules/settings/service.py). */
const KEYS: { [G in Group]: Record<string, keyof EngineSettings> } = {
  launch: {
    autoRebuild: 'play_update_merge', installOverhauls: 'overhaul_install', bootBoost: 'play_boot_boost', showLogos: 'play_show_logos', diagnostics: 'play_diagnostics',
    closeLeftoversBefore: 'play_clear_before', closeLeftoversAfter: 'play_clear_after', warnLeftovers: 'warn_dead_shells',
    offlineSkipOverhaul: 'offline_strip_overhaul', offlineStartSteam: 'offline_start_steam', offlineSkipConfirm: 'offline_skip_confirm',
  },
  saves: { backupBeforeLaunch: 'play_backup_before', keepCopies: 'backups_keep' },
  appearance: { theme: 'theme', effects: 'effects' },
  updates: { channel: 'launcher_channel', checkOnStart: 'check_launcher_updates', me3Notices: 'check_me3_updates' },
};
/** The one location the engine saves and the UI shows by itself (LOCATIONS in service.py); the game folder is handled per game below. */
const PATH_KEYS = { me3: 'me3_path' } as const;

/** The after-quit repair is per game: Elden Ring has its own key and is off by default (modules/launch/play.py repair_key). */
const repairKey = (game: string) => (game === 'eldenring' ? 'play_repair_after_eldenring' : 'play_repair_after');

/* ------------------------------------------------------------------ settings the engine has no counterpart for: kept in this browser */

interface LocalPrefs { density: Settings['appearance']['density']; saveKeepDays: number; logKeepDays: Settings['logs']['keepDays']; bayleTheme: boolean }
const LOCAL_DEFAULTS: LocalPrefs = { density: 'comfortable', saveKeepDays: 30, logKeepDays: 30, bayleTheme: false };
const LOCAL_KEY = 'bayle-ui-prefs';

// shortcut: per-browser prefs, not in the engine's settings file; move them there if the engine adds keys for them.
function readLocal(): LocalPrefs {
  try { return { ...LOCAL_DEFAULTS, ...(JSON.parse(localStorage.getItem(LOCAL_KEY) ?? '{}') as Partial<LocalPrefs>) }; } catch { return LOCAL_DEFAULTS; }
}
function writeLocal(patch: Partial<LocalPrefs>) {
  try { localStorage.setItem(LOCAL_KEY, JSON.stringify({ ...readLocal(), ...patch })); } catch { /* storage unavailable: the choice lasts until reload */ }
}

/* ------------------------------------------------------------------ engine → UI */

export function toSettings(p: EngineSettingsPage, settingsFolder: string | null, local: LocalPrefs = readLocal()): Settings {
  const s = p.settings;
  const path = (own: string, found: string | null | undefined) => own || found || '';
  return {
    paths: {
      // Games are the engine's keys; it holds the path of the current game only.
      games: { [p.game]: path(s.game_exe, p.detected.game_exe) },
      me3: path(s.me3_path, p.detected.me3_path),
      profiles: path(s.profiles_root ?? '', p.detected.me3_profile_dir),
      sharedMods: '', // shortcut: no single shared-mods path in the engine's settings, show one when the layout operations are wired
      backups: p.backups_folder,
      logs: '', // shortcut: the engine reports no logs path, show it when it does
      settingsFile: settingsFolder ?? '',
    },
    launch: Object.fromEntries(Object.entries(KEYS.launch).map(([ui, k]) => [ui, s[k]])) as unknown as Settings['launch'],
    saves: { repairAfterQuit: { [p.game]: s[repairKey(p.game)] }, backupBeforeLaunch: s.play_backup_before, keepCopies: s.backups_keep, keepDays: local.saveKeepDays },
    appearance: { theme: local.bayleTheme && s.theme === 'dark' ? 'bayle' : s.theme, effects: s.effects, density: local.density },
    updates: { channel: s.launcher_channel, checkOnStart: s.check_launcher_updates, me3Notices: s.check_me3_updates },
    logs: { keepDays: local.logKeepDays },
  };
}

/** A patch as [group, field, game?] paths with their values. */
function leaves(patch: SettingsPatch): { path: string[]; value: unknown }[] {
  const out: { path: string[]; value: unknown }[] = [];
  const walk = (o: unknown, path: string[]) => {
    if (o && typeof o === 'object') Object.entries(o).forEach(([k, v]) => walk(v, [...path, k]));
    else out.push({ path, value: o });
  };
  walk(patch, []);
  return out;
}

/* ------------------------------------------------------------------ the adapter */

export function settingsAdapter(gateway: Gateway): Partial<BayleApi> {
  const read = async () => {
    const [p, dir, shell] = await Promise.all([gateway.call<EngineSettingsPage>(OP.settings), gateway.call<components['schemas']['FolderPath']>(OP.folder, { kind: 'settings' }), gateway.app?.info?.()]);
    const settings = toSettings(p, dir.path);
    // The desktop app keeps its own update channel (the engine's launcher_channel is Qt's); the preview shows the engine's.
    if (shell?.channel === 'stable' || shell?.channel === 'beta') settings.updates.channel = shell.channel;
    return { p, settings };
  };
  const set = (key: string, value: boolean | number | string) => gateway.call(OP.set, { key, value });

  return {
    async getSettings() { return (await read()).settings; },

    async getDefaultSettings() {
      const [p, d] = await Promise.all([gateway.call<EngineSettingsPage>(OP.settings), gateway.call<{ settings: EngineSettings }>(OP.defaults)]);
      return toSettings({ ...p, settings: d.settings, detected: {} }, null, LOCAL_DEFAULTS);
    },

    // One engine call per changed setting; values equal to the current ones are skipped, so "reset all" sends only what differs.
    async updateSettings(patch) {
      const { p, settings: now } = await read();
      const cur = now as unknown as Record<string, Record<string, unknown>>;
      for (const { path, value } of leaves(patch)) {
        const [g, f, game] = path as [string, string, string | undefined];
        const had = game ? (cur[g]?.[f] as Record<string, unknown> | undefined)?.[game] : cur[g]?.[f];
        if (had === value) continue;
        const v = value as boolean | number | string;
        if (g === 'appearance' && f === 'theme') {
          // 'bayle' is a UI-only look on the engine's dark theme.
          writeLocal({ bayleTheme: v === 'bayle' });
          await set('theme', v === 'bayle' ? 'dark' : v);
        } else if (g === 'appearance' && f === 'density') writeLocal({ density: v as LocalPrefs['density'] });
        else if (g === 'saves' && f === 'keepDays') writeLocal({ saveKeepDays: v as number });
        else if (g === 'logs' && f === 'keepDays') writeLocal({ logKeepDays: v as LocalPrefs['logKeepDays'] });
        else if (g === 'saves' && f === 'repairAfterQuit') {
          // shortcut: the engine saves this for the current game only; switching game first is the way to set another.
          if (game !== p.game) throw notWired('repair after quitting for another game');
          await set('play_repair_after', v);
        } else if (g === 'paths' && f === 'games') {
          if (game !== p.game) throw notWired('the game folder of another game');
          await set('game_exe', v);
        } else if (g === 'updates' && f === 'channel' && gateway.app?.setChannel) await gateway.app.setChannel(v as 'stable' | 'beta');
        else if (g === 'paths' && f in PATH_KEYS) await set(PATH_KEYS[f as keyof typeof PATH_KEYS], v);
        else if (KEYS[g as Group]?.[f]) await set(KEYS[g as Group][f]!, v);
        // the profiles folder moves through moveProfiles (it needs a confirm); shared mods is the layout rename; backups, logs and the settings file are fixed
        else throw notWired(`${g}.${f}`); // profiles, shared mods, backups, logs, settings file
      }
      return (await read()).settings;
    },

    async checkMoveProfiles(folder) {
      const f = await gateway.call<components['schemas']['RelocateFacts']>(OP.checkRelocate, { folder }).catch((e) => { throw said(e); });
      return { profiles: f.profiles, size: f.size, free: f.free };
    },

    async moveProfiles(folder) {
      // expect_root: the folder this move is from as the engine stores it, so a change made meanwhile is refused as stale
      const { settings } = await gateway.call<EngineSettingsPage>(OP.settings);
      const { entry } = await runJob(gateway, OP.relocate, { folder, expect_root: settings.profiles_root ?? '' }, 'profile');
      return { entry, message: `Moved the profiles to ${folder}`, detail: 'Every file was copied and checked before the old folder was removed.' };
    },

    // shortcut: the cache is me3's own and the engine neither knows where me3 keeps it nor has a route to clear it; needs that read of me3 first.
    async clearBootBoostCache() { throw notWired('clearBootBoostCache'); },

    /** activity_undo takes the entry's whole `undo` record as `expect`; the engine refuses it as stale when it changed meanwhile. */
    async undo(entryId) {
      const list = await gateway.call<{ jobs: EngineActivityRecord[] }>(OP.activity);
      const rec = list.jobs.find((j) => j.id === entryId);
      if (!rec?.undo || rec.undone) throw new GatewayError({ code: 'not_undoable', message: 'This can no longer be undone.' });
      const epoch = gateway.current()?.epoch;
      if (epoch === undefined) throw new GatewayError({ code: 'engine_unavailable', message: "Bayle's engine isn't ready." });
      const { job_id } = await gateway.call<components['schemas']['Started']>(OP.undo, { job_id: entryId, expect: rec.undo }, { epoch });
      const job = await awaitJob({ epoch, id: job_id });
      return { message: (job.result as { said?: string } | undefined)?.said || 'Undone' };
    },
  };
}
