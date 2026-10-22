import { createContext, use } from "react";
import type { ModsActions } from "./actions";
import type { ModsView, Words } from "./types";

/** What every part of the page reads: the snapshot, its words, the actions and the dialogs only the page opens. */
export interface ModsContextValue {
  view: ModsView;
  words: Words;
  actions: ModsActions;
  /** Another page's work asked of this one (Mod Configs on a DLL). */
  openConfigs(name: string): void;
  openOptions(index: number): void;
  openRename(index: number): void;
  openAddExisting(kind: string): void;
}

export const ModsContext = createContext<ModsContextValue | null>(null);

export function useMods(): ModsContextValue {
  const v = use(ModsContext);
  if (!v) throw new Error("useMods outside the Mods page");
  return v;
}
