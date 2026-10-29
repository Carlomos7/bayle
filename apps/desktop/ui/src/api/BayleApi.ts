import type {
  ActionResult, ActivityEntry, ActivityId, AppInfo, AppStatus, BackendEvent, BuildPlan, BuildReport, ClashResolution, ConfigFile, FileFamily, ManifestDifference, OrderSuggestion, PieceHit, SetupManifest, ConfigFileId, ConfigFileRef,
  ConfigValue, CopyId, Game, GameId, InstallPreview, InstallSource, LaunchMode, Mod, ModFile, ModId, ModKind,
  Leftover, OverhaulSetup, Profile, ProfileId, ProfileSummary, SaveCopy, SaveFile, SaveId, SetupId, Settings, SettingsPatch, SlotRef,
} from './types';

/**
 * Everything the UI asks of the backend.
 *
 * Implement this once per transport (see src/api/bridge.ts for a template).
 * Rules:
 * - Every method is async and resolves with plain JSON.
 * - Methods that change something return an ActionResult, which the UI turns
 *   into a toast with Undo and an Activity entry. The backend owns undo.
 * - Errors: reject with an Error whose message is a sentence for the user
 *   ("A file was in use. Close the game and try again.").
 * - Long work (launch, rebuild, install) resolves when it is done; progress
 *   comes through subscribe() as status events.
 */
export interface BayleApi {
  /* app */
  getAppInfo(): Promise<AppInfo>;
  getStatus(): Promise<AppStatus>;
  /** Push channel for status, game closed, failures and "data changed". Returns unsubscribe. */
  subscribe(listener: (event: BackendEvent) => void): () => void;

  /* games + profiles */
  getGames(): Promise<Game[]>;
  /** Make a game the one the app works on (the engine acts on one game at a time). */
  selectGame(gameId: GameId): Promise<void>;
  setActiveProfile(gameId: GameId, profileId: ProfileId): Promise<void>;
  listProfiles(gameId: GameId): Promise<ProfileSummary[]>;
  getProfile(profileId: ProfileId): Promise<Profile>;
  createProfile(gameId: GameId, name: string, copyFrom?: ProfileId): Promise<ActionResult & { profileId: ProfileId }>;
  renameProfile(profileId: ProfileId, name: string): Promise<ActionResult>;
  deleteProfile(profileId: ProfileId): Promise<ActionResult>;
  /** Move a profile that lives elsewhere into Bayle's folder. */
  moveProfileIn(profileId: ProfileId): Promise<ActionResult>;
  /** Undo what an overhaul's own installer did, so Bayle can manage it. */
  takeOverInstaller(profileId: ProfileId): Promise<ActionResult>;

  /* mods in a profile */
  setModsEnabled(profileId: ProfileId, modIds: ModId[], enabled: boolean): Promise<ActionResult>;
  /** New order for one kind. Mods that must stay last are kept last by the backend. */
  reorderMods(profileId: ProfileId, kind: ModKind, orderedIds: ModId[]): Promise<ActionResult>;
  removeMods(profileId: ProfileId, modIds: ModId[], opts?: { rebuild?: boolean }): Promise<ActionResult>;
  addModsToProfile(targetProfileId: ProfileId, fromProfileId: ProfileId, modIds: ModId[]): Promise<ActionResult>;
  /** Take the newer release a mod reports. Keeps settings and picks; the old version stays for Undo. */
  upgradeMod(profileId: ProfileId, modId: ModId): Promise<ActionResult>;
  updateMod(profileId: ProfileId, modId: ModId, patch: Partial<Pick<Mod, 'enabled' | 'packageId' | 'loadAfter' | 'staysLast' | 'rebuildFile' | 'native' | 'name'>>): Promise<ActionResult>;
  listModFiles(profileId: ProfileId, modId: ModId): Promise<ModFile[]>;
  attachConfig(profileId: ProfileId, modId: ModId, fileNames: string[]): Promise<ActionResult>;
  detachConfig(profileId: ProfileId, modId: ModId, fileName: string): Promise<ActionResult>;
  /** Settings files beside the mod that are not attached yet. */
  listAttachableConfigs(profileId: ProfileId, modId: ModId): Promise<string[]>;
  previewInstall(source: InstallSource): Promise<InstallPreview>;
  install(profileId: ProfileId, preview: InstallPreview): Promise<ActionResult>;
  rebuildMerged(profileId: ProfileId): Promise<ActionResult>;

  /* builds: the merged game data for a profile */
  /** State, clashes, dropped changes and the load-order board. Cheap; cached by the backend. */
  getBuild(profileId: ProfileId): Promise<BuildReport>;
  /** What a rebuild would do now. Writes nothing. */
  previewBuild(profileId: ProfileId): Promise<BuildPlan>;
  /** Settle a clash. The choice is kept for later rebuilds and marked for review when its inputs change. */
  resolveClash(profileId: ProfileId, clashId: string, resolution: ClashResolution, pickedId?: ModId): Promise<ActionResult>;
  /** Set or clear a kind rule. `order` winner first; null goes back to load order. Applies at the next rebuild. */
  setRule(profileId: ProfileId, family: FileFamily, order: ModId[] | null, coupled?: FileFamily[]): Promise<ActionResult>;
  /** Mark a rule's new pieces as seen. */
  confirmRule(profileId: ProfileId, ruleId: string): Promise<void>;
  /** Play without a change that could not be merged. It stops asking; undo brings the question back. */
  acceptDropped(profileId: ProfileId, droppedId: string): Promise<ActionResult>;
  /** Drop every rule and pick change made since the last build. */
  discardPending(profileId: ProfileId): Promise<ActionResult>;
  /** Search the piece index: "dash", "Dagger", a row id. Answers "which mod changed this?". */
  searchPieces(profileId: ProfileId, query: string): Promise<PieceHit[]>;
  /** Who should win, from what every mod changes: a load order where mods can move, kind rules where they cannot. Each with its reason and trade. Changes nothing. */
  suggestOrder(profileId: ProfileId): Promise<OrderSuggestion>;

