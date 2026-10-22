import { open } from "@tauri-apps/plugin-dialog";
import { getCurrentWebview } from "@tauri-apps/api/webview";

/** The Tauri file or folder picker; null when cancelled. Same filter as the Qt dialog. */
export async function pickSource(folder: boolean): Promise<string | null> {
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
}

/** Files dropped on the window; returns the unlisten function. A no-op outside Tauri (tests, a browser). */
export async function onFilesDropped(handler: (paths: string[]) => void): Promise<() => void> {
  try {
    return await getCurrentWebview().onDragDropEvent((e) => {
      if (e.payload.type === "drop" && e.payload.paths.length > 0) handler(e.payload.paths);
    });
  } catch {
    return () => {};
  }
}
