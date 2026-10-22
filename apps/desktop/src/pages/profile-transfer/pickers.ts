import { open } from "@tauri-apps/plugin-dialog";

/** The Tauri dialog plugin (capability dialog:allow-open); null when the player cancels. */
export async function pickFolder(title: string): Promise<string | null> {
  const got = await open({ directory: true, multiple: false, title });
  return typeof got === "string" ? got : null;
}

export async function pickProfileFile(title: string): Promise<string | null> {
  const got = await open({
    multiple: false,
    title,
    filters: [{ name: "Profile files", extensions: ["json", "zip"] }],
  });
  return typeof got === "string" ? got : null;
}
