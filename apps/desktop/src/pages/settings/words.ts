/** The page's fixed words, copied from the Qt page's adapter (ui/pages/settings/adapter.py): the snapshot carries the
 *  settings' own words (titles, blurbs, help, choice labels) but not these headings and buttons. */
export const W = {
  locations: "Locations",
  launch: "Launch",
  launchHint: "Steps that run around Launch. Each can be turned off; Launch itself always runs.",
  offline: "Offline play",
  offlineBlurb:
    "Launch Offline starts this profile without Seamless Co-op and with online play off. The game then uses its standard save (.sl2), not Seamless's (.co2).",
  steam: "Steam shortcut",
  steamHelp: "Launches from Steam without this window. One shortcut per game.",
  copyTarget: "Copy target",
  copyOptions: "Copy launch options",
  copied: "Copied",
  pointSteam: "Point Steam shortcuts here",
  leftover: "Leftover processes",
  leftoverHelp: "Hidden copies of the game left running after it closes.",
  clearNow: "Clear now",
  backups: "Backups",
  backupsLocation: "Location",
  backupsLocationHelp: "Inside the launcher's data folder.",
  backupsKeep: "How many to keep",
  backupsKeepHelp: "Per save file. Backups from the last 7 days and any you marked Keep are kept as well.",
  appearance: "Appearance",
  theme: "Theme",
  themeHelp: "System follows Windows. Tarnished is a dark olive theme.",
  effects: "Effects",
  effectsHelp: "Off has no blur or grain. Reduced has no blur and lighter grain.",
  grain: "Grain",
  grainHelp: "Fine texture behind pages and panels.",
  logo: "Logo",
  logoHelp:
    "Sets the top bar emblem and the window icon. Follows theme is crimson on dark themes and ice on the light theme.",
  updates: "Updates",
  channel: "Update channel",
  channelHelp:
    "Beta also offers pre-releases, which get less testing. Going back to Stable never installs an older version.",
  check: "Check for updates",
  releases: "Releases",
  logs: "Logs",
  logsFolder: "Logs folder",
  openFolder: "Open folder",
  saveLogs: "Save logs for support",
  saveLogsHelp: "A zip of recent logs with user names and Steam IDs masked.",
  save: "Save...",
  settingsFolder: "Settings folder",
  logLevel: "Log level",
  logLevelHelp: "Verbose adds fine detail to launcher.log.",
  about: "About",
  aboutHelp:
    "GPL-3.0. Built on PySide6 and me3. Bayle is an unofficial fan project and is not affiliated with or endorsed by FromSoftware or Bandai Namco.",
  licence: "Licence",
  notices: "Third-party notices",
  browse: "Browse...",
  clear: "Clear",
  more: "More",
  profilesFolder: "Profiles folder",
  profilesFolderHelp: "Where Bayle keeps its profiles and mods.",
  change: "Change...",
  moveAll: "Move all...",
  otherProfiles: "Profiles outside Bayle",
  moveAllTip: "Moves every me3 profile of this game into Bayle's folder.",
  folderNames: "Folder names",
  gameFolder: "Game folder",
  gameFiles: "Game-file mods",
  dllMods: "DLL mods",
  sharedMods: "Shared mods",
  apply: "Apply",
  cancel: "Cancel",
  moving: "Moving...",
  dismiss: "Dismiss",
  readMe3: "Read again",
  me3Reading: "Checking me3...",
  loading: "Loading settings...",
} as const;

/** location key -> the folder kind of settings.folder */
export const FOLDER_KIND: Record<string, string> = {
  me3_path: "me3",
  game_exe: "game",
  me3_profile_dir: "profiles",
  saves_dir: "saves",
};

/** the folder-name fields, in the order the Qt page shows them (the keys of settings.layout_check's Names) */
export const NAME_FIELDS = [
  ["pattern", W.gameFolder],
  ["packages", W.gameFiles],
  ["natives", W.dllMods],
  ["shared", W.sharedMods],
] as const;
export type NameField = (typeof NAME_FIELDS)[number][0];

export const GITHUB = "https://github.com/Carlomos7/roundtable-souls";

export const SAID = {
  steamChanged: (names: string) => `Steam shortcuts updated. Now starting this copy: ${names}.`,
  steamNothing: "Nothing to change: no Steam shortcut with --play starts another copy.",
  logsSaved: (name: string) => `Logs saved: ${name}. User names and Steam IDs are masked.`,
  folderMissing: "That folder was not found on this PC.",
  pickFolder: "Pick the folder",
  pickFile: "Pick the file",
  pickProfiles: "Pick the profiles folder",
  pickLogs: "Save logs for support: pick a folder",
};
