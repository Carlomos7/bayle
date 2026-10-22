import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from "@tanstack/react-router";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { toast, Toaster } from "sonner";
import { afterEach, beforeAll, describe, expect, test, vi } from "vitest";
import { BackendProvider } from "@/api/backend";
import { PromptHost } from "@/components/PromptHost";
import { backend, BASE, server } from "@/test/server";
import { ThemeProvider } from "@/theme/ThemeProvider";
import { ModsHostContext, type ModsHost } from "./install-contract";
import { ModsPage } from "./ModsPage";
import { WORD_KEYS } from "./word-keys";

afterEach(() => void toast.dismiss());

beforeAll(() => {
  Element.prototype.setPointerCapture ??= () => {};
  Element.prototype.releasePointerCapture ??= () => {};
  // jsdom lays nothing out: give the virtual list a viewport (TanStack Virtual reads clientHeight/clientWidth)
  Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, value: 600 });
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 800 });
  // jsdom has no PointerEvent: the drag reads clientY from it
  if (!("PointerEvent" in window)) {
    class P extends MouseEvent {
      pointerId: number;
      constructor(type: string, init: PointerEventInit = {}) {
        super(type, init);
        this.pointerId = init.pointerId ?? 1;
      }
    }
    (window as unknown as { PointerEvent: unknown }).PointerEvent = P;
  }
});

const words: Record<string, string> = {
  ...Object.fromEntries(WORD_KEYS.map((k) => [k, k])),
  undo: "Undo",
  install: "Install mod",
  installFile: "From archive or DLL...",
  deleteProfile: "Delete profile...",
  profileSettings: "Profile settings...",
  parameters: "Parameters",
  loadOrder: "Load order",
  showAll: "Show all",
  save: "Save",
  cancel: "Cancel",
  close: "Close",
  toastOn: "{name} is on again",
  toastOff: "{name} is off. It stays in the profile and me3 skips it.",
  toastMoved: "Load order changed",
  toastRemoved: "Removed {name}",
  toastDeleted: "Profile {name} deleted. It is in Deleted profiles.",
  toastUndone: "Undone",
  toastTextSaved: ".me3 saved",
  editOptions: "Edit options",
  optionsTitle: "Mod options: {name}",
  duplicate: "Duplicate...",
  editAsText: "Edit as text",
  unsavedTitle: "Unsaved changes",
  optionsTip: "Mod options",
  removeTip: "Remove from the profile",
  rebuildFile: "Rebuild-tool file",
  profileRenameTip: "Rename profile",
};

const row = (index: number, position: number, name: string, kind: string, more: Record<string, unknown> = {}) => ({
  can_share: false,
  configs_tip: "",
  enabled: true,
  has_configs: false,
  index,
  kind,
  locked: false,
  more: "",
  name,
  path: `C:/p/${name}`,
  position,
  shared: 0,
  status: "",
  status_error: false,
  tags: [],
  ...more,
});

const clashes = Array.from({ length: 14 }, (_, i) => ({ path: `regulation${i}.bin`, winner: "flora", losers: "cloud", lost: false }));
const baseView = {
  profile: "C:/p/main.me3",
  has_profile: true,
  kind: "me3",
  source: "",
  rename_block: "",
  rename_code: "",
  tool_label: "",
  folder_kind: "",
  outside: false,
  folders: { 1: "flora", 2: "cloud", 3: "a.dll" },
  configs: { 3: ["a.ini"] },
  entries: [],
  rebuild_undo: null,
  overhaul: { visible: false, can_clean: false, can_remove: false, clean: "", install: "", remove: "" },
  overhaul_info: null,
  load_order: { title: "Load order", clash_note: "2 files", clash_total: 14, clashes, refused: [], stays_last: null },
  state: {
    title: "main",
    counts: "2 packages  ·  1 native",
    empty: "",
    health: { level: "success", text: "Merge: healthy" },
    notices: [{ key: "dll-folders", severity: "warning", text: "A DLL sits loose", action: "Fix", closable: true }],
    parameters: { action: "Rebuild", blocked: "", level: "warning", packs: "", pill: "Out of date", reasons: ["flora changed"], state: "stale", visible: true },
    groups: [
      {
        kind: "package",
        title: "Packages",
        count: "2",
        icon: "",
        empty: "",
        lines: [],
        rows: [
          row(1, 1, "flora", "package", { tags: [{ icon: "Info", level: "info", text: "Params", tip: "" }] }),
          row(2, 2, "cloud", "package"),
        ],
      },
      { kind: "native", title: "Natives (DLLs)", count: "1", icon: "", empty: "", lines: [], rows: [row(3, 1, "a.dll", "native", { has_configs: true, configs_tip: "a.ini" })] },
    ],
  },
  words,
};

