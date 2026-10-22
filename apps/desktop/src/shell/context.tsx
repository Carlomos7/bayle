import { createContext, use } from "react";

/** What the top bar, the menus and the keys can ask of the shell (Shell.tsx implements it). */
export interface ShellActions {
  /** A link of the pill or the status line (views/topbar.py: new_profile, pick_profile, settings:locations, ...). */
  follow(action: string): void;
  openNewProfile(): void;
  addProfile(): void;
  launch(mode?: string): void;
  cycleGame(step: 1 | -1): void;
  setGame(key: string): void;
  toggleRail(): void;
  railCollapsed: boolean;
  profileMenuOpen: boolean;
  setProfileMenuOpen(open: boolean): void;
  modeMenuOpen: boolean;
  setModeMenuOpen(open: boolean): void;
  run(entryId: string): void;
}

export const ShellActionsContext = createContext<ShellActions | null>(null);

export function useShellActions(): ShellActions {
  const ctx = use(ShellActionsContext);
  if (!ctx) throw new Error("useShellActions outside Shell");
  return ctx;
}
