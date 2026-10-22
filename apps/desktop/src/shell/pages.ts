import { History, Library, Save, Settings, SlidersHorizontal, ArrowLeftRight, type LucideIcon } from "lucide-react";

/** The rail, in order. Ctrl+1..5 are the Qt app's: profile transfer was a sub-page of Mods there, so it has none. */
export interface PageDef {
  /** The backend's page key (GET /v1/pages/{key}). */
  key: string;
  path: string;
  label: string;
  icon: LucideIcon;
  /** Ctrl+<n>, as in views/menu.py. */
  shortcut?: number;
}

export const PAGES: readonly PageDef[] = [
  { key: "mods", path: "/mods", label: "Mods", icon: Library, shortcut: 1 },
  { key: "modConfigs", path: "/mod-configs", label: "Mod Configs", icon: SlidersHorizontal, shortcut: 2 },
  { key: "saves", path: "/saves", label: "Saves", icon: Save, shortcut: 3 },
  { key: "profileTransfer", path: "/profile-transfer", label: "Profile transfer", icon: ArrowLeftRight },
  { key: "activity", path: "/activity", label: "Activity", icon: History, shortcut: 4 },
  { key: "settings", path: "/settings", label: "Settings", icon: Settings, shortcut: 5 },
];

export const pathForPage = (key: string) => PAGES.find((p) => p.key === key)?.path;
