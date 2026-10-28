/**
 * Domain types shared by the UI and the backend.
 *
 * These are the shapes the backend sends and receives. They are plain JSON
 * (no classes, no Dates: times are display strings or ISO strings), so any
 * transport can carry them: pywebview, Qt WebChannel, HTTP, Tauri.
 */

export type GameId = string;
export type ProfileId = string;
export type ModId = string;
export type SaveId = string;
export type CopyId = string;
export type ActivityId = string;
export type ConfigFileId = string;
export type SetupId = string;

/** Colour role for tags and chips. The UI maps these to theme colours. */
export type Tone = 'neutral' | 'accent' | 'info' | 'vio' | 'ok' | 'warn' | 'bad';

export interface Tag {
  label: string;
  tone?: Tone;
}

/* ------------------------------------------------------------------ games */

export interface Game {
  id: GameId;
  name: string;
  /** Two or three letters for badges, e.g. "ER". */
  abbr: string;
  /** False for games Bayle knows about but cannot mod yet. */
  supported: boolean;
  /** The game's current build, read from the executable. */
  build?: string;
  /** The build when this game was last launched through Bayle. */
  lastRunBuild?: string;
  /** Profile that Launch uses for this game. */
  activeProfileId?: ProfileId;
  /** e.g. "last played today, 00:38" */
  lastPlayed?: string;
  installFolder?: string;
  /** Character slots per save file (Elden Ring: 10). */
  slotsPerSave: number;
}

/* ------------------------------------------------------------------ profiles + mods */

export type ModKind = 'package' | 'native';
export type MergeState = 'none' | 'ok' | 'needs';

export interface LoadAfter {
  packageId: string;
  optional: boolean;
}

export interface NativeOptions {
  /** me3 load_early */
  loadEarly: boolean;
  /** Game starts even if this DLL fails. */
  optional: boolean;
  initializer: { kind: 'none' | 'function' | 'delay'; value: string };
  finalizer: string;
  /**
   * After a game update: does this DLL still find what it hooks into?
   * 'ok' when its signatures match the new exe, 'may-fail' when they don't, 'unknown' when Bayle has no
   * evidence for this DLL on this build. Unknown is a real answer, shown as such.
   */
  afterUpdate?: 'ok' | 'may-fail' | 'unknown';
}

export interface Mod {
  id: ModId;
  /** Name other mods use in load_after / load_before. */
  packageId: string;
  name: string;
  kind: ModKind;
  enabled: boolean;
  /** Its folder is gone; Launch leaves it out. */
  missing?: boolean;
  version?: string;
  /** A picture for the mod, when Bayle has one (for example from its page). The UI shows a placeholder until then. */
  thumbnail?: string;
  folder: string;
  size: string;
  addedOn: string;
  /** One line under the name, e.g. "Changes item text". */
  description: string;
  tags: Tag[];
  /** Settings files attached to this mod, shown on Mod Configs. */
  configs: string[];
  /** Lives in the shared library and is used by more than one profile. */
  shared?: boolean;
  /** Set when this mod is an overhaul with a saved setup. */
  setupId?: SetupId;
  /** Overhauls: its rebuild tool merges the mods above it, so it must load last. */
  staysLast?: boolean;
  rebuildFile?: string;
  loadAfter: LoadAfter[];
  /** Another mod that ships the same files and loads later. */
  overriddenBy?: ModId;
  overriddenFiles?: number;
  /** Part of an overhaul, e.g. its DLL. */
  partOfSetupId?: SetupId;
  /** Natives: the DLL's file name, e.g. ersc.dll. The name above is what people call it. */
  file?: string;
  /** Natives: the package mod this DLL came with, e.g. Seamless Co-op for ersc.dll. */
  partOfModId?: ModId;
  /**
   * Where the name came from, so the UI can say how sure it is:
   * 'install' it came in the same download as a named mod; 'file-details' the DLL's own product name;
   * 'known' Bayle's list of well-known DLLs; 'you' renamed by the player; 'file' nothing better, so the file name.
   */
  nameSource?: 'install' | 'file-details' | 'known' | 'you' | 'file';
  /** Natives: what the DLL says about itself in its Windows file details, when it says anything. */
  fileDetails?: { product?: string; description?: string };
  /** Put there by an overhaul's own installer, not by Bayle. */
  installerMade?: boolean;
  native?: NativeOptions;
  /** A newer release is available, with what it would change. */
  update?: ModUpdate;
}

