/** What only the desktop shell can do: the system's folder picker, Explorer, and files dropped on the window. Each one
 *  is a Tauri plugin; outside Tauri (tests, the browser dev server) they do nothing. */

/** Ask for a folder; null when cancelled. */
export async function pickFolder(title: string): Promise<string | null> {
  const { open } = await import("@tauri-apps/plugin-dialog");
  const got = await open({ directory: true, multiple: false, title });
  return typeof got === "string" ? got : null;
}

/** Show a folder in Explorer. */
export async function openPath(path: string): Promise<void> {
  const { openPath: open } = await import("@tauri-apps/plugin-opener");
  await open(path);
}

/** Files dropped from Explorer onto the window; returns the unsubscribe. The Webview reports the paths (a browser drop does not). */
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
