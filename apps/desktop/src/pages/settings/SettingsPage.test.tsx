import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { AppWithBackend } from "@/App";
import { buildRouter } from "@/router";
import { backend, BASE, server } from "@/test/server";

const native = vi.hoisted(() => ({
  pickFolder: vi.fn(),
  pickFile: vi.fn(),
  openLink: vi.fn(),
}));
vi.mock("@/lib/native", () => native);

const spec = (key: string, kind: string, extra: object = {}) => ({ key, kind, scope: "global", follow: "settings", ...extra });
const choices = (...keys: string[]) => keys.map((k) => ({ key: k, label: k[0]!.toUpperCase() + k.slice(1) }));

const settings = {
  game: "eldenring",
  theme: "dark",
  effects: "full",
  grain: "subtle",
  logo: "auto",
  log_level: "normal",
  launcher_channel: "stable",
  labels: {},
  choices: {
    theme: choices("dark", "tarnished", "light", "system"),
    effects: choices("full", "reduced", "off"),
    grain: choices("off", "subtle", "film"),
    logo: [{ key: "auto", label: "Follows theme" }, ...choices("crimson", "ice", "gold")],
    log_level: choices("normal", "verbose"),
    launcher_channel: choices("stable", "beta"),
  },
  backups_keep: 20,
  keep_from: 5,
  keep_to: 200,
  backups_location: "C:\\data\\saves",
  profiles_root: "C:\\data\\profiles",
  steam_target: "C:\\bayle.exe",
  steam_options: "--play",
  data_folder: "C:\\data",
  launcher_line: "Bayle 4.6.0  ·  running from source",
  layout: { pattern: "{game}", packages: "packages", natives: "natives", shared: "shared" },
  locations: [
    { key: "me3_path", title: "me3", help: "Leave empty to find me3 automatically.", value: "", placeholder: "detected: C:\\me3.exe", is_dir: false, filter: "me3 (me3.exe)" },
    { key: "saves_dir", title: "Saves folder", help: "Where the game keeps saves.", value: "", placeholder: "detected: C:\\saves", is_dir: true, filter: "" },
  ],
  switches: [
    { key: "play_boot_boost", title: "Boot boost", blurb: "me3 keeps a decrypted copy.", help: "", group: "launch", checked: true, shown: true },
    { key: "overhaul_install", title: "Install overhauls", blurb: "", help: "", group: "launch", checked: false, shown: false },
    { key: "check_launcher_updates", title: "Check for updates on start", blurb: "", help: "", group: "updates", checked: true, shown: true },
  ],
  specs: [
    spec("play_boot_boost", "switch"),
    spec("overhaul_install", "switch"),
    spec("check_launcher_updates", "switch"),
    spec("theme", "choice", { follow: "appearance", choices: ["dark", "tarnished", "light", "system"] }),
    spec("effects", "choice", { follow: "appearance", choices: ["full", "reduced", "off"] }),
    spec("grain", "choice", { follow: "appearance", choices: ["off", "subtle", "film"] }),
    spec("logo", "choice", { choices: ["auto", "crimson", "ice", "gold"] }),
    spec("log_level", "choice", { choices: ["normal", "verbose"] }),
    spec("launcher_channel", "choice", { follow: "updates", choices: ["stable", "beta"] }),
    spec("backups_keep", "number", { low: 5, high: 200, follow: "none" }),
    spec("me3_path", "location"),
    spec("saves_dir", "location", { is_dir: true, scope: "game" }),
  ],
};

const shell = {
  game_name: "Elden Ring",
  game_ready: true,
  game_running: false,
  profiles: ["Vanilla"],
  profile_index: 0,
  status: { text: "Ready", tone: "muted", busy: false },
  pill: { text: "Play", state: "ready", can_launch: true, mode_text: "" },
  unseen: 0,
  updates: {
    line: "Up to date",
    tone: "muted",
    checking: false,
    notices: [
      {
        id: "flow",
        level: "info",
        title: "Bayle 4.7.0 is available",
        body: "Notes here",
        closable: true,
        actions: [{ key: "update", label: "Update now", primary: true }],
      },
    ],
  },
};

const problem = (code: string, message: string, status = 400) =>
  HttpResponse.json({ code, message, details: {} }, { status });

interface Call {
  op: string;
  body: unknown;
}

