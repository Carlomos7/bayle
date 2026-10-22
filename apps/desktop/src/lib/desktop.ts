import { openPath as tauriOpenPath } from "@tauri-apps/plugin-opener";

/** Open a file with the desktop's default program (Tauri opener; its capability only allows a job log under logs/jobs). */
export const openPath = (path: string): Promise<void> => tauriOpenPath(path);
