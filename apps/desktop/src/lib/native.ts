import { open } from "@tauri-apps/plugin-dialog";
import { openPath, openUrl } from "@tauri-apps/plugin-opener";

/** The desktop shell's pickers and openers (Tauri plugins); pages call these so tests can replace them. */
export const pickFolder = async (title: string): Promise<string | null> => {
  const got = await open({ directory: true, multiple: false, title });
  return typeof got === "string" ? got : null;
};

export const pickFile = async (title: string, filterName: string, extensions: string[]): Promise<string | null> => {
  const filters = extensions.length ? [{ name: filterName, extensions }] : undefined;
  const got = await open({ directory: false, multiple: false, title, filters });
  return typeof got === "string" ? got : null;
};

/** Open a file or folder with the desktop's default program (the opener capability limits where). */
export { openPath };
export const openFolder = (path: string) => openPath(path);
export const openLink = (url: string) => openUrl(url);