type Handler = (body: Record<string, unknown>) => unknown;
interface Call {
  op: string;
  body: Record<string, unknown>;
}

function setup({ view = baseView, ops = {}, host, profiles = ["main"] }: { view?: unknown; ops?: Record<string, Handler>; host?: Partial<ModsHost>; profiles?: string[] } = {}) {
  const calls: Call[] = [];
  const posted: { path: string; body: unknown }[] = [];
  const fullHost: ModsHost = { openInstall: vi.fn(), newProfile: vi.fn(), ...host };
  server.use(
    http.get(`${BASE}/v1/pages/shell`, () => HttpResponse.json({ profiles, profile_index: 0, status: { busy: false, text: "", tone: "muted" } })),
    http.get(`${BASE}/v1/pages/mods`, () => (view instanceof Response ? view.clone() : HttpResponse.json(view as object))),
    http.post(`${BASE}/v1/ops/:op`, async ({ request, params }) => {
      const op = String(params.op);
      const body = (await request.json()) as Record<string, unknown>;
      calls.push({ op, body });
      const got = ops[op]?.(body);
      if (got instanceof Response) return got;
      return HttpResponse.json((got ?? {}) as object, { status: op in jobOps ? 202 : 200 });
    }),
    http.post(`${BASE}/v1/plans/:id`, async ({ request, params }) => {
      posted.push({ path: `/v1/plans/${String(params.id)}`, body: await request.json() });
      return HttpResponse.json({ job_id: "j-plan" });
    }),
    http.get(`${BASE}/v1/jobs/:id`, ({ params }) => HttpResponse.json(jobs[String(params.id)] ?? { id: params.id, state: "done", result: {}, undo: null, error: null })),
  );
  const root = createRootRoute({
    component: () => (
      <ModsHostContext value={fullHost}>
        <Outlet />
      </ModsHostContext>
    ),
  });
  const page = createRoute({ getParentRoute: () => root, path: "/mods", component: ModsPage });
  const other = ["/profile-transfer", "/mod-configs"].map((path) => createRoute({ getParentRoute: () => root, path, component: () => <p>{path}</p> }));
  const router = createRouter({ routeTree: root.addChildren([page, ...other]), history: createMemoryHistory({ initialEntries: ["/mods"] }) });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <ThemeProvider>
      <QueryClientProvider client={qc}>
        <BackendProvider backend={backend}>
          <PromptHost>
            <RouterProvider router={router} />
            <Toaster />
          </PromptHost>
        </BackendProvider>
      </QueryClientProvider>
    </ThemeProvider>,
  );
  return { calls, posted, host: fullHost, router, user: userEvent.setup() };
}

// ops that answer 202 with a job id
const jobOps: Record<string, true> = { "mods.remove": true, "mods.rebuild": true, "mods.duplicate_profile": true, "mods.rename_profile": true };
const jobs: Record<string, unknown> = {};
const jobStarted = (id: string, result: unknown = {}) => {
  jobs[id] = { id, state: "done", result, undo: null, error: null };
  return { job_id: id };
};
const problem = (code: string, message: string, details: object = {}, status = 409) =>
  HttpResponse.json({ code, message, details }, { status, headers: { "Content-Type": "application/problem+json" } });
const callsTo = (calls: Call[], op: string) => calls.filter((c) => c.op === op);