export interface ModUpdate {
  version: string;
  /** e.g. "Oct 20" */
  releasedOn: string;
  /** Pieces that differ from the installed version, by family. */
  changes: { family: FileFamily; count: number; unit: string }[];
  /** Your picks that touch a changed piece. */
  touchesPicks: number;
  /** New clashes it would cause with your other mods. */
  newClashes: number;
  notes?: string;
}

export interface InstallerFootprint {
  name: string;
  entries: { title: string; detail: string }[];
  settings: { title: string; detail: string; kept?: boolean }[];
  leftovers: { title: string; detail: string }[];
}

export interface ProfileSummary {
  id: ProfileId;
  gameId: GameId;
  name: string;
  modCount: number;
  enabledCount: number;
}

export interface Profile extends ProfileSummary {
  /** Save file this profile launches with. */
  saveId?: SaveId;
  merge: MergeState;
  /** Folder outside Bayle's own, if the profile lives elsewhere. */
  outsidePath?: string;
  /** Folders beside an outside profile that it does not use. */
  strays?: string[];
  /** The user accepted the online warning for this profile. */
  onlineAccepted: boolean;
  /** An overhaul installer changed this profile. */
  installer?: InstallerFootprint;
  /** Packages first, then natives, each in load order. */
  mods: Mod[];
}

/** One file inside a mod's folder, for the Files tab. */
export interface ModFile {
  /** Path inside the mod folder, backslash separated. */
  path: string;
  /** What the file is, in plain words. */
  what: string;
  /** The DLL me3 injects, for natives. */
  main?: boolean;
  /** A clash with another mod. */
  clash?: { tone: 'warn' | 'ok'; note: string };
}

/* ------------------------------------------------------------------ install */

export interface InstallSource {
  /** Absolute path to a .zip/.7z/.rar, a .dll, or a folder. */
  path: string;
}

export interface InstallPreview {
  source: string;
  detectedAs: 'package' | 'native' | 'overhaul';
  name: string;
  version?: string;
  items: { path: string; what: string; include: boolean; size: string }[];
  /** For overhauls: the setup Bayle read or already has saved. */
  setupId?: SetupId;
  warnings: string[];
}

/* ------------------------------------------------------------------ saves */

export type SaveHealth = 'ok' | 'repair';

export interface Character {
  name: string;
  level: number;
  location?: string;
  playtime?: string;
  body?: string;
  runesHeld?: number;
  modItems?: string;
}

export interface Slot {
  /** 1-based slot number. */
  n: number;
  character?: Character;
  /** A problem with this character, shown as a warning. */
  problem?: string;
  /** Not played for a long time. */
  stale?: boolean;
}

export interface SaveFile {
  id: SaveId;
  gameId: GameId;
  label: string;
  fileName: string;
  size: string;
  health: SaveHealth;
  /** Who made this save, e.g. "Seamless Co-op". */
  source: string;
  sourceDetail: string;
  /** Profiles that launch with this save. */
  usedBy: string[];
  slots: Slot[];
}

export interface SaveCopy {
  id: CopyId;
  gameId: GameId;
  kind: 'library' | 'backup';
  name: string;
  fromFile?: string;
  note: string;
  when: string;
  size?: string;
  missing?: boolean;
  /** Backups: kept forever instead of rotating out. */
  pinned?: boolean;
  slots: Slot[];
}

export type SlotRef = { saveId: SaveId; n: number } | { copyId: CopyId; n: number };

/* ------------------------------------------------------------------ activity */

export type ActivityKind = 'launch' | 'install' | 'rebuild' | 'save' | 'profile';

export interface ActivityEntry {
  id: ActivityId;
  gameId: GameId;
  kind: ActivityKind;
  ok: boolean;
  title: string;
  detail: string;
  /** "Today", "Yesterday", or a date, for grouping. */
  day: string;
  time: string;
  duration: string;
  hasLog: boolean;
  undoable: boolean;
  undone?: boolean;
  undoLabel?: string;
  /** What Undo will do, line by line. */
  undoLines?: string[];
  noUndoReason?: string;
}

/** What every change returns, so the UI can toast it and offer Undo. */
export interface ActionResult {
  entry: ActivityEntry;
  /** Short line for the toast. */
  message: string;
  detail?: string;
}

/* ------------------------------------------------------------------ configs */

export type ConfigFormat = 'ini' | 'toml' | 'json' | 'text' | 'markdown';

export type ConfigValue = string | number | boolean;

