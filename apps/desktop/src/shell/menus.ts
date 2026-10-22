import type { ShellState } from "@/api/types";

/** The menu bar, as views/menu.py lists it (same ids, words, shortcuts and rules). */
export interface MenuEntry {
  id: string;
  label: string;
  shortcut?: string;
  rule?: Rule;
  /** checked_when: "game:<key>" | "theme:<mode>" */
  checked?: string;
  separator?: boolean;
  submenu?: MenuEntry[];
}
export type Rule = "game_ready" | "profile" | "idle" | "profile_idle";

const SEP: MenuEntry = { id: "", label: "", separator: true };
export const THEMES = [
  ["dark", "Dark"],
  ["tarnished", "Tarnished"],
  ["light", "Light"],
  ["system", "System"],
] as const;
export const MODES = [
  ["profile", "Profile"],
  ["offline", "Offline"],
  ["vanilla", "Vanilla"],
] as const;

export const MENUS: { id: string; title: string; entries: MenuEntry[] }[] = [
  {
    id: "file",
    title: "File",
    entries: [
      { id: "file.new", label: "New profile...", shortcut: "Ctrl+N", rule: "game_ready" },
      { id: "file.add", label: "Add existing profile...", rule: "game_ready" },
      { id: "file.import", label: "Import profile...", rule: "game_ready" },
      { id: "file.export", label: "Export profile...", rule: "profile" },
      SEP,
      { id: "file.profile_folder", label: "Open profile folder", rule: "profile" },
      { id: "file.game_folder", label: "Open game folder", rule: "game_ready" },
      SEP,
      { id: "file.exit", label: "Exit", shortcut: "Ctrl+Q" },
    ],
  },
  {
    id: "profile",
    title: "Profile",
    entries: [
      { id: "profile.rename", label: "Rename...", rule: "profile_idle" },
      { id: "profile.duplicate", label: "Duplicate...", rule: "profile_idle" },
      { id: "profile.move_in", label: "Move into Bayle's folder...", rule: "profile_idle" },
      { id: "profile.delete", label: "Delete...", rule: "profile_idle" },
      SEP,
      { id: "profile.settings", label: "Profile settings...", rule: "profile" },
      { id: "profile.edit", label: "Edit .me3...", rule: "profile" },
      { id: "profile.fix_order", label: "Fix load order", rule: "profile_idle" },
      { id: "profile.versions", label: "Versions...", rule: "profile" },
    ],
  },
  { id: "game", title: "Game", entries: [] }, // the games and the Launch entries come from the shell's snapshot
  {
    id: "saves",
    title: "Saves",
    entries: [
      { id: "saves.backup", label: "Back up now", rule: "idle" },
      { id: "saves.transfer", label: "Transfer character...", rule: "idle" },
      { id: "saves.import", label: "Import save file...", rule: "idle" },
      SEP,
      { id: "saves.folder", label: "Open saves folder", rule: "game_ready" },
      { id: "saves.library", label: "Open library folder", rule: "game_ready" },
      { id: "saves.backups", label: "Open backups folder", rule: "game_ready" },
    ],
  },
  {
    id: "view",
    title: "View",
    entries: [
      { id: "view.mods", label: "Mods", shortcut: "Ctrl+1", rule: "game_ready" },
      { id: "view.configs", label: "Mod Configs", shortcut: "Ctrl+2", rule: "game_ready" },
      { id: "view.saves", label: "Saves", shortcut: "Ctrl+3", rule: "game_ready" },
      { id: "view.activity", label: "Activity", shortcut: "Ctrl+4" },
      { id: "view.settings", label: "Settings", shortcut: "Ctrl+5" },
      SEP,
      {
        id: "view.theme",
        label: "Theme",
        submenu: THEMES.map(([mode, label]) => ({ id: `view.theme.${mode}`, label, checked: `theme:${mode}` })),
      },
      { id: "view.rail", label: "Collapse navigation" },
    ],
  },
  {
    id: "help",
    title: "Help",
    entries: [
      { id: "help.how", label: "How to use", shortcut: "F1" },
      { id: "help.updates", label: "Check for updates" },
      { id: "help.logs_save", label: "Save logs for support..." },
      { id: "help.logs_folder", label: "Open logs folder" },
      { id: "help.me3", label: "About the mod loader (me3)..." },
      { id: "help.steam", label: "Point Steam shortcuts at Bayle" },
      SEP,
      { id: "help.about", label: "About" },
    ],
  },
];

/** The pages the menu entries open (the page's own command is not driven from here yet). */
export const ENTRY_PAGES: Record<string, string> = {
  "view.mods": "mods",
  "view.configs": "modConfigs",
  "view.saves": "saves",
  "view.activity": "activity",
  "view.settings": "settings",
  "help.about": "settings",
  "file.import": "profileTransfer",
  "file.export": "profileTransfer",
  ...Object.fromEntries(MENUS.find((m) => m.id === "profile")!.entries.filter((e) => e.id).map((e) => [e.id, "mods"])),
  ...Object.fromEntries(MENUS.find((m) => m.id === "saves")!.entries.filter((e) => e.id).map((e) => [e.id, "saves"])),
};

export function enabled(rule: Rule | undefined, shell: ShellState | undefined): boolean {
  if (!rule) return true;
  if (!shell) return false;
  const idle = shell.pill.state !== "busy" && !shell.game_running;
  switch (rule) {
    case "game_ready":
      return shell.game_ready;
    case "profile":
      return shell.game_ready && shell.profiles.length > 0;
    case "idle":
      return shell.game_ready && idle;
    case "profile_idle":
      return shell.game_ready && shell.profiles.length > 0 && idle;
  }
}