describe("Mods page states", () => {
  test("loading, then the rows with their tags, counts, health and notices", async () => {
    setup();
    expect(await screen.findByText("flora")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Mods" })).toBeInTheDocument();
    expect(screen.getByText("Params")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "main" })).toBeInTheDocument();
    expect(screen.getByText(/2 packages/)).toBeInTheDocument();
    expect(screen.getByText("Merge: healthy")).toBeInTheDocument();
    expect(screen.getByText("A DLL sits loose")).toBeInTheDocument();
    expect(screen.getByText("a.dll")).toBeInTheDocument();
    expect(screen.getByText("Out of date")).toBeInTheDocument();
  });

  test("a refused page shows the backend's message", async () => {
    setup({ view: problem("no_game", "No game is selected.") });
    expect(await screen.findByRole("alert")).toHaveTextContent("No game is selected.");
  });

  test("no profile: the page says how to start and the button asks the shell for its New profile dialog", async () => {
    const empty = { ...baseView, has_profile: false, profile: "", state: { ...baseView.state, empty: "You have no profile yet.", groups: [], notices: [] } };
    const { host, user } = setup({ view: empty, profiles: [] });
    expect(await screen.findByText("You have no profile yet.")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "createProfile" }));
    expect(host.newProfile).toHaveBeenCalled();
    expect(screen.queryByText("Packages")).not.toBeInTheDocument();
  });
});

