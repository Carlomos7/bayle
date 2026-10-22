import { History, Library, Save, Settings, SlidersHorizontal, ArrowLeftRight, type LucideIcon } from "lucide-react";

/** The rail, in order; Ctrl+1..6 follow it (the Qt app had five: profile transfer was a sub-page of Mods). */
export interface PageDef {
  /** The backend's page key (GET /v1/pages/{key}). */
  key: string;
  path: string;
  label: string;
  icon: LucideIcon;
}

export const PAGES: readonly PageDef[] = [
  { key: "mods", path: "/mods", label: "Mods", icon: Library },
  { key: "modConfigs", path: "/mod-configs", label: "Mod Configs", icon: SlidersHorizontal },
  { key: "saves", path: "/saves", label: "Saves", icon: Save },
  { key: "profileTransfer", path: "/profile-transfer", label: "Profile transfer", icon: ArrowLeftRight },
  { key: "activity", path: "/activity", label: "Activity", icon: History },
  { key: "settings", path: "/settings", label: "Settings", icon: Settings },
];

export const pathForPage = (key: string) => PAGES.find((p) => p.key === key)?.path;