export interface ConfigField {
  key: string;
  help?: string;
  type: 'bool' | 'int' | 'float' | 'string' | 'secret' | 'enum' | 'readonly';
  value: ConfigValue;
  default?: ConfigValue;
  options?: { value: string; label: string }[];
  unit?: string;
}

export interface ConfigSection {
  name: string;
  note?: string;
  fields: ConfigField[];
}

export interface ConfigFileRef {
  id: ConfigFileId;
  modId: ModId;
  modName: string;
  name: string;
  /** Overhaul setups appear on Mod Configs too. */
  isSetup?: boolean;
  /** Set when the file belongs to a mod's DLL: listed under the mod (groupId), marked with the DLL's file name. */
  groupId?: ModId;
  viaFile?: string;
}

export interface ConfigFile extends ConfigFileRef {
  path: string;
  format: ConfigFormat;
  /** Present when Bayle can show the file as a form. */
  sections?: ConfigSection[];
  /** The raw file, always present, for Edit as text. */
  text: string;
}

/* ------------------------------------------------------------------ overhaul setups */

export type FileAction = 'combine' | 'merge' | 'copy' | 'place' | 'keep' | 'text' | 'leave';

export interface SetupFile {
  path: string;
  what: string;
  action: FileAction;
  /** For "place": where it goes inside the game files. */
  target?: string;
  /** The overhaul will not work without it. */
  needed?: boolean;
}

export interface SetupDll {
  name: string;
  loadEarly: boolean;
  loadAfterOthers: boolean;
  initFunction: string;
}

/** Where the recipe came from and whether the download matches it. */
export interface Recipe {
  source: 'bundled' | 'community' | 'yours';
  /** Which version of the overhaul the recipe was written for. */
  forVersion: string;
  /** What the mod's files were made against. Bayle compares against vanilla by default; anything else is said, never guessed. */
  base: 'vanilla' | { mod: string } | 'unknown';
  /** match: every expected file is there. soft: small differences, listed. mismatch: a different release; refuse. */
  check: 'match' | 'soft' | 'mismatch';
  /** The differences, for a soft check. */
  differences?: string[];
}

export interface OverhaulSetup {
  id: SetupId;
  name: string;
  version: string;
  recipe?: Recipe;
  /** null until saved once. */
  savedOn: string | null;
  gameDir: string;
  ownInstaller?: string;
  dlls: SetupDll[];
  files: SetupFile[];
  languages: number;
}

/* ------------------------------------------------------------------ builds (merged game data) */

export type BuildState = 'none' | 'ready' | 'stale' | 'building';

/** Kinds of game file, in the words the UI uses. */
export type FileFamily = 'params' | 'text' | 'animations' | 'scripts' | 'behaviour' | 'textures' | 'other';

/** What happened to one mod's changes in one family of files. */
export type Outcome = 'merged' | 'won' | 'lost' | 'picked' | 'dropped' | 'unsupported' | 'unknown';

/** Something that changed since the last build, in plain words. */
export interface BuildChange {
  kind: 'mod-updated' | 'game-updated' | 'reordered' | 'toggled' | 'setup-changed' | 'pick-changed' | 'added' | 'removed';
  title: string;
  detail?: string;
}

/** One cell of the load-order board. */
export interface BuildCell {
  modId: ModId;
  family: FileFamily;
  outcome: Outcome;
  /** Pieces (rows, lines, animations, inner files) with this outcome. */
  count: number;
}

/**
 * How a clash is settled by the user. 'order' means "no pick of my own": it then
 * follows a kind rule if there is one, else the load order.
 */
export type ClashResolution = 'order' | 'pick' | 'both' | 'skip';

/** Why a winner won. Precedence: pick, then a kind rule (or one it is coupled to), then load order. */
export type WinReason = 'pick' | 'rule' | 'coupled' | 'order' | 'both';

/**
 * A kind rule: a small load order for one kind of file. "Animations: Clever's, then Convergence."
 * The first mod in `order` wins every clash of that kind between mods in the list, unless a pick says otherwise.
 */
export interface Rule {
  id: string;
  family: FileFamily;
  /** Winner first. */
  order: ModId[];
  /** Kinds that follow this rule too, so a mod's moveset stays together. */
  coupled?: FileFamily[];
  /** Pieces this rule settled for the first time since you last looked (after an update, say). */
  meetsNew?: number;
  /** The clashes it settled that it had not met before, for "which one is new?". */
  metIds?: string[];
  /** A mod in the rule is off or gone; the rule waits instead of being deleted. */
  dormant?: boolean;
}