describe("rows", () => {
  test("the switch calls mods.set_enabled, says it in the page's words and Undo calls mods.undo_change", async () => {
    const { calls, user } = setup({ ops: { "mods.set_enabled": () => ({ note: "profile: off", name: "flora" }) } });
    await user.click(await screen.findByRole("switch", { name: "flora" }));
    expect(callsTo(calls, "mods.set_enabled")[0]?.body).toEqual({ profile: "C:/p/main.me3", index: 1, enabled: false });
    expect(await screen.findByText("flora is off. It stays in the profile and me3 skips it.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(callsTo(calls, "mods.undo_change")).toHaveLength(1));
    expect(await screen.findByText("Undone")).toBeInTheDocument();
  });

  test("remove: the confirm opens, its option rides the retry, and the Undo toast calls mods.undo_removal", async () => {
    let first = true;
    const { calls, user } = setup({
      ops: {
        "mods.remove": () => {
          if (first) {
            first = false;
            return problem("needs_confirmation", "Remove cloud?", {
              prompt: { kind: "confirm", title: "Remove cloud?", changes: ["Takes it out"], apply: "Remove", option: "Delete its folder", option_checked: false },
            });
          }
          return jobStarted("j-remove", { undo: { id: "u1" } });
        },
        "mods.undo_removal": () => ({ note: "back", name: "cloud" }),
      },
    });
    await user.click(await screen.findByRole("button", { name: /Remove from the profile: cloud/ }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByLabelText("Delete its folder"));
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(callsTo(calls, "mods.remove")).toHaveLength(2));
    expect(callsTo(calls, "mods.remove")[1]?.body).toMatchObject({ index: 2, name: "cloud", confirmed: true, delete_folder: true });
    // a confirm was asked, so Undo lives in Activity: no Undo toast
    expect(screen.queryByText("Removed cloud")).not.toBeInTheDocument();
  });

  test("remove without a confirm offers Undo right in the toast", async () => {
    const { calls, user } = setup({
      ops: { "mods.remove": () => jobStarted("j-r2", { undo: { id: "u9" } }), "mods.undo_removal": () => ({ note: "back" }) },
    });
    await user.click(await screen.findByRole("button", { name: /Remove from the profile: cloud/ }));
    expect(await screen.findByText("Removed cloud")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(callsTo(calls, "mods.undo_removal")[0]?.body).toEqual({ undo: { id: "u9" } }));
  });

  test("the context menu moves to the top or bottom through mods.move", async () => {
    const { calls, user } = setup({ ops: { "mods.move": () => ({ moved: true, name: "flora" }) } });
    const rowEl = await screen.findByLabelText("flora", { selector: "[data-pos]" });
    fireEvent.contextMenu(rowEl);
    await user.click(await screen.findByRole("menuitem", { name: "moveBottom" }));
    await waitFor(() => expect(callsTo(calls, "mods.move")[0]?.body).toEqual({ profile: "C:/p/main.me3", index: 1, to: 1 }));
    expect(await screen.findByText("Load order changed")).toBeInTheDocument();
  });
});

describe("tick lists", () => {
  test("Use in other profiles asks the choices, shows the rows, and starts the job with the ticked ones", async () => {
    const shared = structuredClone(baseView);
    shared.state.groups[0]!.rows[0] = row(1, 1, "flora", "package", { shared: 2 });
    const { calls, user } = setup({
      view: shared,
      ops: {
        "mods.library_use_choices": () => ({ prompt: { kind: "pick", title: "Use flora in", body: "Pick the profiles", apply: "Use it", rows: ["Alpha", "Beta"], ticked: [] } }),
        "mods.library_use": () => jobStarted("j-use"),
      },
    });
    const rowEl = await screen.findByLabelText("flora", { selector: "[data-pos]" });
    fireEvent.contextMenu(rowEl);
    await user.click(await screen.findByRole("menuitem", { name: "useInOthers" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByRole("button", { name: "Use it" })).toBeDisabled(); // nothing is ticked at first
    await user.click(within(dialog).getByLabelText("Beta"));
    await user.click(within(dialog).getByRole("button", { name: "Use it" }));
    await waitFor(() => expect(callsTo(calls, "mods.library_use")[0]?.body).toEqual({ profile: "C:/p/main.me3", index: 1, targets: [1], name: "flora" }));
  });
});

describe("drag and drop", () => {
  const grip = () => screen.getByRole("button", { name: /^flora: drag to reorder/ });

  test("one mods.drag at the start, none while moving, the refusal shown for the spot, mods.move on drop", async () => {
    const { calls } = setup({
      ops: {
        "mods.drag": () => ({ kind: "package", reasons: { 0: "", 1: "cloud must load after flora" } }),
        "mods.move": () => ({ moved: false, problem: "cloud must load after flora", decided_by: 2 }),
        "mods.options": () => ({ index: 2, name: "cloud", kind: "package", enabled: true, id: "cloud", load_after: [], load_before: [], others: ["flora"], optional: false, load_early: false, init_kind: 0, init_value: "", finalizer: "", overlay: -1, rebuild_file: "" }),
      },
    });
    await screen.findByText("flora");
    fireEvent.pointerDown(grip(), { clientY: 100, button: 0, pointerId: 1 });
    await waitFor(() => expect(callsTo(calls, "mods.drag")).toHaveLength(1));
    expect(callsTo(calls, "mods.drag")[0]?.body).toEqual({ profile: "C:/p/main.me3", index: 1 });
    fireEvent.pointerMove(grip(), { clientY: 156, pointerId: 1 }); // one row (56 px) down
    fireEvent.pointerMove(grip(), { clientY: 158, pointerId: 1 });
    await waitFor(() => expect(screen.getAllByText("cloud must load after flora").length).toBeGreaterThan(0));
    expect(callsTo(calls, "mods.drag")).toHaveLength(1); // no extra call during the drag
    fireEvent.pointerUp(grip(), { clientY: 158, pointerId: 1 });
    await waitFor(() => expect(callsTo(calls, "mods.move")[0]?.body).toEqual({ profile: "C:/p/main.me3", index: 1, to: 1 }));
    // the refusal is said with the entry that decided it, and Edit options opens that entry's options
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edit options" }));
    await waitFor(() => expect(callsTo(calls, "mods.options")[0]?.body).toEqual({ profile: "C:/p/main.me3", index: 2 }));
    expect(await screen.findByRole("dialog", { name: "Mod options: cloud" })).toBeInTheDocument();
  });

  test("Escape during a drag cancels the drop", async () => {
    const { calls } = setup({ ops: { "mods.drag": () => ({ kind: "package", reasons: {} }) } });
    await screen.findByText("flora");
    fireEvent.pointerDown(grip(), { clientY: 0, button: 0, pointerId: 1 });
    fireEvent.pointerMove(grip(), { clientY: 60, pointerId: 1 });
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.pointerUp(grip(), { clientY: 60, pointerId: 1 });
    await new Promise((r) => setTimeout(r, 50));
    expect(callsTo(calls, "mods.move")).toHaveLength(0);
  });

  test("the keyboard twin: Ctrl+Down on a row moves it down by one", async () => {
    const { calls, user } = setup({ ops: { "mods.move": () => ({ moved: true, name: "flora" }) } });
    const rowEl = await screen.findByLabelText("flora", { selector: "[data-pos]" });
    rowEl.focus();
    await user.keyboard("{Control>}{ArrowDown}{/Control}");
    await waitFor(() => expect(callsTo(calls, "mods.move")[0]?.body).toEqual({ profile: "C:/p/main.me3", index: 1, to: 1 }));
  });

  test("a locked row has no grip to drag", async () => {
    const locked = structuredClone(baseView);
    locked.state.groups[0]!.rows[1]!.locked = true;
    setup({ view: locked });
    expect(await screen.findByRole("button", { name: /^cloud: Its rebuild tool|^cloud: lockedTip/ })).toBeDisabled();
  });
});

describe("plans, jobs and notices", () => {
  test("Delete profile is a plan: its confirm opens, answering posts the plan and the deleted toast follows the job", async () => {
    const { posted, user } = setup({
      ops: {
        "mods.delete_profile": () => ({
          plan_id: "p-del",
          prompt: { kind: "confirm", title: "Delete profile main?", changes: ["Moves it to Deleted profiles"], apply: "Delete" },
        }),
      },
    });
    await screen.findByText("flora");
    await user.click(screen.getByRole("button", { name: "gearTip" }));
    await user.click(await screen.findByRole("menuitem", { name: "Delete profile..." }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Delete profile main?")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(posted[0]).toMatchObject({ path: "/v1/plans/p-del", body: { ok: true } }));
    expect(await screen.findByText("Profile main deleted. It is in Deleted profiles.")).toBeInTheDocument();
  });

  test("Rebuild is a job; a rebuild tool not yet allowed asks first, and yes runs it again with allow", async () => {
    let first = true;
    const { calls, user } = setup({
      ops: {
        "mods.rebuild": () => {
          if (first) {
            first = false;
            return problem("needs_confirmation", "Allow it?", { prompt: { kind: "confirm", title: "Run the rebuild tool?", changes: [], apply: "Allow" } });
          }
          return jobStarted("j-rb");
        },
      },
    });
    await user.click(await screen.findByRole("button", { name: "Rebuild" }));
    await user.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Allow" }));
    await waitFor(() => expect(callsTo(calls, "mods.rebuild")).toHaveLength(2));
    expect(callsTo(calls, "mods.rebuild")[0]?.body).toMatchObject({ combine: null });
    expect(callsTo(calls, "mods.rebuild")[1]?.body).toMatchObject({ confirmed: true, allow: true });
  });

  test("closing an InfoBar calls mods.close_notice; its action runs the notice's op", async () => {
    const { calls, user } = setup({
      ops: { "mods.dll_folders": () => ({ plan_id: "p-dll", prompt: { kind: "confirm", title: "Give each DLL a folder?", changes: [], apply: "Do it" } }) },
    });
    await user.click(await screen.findByRole("button", { name: "Fix" }));
    expect(await screen.findByText("Give each DLL a folder?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(callsTo(calls, "mods.close_notice")[0]?.body).toEqual({ profile: "C:/p/main.me3", key: "dll-folders" }));
  });

  test("a plan the backend refuses is only told: nothing is posted", async () => {
    const { posted, user } = setup({
      ops: {
        "mods.delete_profile": () => ({ plan_id: null, prompt: { kind: "refusal", title: "Not this one", body: "main is managed by its installer. Delete it there." } }),
      },
    });
    await screen.findByText("flora");
    await user.click(screen.getByRole("button", { name: "gearTip" }));
    await user.click(await screen.findByRole("menuitem", { name: "Delete profile..." }));
    expect(await screen.findByText("main is managed by its installer. Delete it there.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(posted).toHaveLength(0);
  });

  test("Install mod hands over to the install dialog's contract", async () => {
    const { host, user } = setup();
    await user.click(await screen.findByRole("button", { name: "Install mod" }));
    await user.click(await screen.findByRole("menuitem", { name: "From archive or DLL..." }));
    expect(host.openInstall).toHaveBeenCalledWith({ from: "file" });
  });
});

describe("dialogs and panels", () => {
  test("Mod options reads mods.options and saves through mods.save_options", async () => {
    const { calls, user } = setup({
      ops: {
        "mods.options": () => ({ index: 3, name: "a.dll", kind: "native", enabled: true, id: "", load_after: [], load_before: [], others: [], optional: false, load_early: true, init_kind: 0, init_value: "", finalizer: "", overlay: -1, rebuild_file: "" }),
        "mods.save_options": () => ({ note: "saved", name: "a.dll" }),
      },
    });
    await user.click(await screen.findByRole("button", { name: "Mod options: a.dll" }));
    expect(await screen.findByRole("dialog", { name: "Mod options: a.dll" })).toBeInTheDocument();
    expect(screen.getByText(/configFiles: a.ini/)).toBeInTheDocument();
    await user.click(screen.getByLabelText("loadEarly"));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(callsTo(calls, "mods.save_options")).toHaveLength(1));
    expect(callsTo(calls, "mods.save_options")[0]?.body).toMatchObject({ index: 3, load_early: false, enabled: true, overlay: -1 });
    expect(await screen.findByText("a.dll: options saved".replace("a.dll: options saved", "toastOptionsSaved"))).toBeInTheDocument();
  });

  test("the health pill opens the Load order panel, which cuts the clash list until Show all", async () => {
    const { user } = setup();
    await user.click(await screen.findByRole("button", { name: "Merge: healthy" }));
    const panel = await screen.findByRole("dialog", { name: "Load order" });
    expect(within(panel).getAllByText(/^regulation\d+\.bin$/)).toHaveLength(12);
    await user.click(within(panel).getByRole("button", { name: "Show all (14)" }));
    expect(within(panel).getAllByText(/^regulation\d+\.bin$/)).toHaveLength(14);
  });

  test("Edit as text reads the file, gates Save on the parse check, saves, and asks before leaving unsaved text", async () => {
    const { calls, user } = setup({
      ops: {
        "mods.text": () => ({ text: "a = 1", crlf: false }),
        "mods.check_text": (b) => ({ problem: String(b.text).includes("!") ? "line 1: bad" : "" }),
        "mods.save_text": () => ({ note: "saved" }),
      },
    });
    const toggle = await screen.findByRole("switch", { name: "Edit as text" });
    await user.click(toggle);
    const area = await screen.findByLabelText("me3");
    await waitFor(() => expect(area).toHaveValue("a = 1"));
    await user.type(area, "!");
    expect(await screen.findByText("line 1: bad", undefined, { timeout: 2000 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.type(area, "{Backspace}2");
    await waitFor(() => expect(screen.queryByText("line 1: bad")).not.toBeInTheDocument(), { timeout: 2000 });
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(callsTo(calls, "mods.save_text")[0]?.body).toEqual({ profile: "C:/p/main.me3", text: "a = 12", crlf: false }));
    // leaving with unsaved edits asks
    await user.type(area, "3");
    await user.click(screen.getByRole("switch", { name: "Edit as text" }));
    expect(await screen.findByText("Unsaved changes", { selector: "h2" })).toBeInTheDocument();
  });

  test("renaming the profile checks the name live and starts mods.rename_profile", async () => {
    const { calls, user } = setup({
      ops: { "mods.profile_name_check": (b) => ({ problem: b.name === "taken" ? "That name is taken." : "" }), "mods.rename_profile": () => jobStarted("j-rn") },
    });
    await user.click(await screen.findByRole("button", { name: "main" }));
    const input = screen.getByLabelText("profileRenameField");
    await user.clear(input);
    await user.type(input, "taken");
    expect(await screen.findByText("That name is taken.", undefined, { timeout: 2000 })).toBeInTheDocument();
    await user.clear(input);
    await user.type(input, "fresh{Enter}");
    await waitFor(() => expect(callsTo(calls, "mods.rename_profile")[0]?.body).toMatchObject({ profile: "C:/p/main.me3", name: "fresh", kind: "me3" }));
  });
});
