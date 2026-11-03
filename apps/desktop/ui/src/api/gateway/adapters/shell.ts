/**
 * The app shell over the engine and Rust: games, profiles, Launch, and the desktop actions.
 *
 * Ids: GameId is the engine's game key ("eldenring"); ProfileId is a profile's `source` (its .me3 path for a normal
 * profile). The engine works on one current game, so the profile calls act on that game whatever `gameId` they get.
 *
 * Profile edits follow the engine's pattern: a read of what blocks the edit, then the job (rename, duplicate, move in,
 * delete), with the stamp a check gave as `expect` where the engine wants one. Jobs are awaited with awaitJob.
 *
 * Launch: `launch_check` first (so a refusal is a sentence), then `launch_play` as a job. The job asks questions
 * (prompt events, answered by LaunchPrompt through `answer_prompt`) and ends when Play is done; Stop is `cancel_job`
 * (the top bar). The job ref is kept in useLaunchJob so the UI can find it, because the engine marks Play quiet.
 *
 * Not connected (reject with not_wired): takeOverInstaller.
 */
import { awaitJob, useLaunchJob } from '@/data/engine';
import type { BayleApi } from '../../BayleApi';
import type { ActivityEntry, Game, LaunchMode, Profile, ProfileSummary } from '../../types';
import type { components } from '../engine.gen';
import type { Gateway } from '../hub';
import { GatewayError } from '../transport';
import { readMods } from './modsCommon';

// Operation ids stay local so the wiring batches don't all edit OPERATIONS in protocol.ts.
const OP = {
  games: 'games', selectGame: 'games_select',
  profiles: 'launch_profiles', setProfile: 'launch_set_profile', createProfile: 'launch_create_profile',
  check: 'launch_check', play: 'launch_play',
  block: 'mods_profile_block', nameCheck: 'mods_profile_name_check', rename: 'mods_rename_profile', duplicate: 'mods_duplicate_profile',
  checkMoveIn: 'mods_check_move_in', moveIn: 'mods_move_in', checkDelete: 'mods_check_delete_profile', delete: 'mods_delete_profile',
} as const;

/* ------------------------------------------------------------------ engine shapes (routers/games.py, routers/launch.py, routers/mods.py) */

type S = components['schemas'];
export type EngineGame = S['GameItem'];
type EngineProblem = S['LaunchProblem'];
export type EngineLaunchProfile = S['LaunchProfile'];
type EngineChecked = S['LaunchChecked'];
/** How the engine addresses a profile in the mods routes. */
interface ProfileRef { profile: string; kind: string; source: string }

const MODES: Record<LaunchMode, 'profile' | 'offline' | 'vanilla'> = { Profile: 'profile', Offline: 'offline', Vanilla: 'vanilla' };

const notWired = (what: string) => new GatewayError({ code: 'not_wired', message: `This part of Bayle isn't connected to the engine yet (${what}).` });
const problem = (code: string, message: string) => new GatewayError({ code, message });

/* ------------------------------------------------------------------ words for what the engine reports as codes */

/** Why Play can't start (LaunchProblem.code, modules/launch/play.py). */
function playProblem(p: EngineProblem): string {
  switch (p.code) {
    case 'profile_missing': return "The profile's file is missing.";
    case 'wrong_game': return `That profile is for another game (${p.detail}).`;
    case 'unfinished': return `The profile isn't finished: ${p.detail}`;
    case 'me3_missing': return "Bayle can't find me3. Choose it in Settings.";
    case 'me3_not_installed': return 'me3 is not installed yet.';
    case 'game_exe_missing': return "Bayle can't find the game's program. Choose it in Settings.";
    case 'game_exe_setting_missing': return "The game program chosen in Settings isn't there any more.";
    case 'mod_folder_missing': return `A mod folder is missing (${p.detail}).`;
    default: return p.detail || `Play can't start (${p.code}).`;
  }
}

/** mods_profile_block's reason. */
const BLOCKS: Record<string, string> = {
  'no-profile': "That profile isn't there any more.",
  managed: "An overhaul's installer runs this profile, so it can't be changed here.",
  busy: 'Bayle is busy with something else. Try again when it is done.',
  'game-running': 'Close the game first.',
};

/** mods_profile_name_check's code. */
const NAMES: Record<string, string> = { no_profile: "That profile isn't there any more.", empty: 'Type a name for the profile.' };

/** One-letter-per-word badge: "Elden Ring" is ER; a one-word name takes its first two letters. */
function abbr(name: string): string {
  const words = name.split(/\s+/).filter(Boolean);
  return (words.length > 1 ? words.slice(0, 3).map((w) => w[0]).join('') : name.slice(0, 2)).toUpperCase();
}

