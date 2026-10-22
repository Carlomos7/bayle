import { createContext, use } from "react";
import { toast } from "sonner";
import type { InstallRequest } from "./types";

/**
 * What the Mods page's rows and menus ask of the page itself: ModsPage provides it (it renders the Install mod dialog,
 * and the shell's New profile dialog is reached through the shell actions). Without a provider each says so.
 */
export interface ModsHost {
  /** Open the Install mod dialog; `request` says what to install (a picked kind, or paths dropped on the page). */
  openInstall(request?: InstallRequest): void;
  /** Open the shell's New profile dialog (the first-run button). */
  newProfile(): void;
}

const stub: ModsHost = {
  openInstall: () => toast("The Install mod dialog is not built yet."),
  newProfile: () => toast("The New profile dialog is not built yet."),
};

export const ModsHostContext = createContext<ModsHost>(stub);
export const useModsHost = () => use(ModsHostContext);