  /* setup manifests: play with friends on the same setup without sharing files */
  /** The profile as versions and hashes. Contains no mod files. */
  exportManifest(profileId: ProfileId): Promise<SetupManifest>;
  /** Write the manifest to a file the user picks. Returns the path. */
  saveManifest(profileId: ProfileId): Promise<string | null>;
  /** Pick a friend's manifest file and compare. Read only. */
  compareManifest(profileId: ProfileId): Promise<{ theirs: SetupManifest; differences: ManifestDifference[] } | null>;

  /* launch */
  launch(gameId: GameId, profileId: ProfileId, mode: LaunchMode): Promise<void>;

  /* saves */
  listSaves(gameId: GameId): Promise<SaveFile[]>;
  listCopies(gameId: GameId): Promise<SaveCopy[]>;
  repairSave(saveId: SaveId): Promise<ActionResult>;
  keepCopy(saveId: SaveId, name: string): Promise<ActionResult>;
  /** Copy one character into a slot (from a live save or a copy). Overwrites what is there; the backend backs it up first. */
  copyCharacter(from: SlotRef, to: { saveId: SaveId; n: number }): Promise<ActionResult>;
  deleteCharacter(saveId: SaveId, n: number): Promise<ActionResult>;
  /** Put a whole copy back over a live save. */
  restoreCopy(copyId: CopyId, saveId: SaveId): Promise<ActionResult>;
  renameCopy(copyId: CopyId, name: string): Promise<ActionResult>;
  removeCopy(copyId: CopyId): Promise<ActionResult>;
  pinBackup(copyId: CopyId, pinned: boolean): Promise<ActionResult>;
  importSave(gameId: GameId, path: string): Promise<ActionResult>;
  backupNow(gameId: GameId): Promise<ActionResult>;

  /* configs */
  listConfigFiles(profileId: ProfileId): Promise<ConfigFileRef[]>;
  getConfigFile(profileId: ProfileId, id: ConfigFileId): Promise<ConfigFile>;
  /** Save either form values (section.key → value) or the raw text. */
  saveConfigFile(profileId: ProfileId, id: ConfigFileId, change: { values: Record<string, ConfigValue> } | { text: string }): Promise<ActionResult>;

  /* overhaul setups */
  /** profileId: the profile the sheet is open for (a setup is read from, and written to, one profile). */
  getSetup(id: SetupId, profileId: ProfileId): Promise<OverhaulSetup>;
  /** Profiles that use this setup and would be rebuilt on save. */
  setupUsers(id: SetupId): Promise<{ profileId: ProfileId; name: string; running: boolean }[]>;
  saveSetup(setup: OverhaulSetup): Promise<ActionResult>;
  installOverhaul(profileId: ProfileId, setup: OverhaulSetup): Promise<ActionResult>;
  removeOverhaul(profileId: ProfileId, setupId: SetupId): Promise<ActionResult>;
  /** What overhauls' own installers left beside the profile (no screen lists them yet). */
  listLeftovers(profileId: ProfileId): Promise<Leftover[]>;
  cleanLeftovers(profileId: ProfileId, paths: string[]): Promise<ActionResult>;

  /* activity */
  listActivity(): Promise<ActivityEntry[]>;
  undo(entryId: ActivityId): Promise<ActionResult>;
  getLog(entryId: ActivityId): Promise<string[]>;

  /* settings */
  getSettings(): Promise<Settings>;
  getDefaultSettings(): Promise<Settings>;
  updateSettings(patch: SettingsPatch): Promise<Settings>;
  clearBootBoostCache(): Promise<void>;
  /** What moving the Profiles folder to `folder` means: how many profiles, their size and the free space there (bytes; null when it can't be read). */
  checkMoveProfiles(folder: string): Promise<{ profiles: number; size: number; free: number | null }>;
  /** Move every profile and mod there (copied and checked first; the old folder goes only once the move is done). */
  moveProfiles(folder: string): Promise<ActionResult>;
  /** Zip the logs where the user picks. Returns the path, or null when they cancel. */
  saveSupportLogs(): Promise<string | null>;
  checkForUpdates(): Promise<AppInfo>;

  /* desktop */
  pickFile(opts: { title: string; filters?: { name: string; extensions: string[] }[] }): Promise<string | null>;
  pickFolder(opts: { title: string }): Promise<string | null>;
  openPath(path: string): Promise<void>;
  /** Open a web page in the user's browser (releases, notes, GitHub). */
  openUrl(url: string): Promise<void>;
  windowControl(action: 'minimize' | 'maximize' | 'close'): Promise<void>;
  /** Whether the window is maximized, for the title bar's Maximise/Restore button. */
  isMaximized(): Promise<boolean>;
  /** Open the folder the app and engine write their logs to. */
  openLogs(): Promise<void>;
}