export const toGame = (g: EngineGame): Game => ({
  id: g.key,
  name: g.name,
  abbr: abbr(g.name),
  supported: g.ready,
  ...(g.last_run_build ? { lastRunBuild: g.last_run_build } : {}),
  ...(g.profile ? { activeProfileId: g.profile } : {}),
  ...(g.installed ? { installFolder: g.installed } : {}),
  current: g.current,
  slotsPerSave: 10, // shortcut: Elden Ring's; the games route reports no slot count, upgrade when it does.
});

/* ------------------------------------------------------------------ the adapter */

export function shellApi(gateway: Gateway): Partial<BayleApi> {
  const call = <T>(operation: string, params?: Record<string, unknown>) => gateway.call<T>(operation, params);

  /** Start a job and wait for it; the ActionResult's entry is the Activity row the job made. */
  async function runJob(operation: string, params: Record<string, unknown>): Promise<{ result: unknown; entry: ActivityEntry }> {
    const epoch = gateway.current()?.epoch;
    if (epoch === undefined) throw problem('engine_unavailable', "Bayle's engine isn't ready.");
    const { job_id } = await gateway.call<{ job_id: string }>(operation, params, { epoch });
    const job = await awaitJob({ epoch, id: job_id });
    const now = new Date();
    const entry: ActivityEntry = {
      id: job.id, gameId: '', kind: 'profile', ok: true, title: job.title, detail: '', day: 'Today',
      time: now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false }),
      duration: '', hasLog: true, undoable: !!job.undo,
    };
    return { result: job.result, entry };
  }

  /** The name people see: the engine names an me3 profile by its file. */
  const shown = (name: string) => name.replace(/\.me3$/i, '');
  const profileList = async () => (await call<S['LaunchProfiles']>(OP.profiles)).profiles;

  /** The engine's way of naming the profile, found from its id (`source`). */
  async function refOf(profileId: string): Promise<ProfileRef & { name: string }> {
    const p = (await profileList()).find((x) => x.source === profileId);
    if (!p) throw problem('not_found', "That profile isn't there any more.");
    return { profile: p.profile, kind: p.kind, source: p.source, name: p.name };
  }

  /** Rename, duplicate and move in are refused while the profile is run by an installer, a job is running or the game is. */
  async function unblocked(profileId: string) {
    const { name, ...ref } = await refOf(profileId);
    const { reason } = await call<S['ProfileBlock']>(OP.block, ref);
    if (reason) throw problem('profile_blocked', BLOCKS[reason] ?? "This profile can't be changed right now.");
    return { ref, name };
  }

  const rename = async (ref: ProfileRef, name: string) => {
    const { code, reason } = await call<S['NameCheck']>(OP.nameCheck, { ...ref, name });
    if (code) throw problem('invalid_name', NAMES[code] ?? (reason || 'That name can not be used.'));
    return runJob(OP.rename, { ...ref, name });
  };

  return {
    async getGames() {
      return (await call<S['GamesPage']>(OP.games)).games.map(toGame);
    },

    async selectGame(gameId) {
      await call(OP.selectGame, { key: gameId });
    },

    // shortcut: the engine lists the current game's profiles only; the UI asks for the current game's, so gameId is not checked.
    async listProfiles(gameId) {
      // One mods read per profile (the same count getProfile gives); a profile that can't be read shows 0.
      return Promise.all((await profileList()).map(async (p): Promise<ProfileSummary> => {
        const mods = await readMods(gateway, p.source).catch(() => []);
        return { id: p.source, gameId, name: shown(p.name), modCount: mods.length, enabledCount: mods.filter((m) => m.enabled).length };
      }));
    },

    async getProfile(profileId) {
      const p = (await profileList()).find((x) => x.source === profileId);
      if (!p) throw problem('not_found', "That profile isn't there any more.");
      const [mods, { games }] = await Promise.all([readMods(gateway, profileId), call<S['GamesPage']>(OP.games)]);
      const enabled = mods.filter((m) => m.enabled).length;
      // shortcut: the mods page has no merge state, save, online consent or installer footprint; upgrade with engine routes for them.
      return { id: p.source, gameId: games.find((g) => g.current)?.key ?? '', name: shown(p.name), modCount: mods.length, enabledCount: enabled, merge: 'none', onlineAccepted: false, mods } satisfies Profile;
    },

    async setActiveProfile(_gameId, profileId) {
      await call(OP.setProfile, { source: profileId });
    },

    async createProfile(_gameId, name, copyFrom) {
      if (!copyFrom) {
        const { profile } = await call<S['ProfileCreated']>(OP.createProfile, { name });
        return { message: `Created ${name}`, profileId: profile };
      }
      const from = await unblocked(copyFrom);
      // The dialog promises "shared mods stay shared", so ask the engine to share the game-file mods.
      const copy = await runJob(OP.duplicate, { ...from.ref, share: true });
      const made = copy.result as { profile: string; name: string };
      if (made.name === name) return { entry: copy.entry, message: `Created ${name}`, detail: `Copied from ${from.name}`, profileId: made.profile };
      const renamed = await rename({ profile: made.profile, kind: 'me3', source: made.profile }, name);
      return { entry: renamed.entry, message: `Created ${name}`, detail: `Copied from ${from.name}`, profileId: (renamed.result as { profile: string }).profile };
    },

    async renameProfile(profileId, name) {
      const { ref, name: was } = await unblocked(profileId);
      const { result, entry } = await rename(ref, name);
      return { entry, message: `Renamed ${was} to ${(result as { name: string }).name}` };
    },

    async deleteProfile(profileId) {
      const { profile, kind, source } = await refOf(profileId);
      const params = { profile, kind, source };
      const plan = await call<S['DeletePlan']>(OP.checkDelete, params);
      const { entry } = await runJob(OP.delete, { ...params, expect: plan.stamp });
      return { entry, message: `Deleted ${plan.name}`, detail: plan.keeps ? `${plan.keeps} keeps its shared files.` : 'It is in Deleted profiles; restore it from Activity.' };
    },

    async moveProfileIn(profileId) {
      const { ref, name } = await unblocked(profileId);
      const plan = await call<S['FolderPlan']>(OP.checkMoveIn, ref);
      if (plan.refusals.length) throw problem('cannot_move_in', plan.refusals[0]!);
      const { entry } = await runJob(OP.moveIn, { ...ref, expect: plan.stamp });
      return { entry, message: `Moved ${name} into Bayle's folder` };
    },

    async launch(_gameId, profileId, mode) {
      const way = MODES[mode];
      const source = mode === 'Vanilla' ? '' : profileId;
      const got = await call<EngineChecked>(OP.check, { mode: way, source });
      if (got.game_running) throw problem('game_running', 'The game is already running.');
      if (got.busy) throw problem('busy', 'Bayle is busy with something else. Try again when it is done.');
      if (!got.installed) throw problem('not_installed', "Bayle can't find the game on this PC.");
      if (got.problems.length) throw problem('cannot_launch', playProblem(got.problems[0]!));
      const epoch = gateway.current()?.epoch;
      if (epoch === undefined) throw problem('engine_unavailable', "Bayle's engine isn't ready.");
      const { job_id } = await gateway.call<S['JobStarted']>(OP.play, { mode: way, source }, { epoch });
      useLaunchJob.setState({ ref: { epoch, id: job_id } });
      try {
        await awaitJob({ epoch, id: job_id });
      } finally {
        useLaunchJob.setState({ ref: undefined });
      }
    },

    /* ---------------------------------------------------------------- desktop (Rust commands, not the engine) */

    async pickFile(opts) {
      if (!gateway.app?.pickFile) throw notWired('pickFile');
      return gateway.app.pickFile(opts);
    },
    async pickFolder(opts) {
      if (!gateway.app?.pickFolder) throw notWired('pickFolder');
      return gateway.app.pickFolder(opts);
    },
    async openPath(path) {
      if (!gateway.app?.openPath) throw notWired('openPath');
      await gateway.app.openPath(path);
    },
    async windowControl(action) {
      if (!gateway.app?.windowAction) throw notWired('windowControl');
      await gateway.app.windowAction(action === 'maximize' ? 'toggle_maximize' : action);
    },
    async isMaximized() {
      return (await gateway.app?.windowMaximized?.()) ?? false;
    },
    async openLogs() {
      if (!gateway.app) throw notWired('openLogs');
      await gateway.app.openLogs();
    },
    async saveSupportLogs() {
      if (!gateway.app?.saveSupportLogs) throw notWired('saveSupportLogs');
      return gateway.app.saveSupportLogs();
    },
  };
}

/** Answer a Play question: the key of one of its options, or "cancel". */
export function answerPrompt(gateway: Gateway, promptId: string, choice: string): Promise<unknown> {
  return gateway.call('answer_prompt', { prompt_id: promptId, choice });
}
