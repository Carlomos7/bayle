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
/** The Install mod dialog's picker: an archive or DLL, or an unpacked folder; null when cancelled. Same filter as the Qt dialog. */
export const pickModSource = async (folder: boolean): Promise<string | null> => {
  const got = await open(
    folder
      ? { directory: true, title: "Install a mod: pick its folder" }
      : {
          title: "Install a mod: pick an archive or DLL",
          filters: [
            { name: "Mod archive or DLL", extensions: ["zip", "7z", "rar", "dll"] },
            { name: "All files", extensions: ["*"] },
          ],
        },
  );
  return typeof got === "string" ? got : null;
};

export const openFolder = (path: string) => openPath(path);
export const openLink = (url: string) => openUrl(url);

/** Files dropped from Explorer onto the window; returns the unsubscribe. The Webview reports the paths (a browser drop does not). Outside Tauri it does nothing. */
export async function onFilesDropped(handler: (paths: string[], over: boolean) => void): Promise<() => void> {
  try {
    const { getCurrentWebview } = await import("@tauri-apps/api/webview");
    return await getCurrentWebview().onDragDropEvent((e) => {
      const p = e.payload;
      if (p.type === "drop") handler(p.paths, false);
      else if (p.type === "over" || p.type === "enter") handler([], true);
      else handler([], false);
    });
  } catch {
    return () => {};
  }
}
