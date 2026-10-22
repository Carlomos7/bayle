import { createContext, use } from "react";
import { toast } from "sonner";
import type { InstallRequest } from "./types";

/**
 * What the Mods page asks of the rest of the app, and nothing more. The Install mod dialog (its own work package) and
 * the shell's New profile dialog provide these with `ModsHostContext` (around the router outlet or the page); the page
 * needs no further change. Until then each one says so instead of doing nothing.
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
