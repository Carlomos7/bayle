/** What only the desktop shell can do for this page: the system's file picker. Outside Tauri (tests, the browser dev server) it asks for the path in a prompt. */

/** Ask for a file; null when cancelled. */
export async function pickFile(title: string): Promise<string | null> {
  try {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const got = await open({ multiple: false, directory: false, title });
    return typeof got === "string" ? got : null;
  } catch {
    return window.prompt(title)?.trim() || null;
  }
}
