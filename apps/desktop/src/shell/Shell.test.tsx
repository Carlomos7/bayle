import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, expect, test, vi } from "vitest";
import { AppWithBackend } from "@/App";
import { buildRouter } from "@/router";
import { backend, BASE, server } from "@/test/server";

const pickPath = vi.fn();
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: (o: unknown) => pickPath(o) }));
vi.mock("@tauri-apps/api/window", () => ({ getCurrentWindow: () => ({ close: vi.fn() }) }));

const games = [
  { key: "eldenring", name: "Elden Ring", short: "ER", tint: "", status: "installed", checked: true },
  { key: "nightreign", name: "Nightreign", short: "NR", tint: "", status: "installed", checked: false },
];
const base = {
  game: "eldenring",
  game_name: "Elden Ring",
  game_ready: true,
  game_running: false,
  games,
  profiles: ["Vanilla", "Overhaul"],
  profile_index: 1,
  mode: "profile",
  modes: [
    { mode: "profile", text: "Launch Profile", checked: true },
    { mode: "offline", text: "Launch Offline", checked: false },
  ],
  pill: { mode: "profile", mode_text: "Profile", state: "enabled", text: "Launch", reason: "", can_launch: true, warn: false },
  status: { text: "Ready", tone: "muted", busy: false, to_activity: true },
  unseen: 0,
  updates: { notices: [] as unknown[] },
};

const frame = (seq: number, type: string, data: unknown) =>
  `id: ${seq}\nevent: ${type}\ndata: ${JSON.stringify({ seq, job_id: null, type, data })}\n\n`;

const posts: { path: string; body: unknown }[] = [];

/** The backend: a shell page (overridable), an open event stream carrying `events`, and a recorder for every POST. */
function boot(shell: object = {}, events: string[] = []) {
  server.use(
    http.get(`${BASE}/v1/pages/shell`, () => HttpResponse.json({ ...base, ...shell })),
    http.get(`${BASE}/v1/events`, () => {
      const enc = new TextEncoder();
      const stream = new ReadableStream<Uint8Array>({ start: (c) => events.forEach((e) => c.enqueue(enc.encode(e))) });
      return new HttpResponse(stream, { headers: { "Content-Type": "text/event-stream" } });
    }),
    http.post(`${BASE}/v1/ops/:name`, async ({ request, params }) => {
      posts.push({ path: String(params.name), body: await request.json() });
      return HttpResponse.json({});
    }),
    http.post(`${BASE}/v1/prompts/:id`, async ({ request, params }) => {
      posts.push({ path: `prompt ${String(params.id)}`, body: await request.json() });
      return HttpResponse.json({});
    }),
  );
  render(<AppWithBackend backend={backend} router={buildRouter(createMemoryHistory({ initialEntries: ["/saves"] }))} />);
}

beforeEach(() => {
  posts.length = 0;
  pickPath.mockReset();
});

test("Launch runs shell.launch; a refusal says its reason", async () => {
  boot();
  server.use(
    http.post(`${BASE}/v1/ops/shell.launch`, () =>
      HttpResponse.json({ code: "cannot_launch", message: "Elden Ring is running", details: {} }, { status: 409 }),
    ),
  );
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Launch" }));
  expect(await screen.findByText("Elden Ring is running")).toBeInTheDocument();
});

test("Ctrl+L launches, a blocked pill does not, and the mode menu sets the mode", async () => {
  boot();
  const user = userEvent.setup();
  await screen.findByRole("button", { name: "Launch" });
  await user.keyboard("{Control>}l{/Control}");
  await vi.waitFor(() => expect(posts).toContainEqual({ path: "shell.launch", body: {} }));
  await user.click(screen.getByRole("button", { name: /Launch mode/ }));
  await user.click(await screen.findByRole("menuitemradio", { name: "Launch Offline" }));
  await vi.waitFor(() => expect(posts).toContainEqual({ path: "shell.set_mode", body: { mode: "offline" } }));
});

test("a blocked pill is disabled and the status line carries the reason and its link", async () => {
  boot({
    pill: { ...base.pill, state: "blocked", can_launch: false, reason: "No profile" },
    status: { text: "No profile", tone: "danger", link: { text: "Create a profile", action: "new_profile" } },
  });
  server.use(http.post(`${BASE}/v1/ops/shell.new_profile_offer`, () => HttpResponse.json({ name: "Elden Ring mods", seamless: true })));
  const user = userEvent.setup();
  expect(await screen.findByRole("button", { name: "Launch" })).toBeDisabled();
  await user.click(await screen.findByRole("button", { name: "Create a profile" }));
  const dialog = await screen.findByRole("dialog", { name: "New profile" });
  expect(within(dialog).getByLabelText("Profile name")).toHaveValue("Elden Ring mods");
  await user.click(within(dialog).getByRole("button", { name: "Create" }));
  await vi.waitFor(() =>
    expect(posts).toContainEqual({ path: "shell.new_profile", body: { name: "Elden Ring mods", include_seamless: true } }),
  );
});