/** One piece whose winner a rebuild would change. */
export interface PendingChange {
  clashId: string;
  piece: string;
  fromId?: ModId;
  toId?: ModId;
}

/** Two mods changed the same piece. */
export interface Clash {
  id: string;
  family: FileFamily;
  /** The game file, e.g. regulation.bin. */
  file: string;
  /** The piece inside it, e.g. "EquipParamWeapon · row 1000 (Dagger) · attack". */
  piece: string;
  /** Each side's change, in load order. */
  sides: { modId: ModId; value: string }[];
  /** How it is settled now. 'order' means the later mod wins. */
  resolution: ClashResolution;
  /** For 'pick': the mod whose value is used. */
  pickedId?: ModId;
  /** Only added rows or lines can be kept side by side. */
  canKeepBoth?: boolean;
  /** An input changed since you settled this; the choice still applies but deserves a look. */
  needsReview?: boolean;
  /** The file type cannot be merged: the whole file from one side is used. Not a judgement about compatibility. */
  unsupported?: boolean;
  /** Who wins now, and why. Absent when both are kept. Computed by the backend. */
  winnerId?: ModId;
  reason?: WinReason;
  /** Who won in the last build, so the UI can show what a rebuild would change. */
  builtWinnerId?: ModId;
  /** 'delete-edit': one mod removes what another changes. Never settled silently. */
  conflict?: 'edit' | 'delete-edit';
  /** Needs an explicit choice before Bayle stops asking. */
  unresolved?: boolean;
  /** The game itself moved this value since the mod was made: the mod's change may not mean what its author meant. */
  rebase?: { wasVanilla: string; nowVanilla: string; modId: ModId };
}

/** A change Bayle could not carry into the build. */
export interface DroppedChange {
  id: string;
  modId: ModId;
  family: FileFamily;
  file: string;
  what: string;
  reason: string;
  /** What the user can do about it, if anything. */
  fix?: string;
  /** The player said to play without it. It stays listed, but stops asking. */
  accepted?: boolean;
}

/** What every mod was compared against. */
export interface Baseline {
  /** e.g. "Elden Ring 1.16.1" */
  game: string;
  /** Mods whose base is not vanilla, or not known. The build compares them against vanilla anyway and says so. */
  exceptions: { modId: ModId; base: 'unknown' | { mod: string } }[];
}

export interface BuildReport {
  profileId: ProfileId;
  state: BuildState;
  baseline: Baseline;
  /** e.g. "today, 00:31" */
  builtOn?: string;
  durationSec?: number;
  /** Why the build is stale. Empty when ready. */
  changes: BuildChange[];
  /** Families that appear in at least one enabled package, in display order. */
  families: FileFamily[];
  cells: BuildCell[];
  clashes: Clash[];
  rules: Rule[];
  /** What rebuilding now would change, compared with the last build. Empty when nothing is pending. */
  pending: PendingChange[];
  dropped: DroppedChange[];
  /** Rules and picks the player changed since the last build; what Undo would put back. */
  choicesSinceBuild?: number;
  /** How much of each overlapping mod gets in, as things stand. */
  survival?: ModSurvival[];
  /** What was kept from more than one mod: "34 text lines", "12 parameter rows". */
  kept: { family: FileFamily; count: number; unit: string }[];
  /** Full merge report, one line each. */
  reportLines: string[];
}

/** One piece of the game and who last changed it, for "why is my game doing X". */
export interface PieceHit {
  family: FileFamily;
  file: string;
  piece: string;
  /** Mods that change it, in load order. The last one is what the game uses, unless a pick says otherwise. */
  changedBy: ModId[];
  /** What the game ends up with. */
  value: string;
  /** The mod whose value is used. */
  winnerId: ModId;
  /** Set when a clash record exists for this piece. */
  clashId?: string;
}

/**
 * How much of one mod makes it into the game: everything it changes against
 * the original game, minus the clashes it loses and the changes left out.
 */
export interface ModSurvival {
  modId: ModId;
  /** Pieces it changes against the original game. */
  total: number;
  /** Pieces whose value from this mod is in the build. */
  kept: number;
  lost: { clashId: string; piece: string; toId?: ModId }[];
  /** Pieces left out because they could not be read or merged. */
  dropped: number;
}

/** A winner change that applying a suggestion would cause. */
export interface SuggestedChange { clashId: string; piece: string; fromId?: ModId; toId?: ModId }