/** Serve the pages and record every op; `ops` overrides one op's answer. */
function boot(ops: Record<string, (body: unknown) => Response> = {}) {
  const calls: Call[] = [];
  server.use(
    http.get(`${BASE}/v1/pages/shell`, () => HttpResponse.json(shell)),
    http.get(`${BASE}/v1/pages/settings`, () => HttpResponse.json(settings)),
    http.get(`${BASE}/v1/events`, () => new HttpResponse(new ReadableStream(), { headers: { "Content-Type": "text/event-stream" } })),
    http.post(`${BASE}/v1/ops/:op`, async ({ request, params }) => {
      const op = String(params.op);
      const body = await request.json();
      calls.push({ op, body });
      if (ops[op]) return ops[op](body);
      if (op === "settings.layout_check") return HttpResponse.json({ errors: {}, preview: "Elden Ring" });
      if (op === "shell.me3") return HttpResponse.json({ facts: { version: "0.9.0", latest: { version: "0.9.0" } } });
      if (op === "settings.set") return HttpResponse.json({ ...(body as object), stored_as: "x", follow: "settings", said: "" });
      return HttpResponse.json({});
    }),
  );
  render(<AppWithBackend backend={backend} router={buildRouter(createMemoryHistory({ initialEntries: ["/settings"] }))} />);
  return { calls, last: (op: string) => calls.filter((c) => c.op === op).at(-1)?.body };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Settings page", () => {
  test("shows a loading state, then every section from the snapshot", async () => {
    boot();
    expect(await screen.findByText("Loading settings...")).toBeInTheDocument();
    for (const name of ["Locations", "Launch", "Backups", "Appearance", "Updates", "Logs", "About"])
      expect(await screen.findByRole("heading", { name })).toBeInTheDocument();
    expect(screen.getByLabelText("Boot boost")).toBeChecked();
    expect(screen.queryByLabelText("Install overhauls")).not.toBeInTheDocument(); // shown: false
    expect(screen.getByLabelText("me3")).toHaveAttribute("placeholder", "detected: C:\\me3.exe");
    expect(await screen.findByText(/me3 0.9.0.*up to date/)).toBeInTheDocument();
  });

  test("a failed page read shows the backend's message and retries", async () => {
    server.use(
      http.get(`${BASE}/v1/pages/shell`, () => HttpResponse.json(shell)),
      http.get(`${BASE}/v1/pages/settings`, () => problem("boom", "The settings could not be read.", 500)),
      http.get(`${BASE}/v1/events`, () => new HttpResponse(new ReadableStream(), { headers: { "Content-Type": "text/event-stream" } })),
    );
    render(<AppWithBackend backend={backend} router={buildRouter(createMemoryHistory({ initialEntries: ["/settings"] }))} />);
    expect(await screen.findByText("The settings could not be read.", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  test("a switch, a choice and a number each call settings.set with their key", async () => {
    const { last } = boot();
    const user = userEvent.setup();
    await user.click(await screen.findByLabelText("Boot boost"));
    await waitFor(() => expect(last("settings.set")).toEqual({ key: "play_boot_boost", value: false }));
    await user.selectOptions(screen.getByLabelText("Log level"), "verbose");
    await waitFor(() => expect(last("settings.set")).toEqual({ key: "log_level", value: "verbose" }));
    const keep = screen.getByLabelText("How many to keep");
    await user.clear(keep);
    await user.type(keep, "40{Enter}");
    await waitFor(() => expect(last("settings.set")).toEqual({ key: "backups_keep", value: 40 }));
  });

  test("the theme is applied at once and saved through settings.set", async () => {
    const { last } = boot();
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Theme"), "light");
    expect(document.documentElement.dataset.theme).toBe("light");
    await waitFor(() => expect(last("settings.set")).toEqual({ key: "theme", value: "light" }));
    await user.selectOptions(screen.getByLabelText("Logo"), "ice");
    await waitFor(() => expect(last("settings.set")).toEqual({ key: "logo", value: "ice" }));
  });

  test("a refused path shows the backend's sentence under its field", async () => {
    boot({ "settings.set": () => problem("path_problem", "That file does not exist.") });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("me3"), "C:\\nope.exe{Enter}");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("That file does not exist.");
    expect(screen.getByLabelText("me3")).toHaveAttribute("aria-invalid", "true");
  });

  test("Browse picks a folder and saves it; Open folder asks the engine to open it", async () => {
    native.pickFolder.mockResolvedValue("D:\\Saves");
    const { last } = boot({ "settings.folder": () => HttpResponse.json({ path: "C:\\saves" }) });
    const user = userEvent.setup();
    const row = (await screen.findByLabelText("Saves folder")).closest("div.flex.flex-wrap")!.parentElement as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "Browse..." }));
    await waitFor(() => expect(last("settings.set")).toEqual({ key: "saves_dir", value: "D:\\Saves" }));
    await user.click(within(row).getByRole("button", { name: "Open folder" }));
    await waitFor(() => expect(last("settings.folder")).toEqual({ kind: "saves", open: true }));
  });

  test("renaming the folders is a plan: check, confirm, then the answer is posted", async () => {
    const posted: unknown[] = [];
    server.use(
      http.post(`${BASE}/v1/plans/:id`, async ({ request, params }) => {
        posted.push([params.id, await request.json()]);
        return HttpResponse.json({ job_id: "j1" });
      }),
    );
    const { last } = boot({
      "settings.rename_layout": () =>
        HttpResponse.json({
          plan_id: "p9",
          prompt: { kind: "confirm", title: "Rename folders?", changes: ["DLL mods: natives -> dll"], apply: "Rename" },
        }),
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Folder names" }));
    const apply = screen.getByRole("button", { name: "Apply" });
    expect(apply).toBeDisabled();
    const dll = screen.getByLabelText("DLL mods");
    await user.clear(dll);
    await user.type(dll, "dll");
    await waitFor(() => expect(last("settings.layout_check")).toMatchObject({ natives: "dll" }));
    await user.click(apply);
    expect(await screen.findByText("Rename folders?")).toBeInTheDocument();
    expect(last("settings.rename_layout")).toMatchObject({ natives: "dll", pattern: "{game}" });
    await user.click(screen.getByRole("button", { name: "Rename" }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toMatchObject(["p9", { ok: true }]);
  });

  test("an unusable folder name shows its sentence and keeps Apply off", async () => {
    boot({ "settings.layout_check": () => HttpResponse.json({ errors: { natives: "That name is not allowed." }, preview: "" }) });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Folder names" }));
    await user.type(screen.getByLabelText("DLL mods"), "x");
    expect(await screen.findByText("That name is not allowed.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled();
  });

  test("moving the profiles folder: pick, confirm, then Moving... with a Cancel that cancels the job", async () => {
    native.pickFolder.mockResolvedValue("E:\\Profiles");
    let cancelled = false;
    server.use(
      http.post(`${BASE}/v1/plans/:id`, () => HttpResponse.json({ job_id: "j7" })),
      http.post(`${BASE}/v1/jobs/j7/cancel`, () => {
        cancelled = true;
        return HttpResponse.json({});
      }),
    );
    const { last } = boot({
      "settings.relocate": () =>
        HttpResponse.json({ plan_id: "p3", prompt: { kind: "confirm", title: "Move to E:\\Profiles?", changes: [], apply: "Move" } }),
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Change..." }));
    await user.click(await screen.findByRole("button", { name: "Move" }));
    expect(last("settings.relocate")).toEqual({ folder: "E:\\Profiles" });
    expect(await screen.findByText("Moving...")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change..." })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(cancelled).toBe(true));
  });

  test("Move all with nothing to move shows the refusal", async () => {
    boot({
      "settings.move_all": () =>
        HttpResponse.json({ plan_id: null, prompt: { kind: "refusal", title: "Nothing to move", body: "No profiles are outside Bayle's folder." } }),
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Move all..." }));
    expect(await screen.findByText("No profiles are outside Bayle's folder.")).toBeInTheDocument();
  });

  test("the buttons call their ops: clear leftovers, check for updates, Steam shortcuts, logs, an update notice", async () => {
    native.pickFolder.mockResolvedValue("D:\\Out");
    const { last } = boot({
      "shell.steam_shortcuts": () => HttpResponse.json({ changed: [] }),
      "shell.save_logs": () => HttpResponse.json({ path: "D:\\Out\\logs.zip" }),
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Clear now" }));
    await waitFor(() => expect(last("settings.clear_leftovers")).toEqual({}));
    await user.click(screen.getByRole("button", { name: "Check for updates" }));
    await waitFor(() => expect(last("shell.check_updates")).toEqual({}));
    await user.click(screen.getByRole("button", { name: "Point Steam shortcuts here" }));
    await waitFor(() => expect(last("shell.steam_shortcuts")).toEqual({}));
    await user.click(screen.getByRole("button", { name: "Save..." }));
    await waitFor(() => expect(last("shell.save_logs")).toEqual({ folder: "D:\\Out" }));
    await user.click(await screen.findByRole("button", { name: "Update now" }));
    await waitFor(() => expect(last("shell.update_action")).toEqual({ notice_id: "flow", key: "update" }));
    await user.click(screen.getByRole("button", { name: "Dismiss: Bayle 4.7.0 is available" }));
    await waitFor(() => expect(last("shell.dismiss_notice")).toEqual({ notice_id: "flow" }));
  });
});