test("game and profile menus call set_game and pick_profile; Add existing profile uses the file dialog", async () => {
  boot();
  pickPath.mockResolvedValue("C:\\mods\\a.me3");
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Game" }));
  await user.click(await screen.findByRole("menuitemcheckbox", { name: /Nightreign/ }));
  await vi.waitFor(() => expect(posts).toContainEqual({ path: "shell.set_game", body: { key: "nightreign" } }));

  await user.click(screen.getByRole("button", { name: "Profile" }));
  await user.click(await screen.findByRole("menuitemcheckbox", { name: "Vanilla" }));
  await vi.waitFor(() => expect(posts).toContainEqual({ path: "shell.pick_profile", body: { index: 0 } }));

  await user.click(screen.getByRole("button", { name: "Profile" }));
  await user.click(await screen.findByRole("menuitem", { name: /Add existing profile/ }));
  await vi.waitFor(() => expect(posts).toContainEqual({ path: "shell.add_profile", body: { path: "C:\\mods\\a.me3" } }));
});

test("a Launch-flow prompt opens the dialog and the answer goes to /v1/prompts/{id}", async () => {
  boot({}, [
    frame(1, "prompt", {
      prompt_id: "q7",
      kind: "choose",
      title: "The backup failed",
      lines: ["Retry?"],
      choices: [
        { key: "retry", label: "Retry", role: "primary" },
        { key: "cancel", label: "Cancel", role: "normal" },
      ],
    }),
  ]);
  const user = userEvent.setup();
  expect(await screen.findByRole("alertdialog", { name: "The backup failed" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Retry" }));
  await vi.waitFor(() => expect(posts).toContainEqual({ path: "prompt q7", body: { choice: "retry" } }));
});

test("update notices show their actions, which post to update_action, and dismiss", async () => {
  boot({
    updates: {
      notices: [
        {
          id: "flow",
          level: "info",
          title: "Bayle 9.9 is available",
          body: "Notes",
          closable: true,
          actions: [{ key: "update", label: "Update now", primary: true }],
        },
      ],
    },
  });
  const user = userEvent.setup();
  expect(await screen.findByText("Bayle 9.9 is available")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Update now" }));
  await vi.waitFor(() => expect(posts).toContainEqual({ path: "shell.update_action", body: { notice_id: "flow", key: "update" } }));
  await user.click(screen.getByRole("button", { name: /Dismiss/ }));
  await vi.waitFor(() => expect(posts).toContainEqual({ path: "shell.dismiss_notice", body: { notice_id: "flow" } }));
});

test("Help > Save logs asks for a folder and Check for updates forces a check", async () => {
  boot();
  pickPath.mockResolvedValue("C:\\out");
  server.use(http.post(`${BASE}/v1/ops/shell.save_logs`, () => HttpResponse.json({ path: "C:\\out\\logs.zip" })));
  const user = userEvent.setup();
  await user.click(await screen.findByRole("menuitem", { name: "Help" }));
  await user.click(await screen.findByRole("menuitem", { name: "Check for updates" }));
  await vi.waitFor(() => expect(posts).toContainEqual({ path: "shell.check_updates", body: { force: true } }));
  await user.click(screen.getByRole("menuitem", { name: "Help" }));
  await user.click(await screen.findByRole("menuitem", { name: "Save logs for support..." }));
  expect(await screen.findByText("Logs saved: C:\\out\\logs.zip")).toBeInTheDocument();
});

test("a game running shows Running with the pill disabled and Clear on a dead process runs the op", async () => {
  boot({
    game_running: true,
    pill: { ...base.pill, state: "running", text: "Running", can_launch: false },
    status: { text: "Dead game process", tone: "danger", link: { text: "Clear", action: "clear_dead" }, to_activity: false },
  });
  const user = userEvent.setup();
  expect(await screen.findByRole("button", { name: "Running" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Clear" }));
  await vi.waitFor(() => expect(posts).toContainEqual({ path: "shell.clear_dead_processes", body: {} }));
});