/**
 * One thing Bayle suggests, with its reason and its trade. Either a new load
 * order (for mods that can move) or a kind rule (where order cannot help,
 * for example against a mod that has to load last). Suggested, never applied
 * on its own.
 */
export type Suggestion = {
  id: string;
  title: string;
  reason: string;
  changes: SuggestedChange[];
  /** Change in kept pieces per mod if this is applied. */
  effect: { modId: ModId; delta: number }[];
} & (
  | { kind: 'order'; modKind: ModKind; orderedIds: ModId[]; moves: { modId: ModId; from: number; to: number }[] }
  | { kind: 'rule'; family: FileFamily; order: ModId[]; coupled?: FileFamily[] }
);

/** Bayle's suggestions for who should win, from what every mod changes. */
export interface OrderSuggestion {
  suggestions: Suggestion[];
  /** How much of each overlapping mod gets in now. */
  survival: ModSurvival[];
  /** What was left alone and why: your picks, your rules, decisions Bayle won't make. */
  leftAlone: string[];
}

/* ------------------------------------------------------------------ setup manifests (friends on the same setup) */

/** A profile described without its files: versions and hashes, so friends can compare without sharing mods. */
export interface SetupManifest {
  profileName: string;
  game: string;
  me3Version: string;
  /** e.g. "today, 16:40" */
  madeOn: string;
  launch: { mode: LaunchMode; online: boolean };
  mods: { name: string; version?: string; kind: ModKind; enabled: boolean; hash: string; order: number }[];
  /** Settings files that matter for playing together, with a hash of their contents. */
  configs: { file: string; hash: string }[];
}

export interface ManifestDifference {
  kind: 'missing-here' | 'missing-there' | 'version' | 'hash' | 'order' | 'enabled' | 'config' | 'launch' | 'loader';
  /** Mod or file name. */
  subject: string;
  mine: string;
  theirs: string;
  /** What it means for playing together. */
  effect: string;
}

/** What a rebuild would do, before anything is written. */
export interface BuildPlan {
  steps: { title: string; detail?: string }[];
  estimateSec: number;
}

/* ------------------------------------------------------------------ settings */

export type ThemeName = 'dark' | 'bayle' | 'tarnished' | 'light' | 'system';
export type LaunchMode = 'Profile' | 'Offline' | 'Vanilla';

export interface Settings {
  paths: {
    games: Record<GameId, string>;
    me3: string;
    profiles: string;
    sharedMods: string;
    backups: string;
    logs: string;
    settingsFile: string;
  };
  launch: {
    autoRebuild: boolean;
    installOverhauls: boolean;
    bootBoost: boolean;
    showLogos: boolean;
    diagnostics: boolean;
    closeLeftoversBefore: boolean;
    closeLeftoversAfter: boolean;
    warnLeftovers: boolean;
    offlineSkipOverhaul: boolean;
    offlineStartSteam: boolean;
    offlineSkipConfirm: boolean;
  };
  saves: {
    repairAfterQuit: Record<GameId, boolean>;
    backupBeforeLaunch: boolean;
    keepCopies: number;
    keepDays: number;
  };
  appearance: {
    theme: ThemeName;
    effects: 'full' | 'reduced' | 'off';
    density: 'comfortable' | 'compact';
  };
  updates: {
    channel: 'stable' | 'beta';
    checkOnStart: boolean;
    me3Notices: boolean;
  };
  logs: { keepDays: 7 | 30 | 90 };
}

/** Deep-partial patch for updateSettings. */
export type SettingsPatch = { [K in keyof Settings]?: Partial<Settings[K]> };

export interface AppInfo {
  version: string;
  me3Version: string;
  me3Latest?: string;
  update?: { version: string; channel: string };
  platform: string;
  dataFolder: string;
}

/* ------------------------------------------------------------------ live status + events */

export type StatusState = 'ready' | 'busy' | 'running' | 'warn';

export interface AppStatus {
  state: StatusState;
  text: string;
}

/** Things the backend pushes without being asked. */
export type BackendEvent =
  | { type: 'status'; status: AppStatus }
  | { type: 'game-closed'; gameId: GameId; summary: string }
  | { type: 'mod-failed'; gameId: GameId; modName: string; reason: string }
  | { type: 'changed'; scope: 'profiles' | 'saves' | 'activity' | 'settings' | 'configs' }
  /** Something the player should read now, said by the engine (a warning mid-job, an error). */
  | { type: 'notice'; text: string; error: boolean };
