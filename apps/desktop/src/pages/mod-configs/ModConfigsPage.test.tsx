import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { BackendProvider } from "@/api/backend";
import { PromptHost } from "@/components/PromptHost";
import { sonnerToasts } from "@/components/toasts";
import { backend, BASE, server } from "@/test/server";
import { ModConfigsPage } from "./ModConfigsPage";
import * as native from "@/lib/native";

// jsdom cannot type into CodeMirror: a textarea stands in for it here (the editor has its own test)
vi.mock("@/components/CodeEditor", () => ({
  CodeEditor: ({ value, onChange, "aria-label": label }: { value: string; onChange?: (t: string) => void; "aria-label"?: string }) => (
    <textarea aria-label={label} value={value} onChange={(e) => onChange?.(e.target.value)} />
  ),
}));
vi.mock("@/lib/native", () => ({ pickFile: vi.fn(), openFolder: vi.fn() }));

const WORDS: Record<string, string> = {
  title: "Mod Configs",
  noProfile: "Pick a profile first.",
  noMods: "No mod in this profile has a settings file.",
  pickFile: "Pick a file to edit it.",
  editAsText: "Edit as text",
  save: "Save",
  discard: "Discard",
  resetAll: "Reset all",
  reset: "Reset to default",
  changed: "Changed",
  diskChanged: "This file changed outside the launcher.",
  reload: "Reload",
  noChanges: "No changes",
  changeOne: "{n} change not saved",
  changeMany: "{n} changes not saved",
  emptyPickTitle: "Pick a file to edit",
  emptyPickBody: "Its settings show here as a form.",
  emptyNoFilesTitle: "No settings files yet",
  emptyNoFilesBody: "Attach a settings file.",
  goToMods: "Go to Mods",
  unsavedTitle: "Unsaved changes",
  unsavedBody: "This file has changes that are not saved.",
  attach: "Attach a file...",
  detach: "Detach",
  password: "Password",
  showPassword: "Show",
  hidePassword: "Hide",
  difficulty: "Difficulty",
  preset: "Party size",
  language: "Language",
  otherSettings: "Other settings",
  share: "Share with a friend",
  copy: "Copy settings",
  paste: "Paste settings",
  load: "Load settings...",
  saveAs: "Save settings...",
  more: "More",
  disabled: "Disabled",
  setUpOverhaul: "Set up as an overhaul...",
  turnOffOverhaul: "Turn off overhaul setup...",
  setUpModLink: "Set up a mod as an overhaul...",
  readonly: "Only Edit as text can change this one",
  copied: "Settings copied.",
  savedOne: "{n} setting saved.",
  savedMany: "{n} settings saved.",
  emptyPasswordTitle: "Password needed",
  emptyPasswordBody: "The Seamless Co-op password cannot be empty.",
  notSavedTitle: "Not saved",
  findSetting: "Find a setting",
  pickOverhaulTitle: "Set up which mod as an overhaul?",
  pickOverhaulBody: "Tick the mod to set up.",
  pickOverhaulApply: "Next",
  cantOpen: "Can't open {name}",
};

const row = (key: string, value: string, more: object = {}) => ({
  section: "GAMEPLAY",
  key,
  label: key,
  blurb: "",
  help: "",
  kind: "text",
  value,
  choices: [],
  lo: 0,
  hi: 0,
  tip: "",
  default: null,
  onValue: "1",
  offValue: "0",
  ...more,
});

const SEAMLESS = { key: "seamless", name: "Seamless Co-op", kind: "seamless", target: null, setup: null, files: [{ path: "C:/g/ersc_settings.ini", how: "seamless", exists: true, kind: "seamless" }] };
const NATIVE = {
  key: "native:C:/m/Mod.dll",
  name: "Mod",
  kind: "native",
  target: "C:/m/Mod.dll",
  setup: null,
  files: [
    { path: "C:/m/mod.toml", how: "found", exists: true, kind: "form" },
    { path: "C:/m/notes.txt", how: "found", exists: true, kind: "text" },
  ],
};
const treeOf = (n: typeof SEAMLESS | typeof NATIVE): object =>
  n.kind === "overhaul"
    ? { key: n.key, kind: "overhaul", name: `Overhaul setup: ${n.name}`, sub: "your config, not verified", disabled: false, disabledTip: "", muted: false, action: "turnOff", files: [{ path: n.files[0]!.path, name: "Setup", kind: "overhaul", attached: false }] }
    : plainTree(n);
const plainTree = (n: typeof SEAMLESS | typeof NATIVE) => ({
  key: n.key,
  kind: n.kind,
  name: n.name,
  sub: "",
  disabled: false,
  disabledTip: "",
  muted: false,
  action: n.kind === "native" ? "setUp" : "",
  files: n.files.map((f) => ({ path: f.path, name: f.path.split("/").pop(), kind: f.kind, attached: false })),
});

const READ_BASE = { encoding: "utf-8", crlf: false, sha: "sha1", stamp: [1, 2], form_note: "", seamless: null, seamless_view: {} };
const TOML_READ = {
  ...READ_BASE,
  path: "C:/m/mod.toml",
  text: "speed = 3\nfast = true\n",
  has_form: true,
  sections: [
    {
      title: "",
      path: "",
      rows: [
        row("speed", "3", { section: "", kind: "int", hi: 10, tip: "Default: 1", default: "1" }),
        row("fast", "true", { section: "", kind: "bool", onValue: "true", offValue: "false" }),
      ],
    },
  ],
};
const TEXT_READ = { ...READ_BASE, path: "C:/m/notes.txt", text: "hello", has_form: false, sections: [] };
const SEAMLESS_READ = {
  ...READ_BASE,
  path: "C:/g/ersc_settings.ini",
  text: "[PASSWORD]\ncooppassword = room\n",
  has_form: true,
  seamless: {},
  sections: [{ title: "Gameplay", path: "GAMEPLAY", rows: [row("allow_invaders", "1", { kind: "bool" })] }],
  seamless_view: {
    hasPassword: true,
    password: "room",
    presets: ["Solo", "Duo", "Custom"],
    presetKeys: ["Solo", "Duo", "Custom"],
    preset: "Solo",
    scaling: [{ key: "enemy_health", label: "Enemy health", value: 100 }],
    scalingHint: "",
    presetValues: { Solo: [100], Duo: [180] },
    languages: [{ value: "", label: "Game language" }],
    language: "",
    fingerprint: "Parameters 1234",
    fingerprintNote: "",
  },
};

type Json = Record<string, unknown>;
interface Posted {
  op: string;
  body: Json;
}

function mount(opts: { nodes?: object[]; profile?: string; reads?: Record<string, Json>; ops?: Record<string, (body: Json) => Response | Json> } = {}) {
  const posted: Posted[] = [];
  const nodes = (opts.nodes ?? [SEAMLESS, NATIVE]) as (typeof SEAMLESS)[];
  const reads: Record<string, Json> = { "C:/m/mod.toml": TOML_READ, "C:/m/notes.txt": TEXT_READ, "C:/g/ersc_settings.ini": SEAMLESS_READ, ...opts.reads };
  server.use(
    http.get(`${BASE}/v1/pages/mod_configs`, () =>
      HttpResponse.json({ profile: opts.profile ?? "C:/p/My.me3", nodes, words: WORDS, tree: nodes.map((n) => treeOf(n)) }),
    ),
    http.post(`${BASE}/v1/ops/:op`, async ({ request, params }) => {
      const op = String(params.op);
      const body = (await request.json()) as Json;
      posted.push({ op, body });
      const custom = opts.ops?.[op];
      if (custom) {
        const got = custom(body);
        return got instanceof Response ? got : HttpResponse.json(got);
      }
      if (op === "mod_configs.open") return HttpResponse.json(reads[String(body.path)]);
      if (op === "mod_configs.stamp") return HttpResponse.json({ stamp: [1, 2] });
      if (op === "mod_configs.check_text") return HttpResponse.json({ line: 0, message: "" });
      if (op === "mod_configs.save") return HttpResponse.json({ name: "x", saved: 1, missing: [], said: "1 setting saved.", missing_said: "" });
      return HttpResponse.json({});
    }),
    http.post(`${BASE}/v1/plans/:id`, async ({ request, params }) => {
      posted.push({ op: `plan:${String(params.id)}`, body: (await request.json()) as Json });
      return HttpResponse.json({ job_id: null });
    }),
  );
  const root = createRootRoute({ component: ModConfigsPage });
  const router = createRouter({ routeTree: root.addChildren([createRoute({ getParentRoute: () => root, path: "/" }), createRoute({ getParentRoute: () => root, path: "/mods" })]), history: createMemoryHistory({ initialEntries: ["/"] }) });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <BackendProvider backend={backend}>
        <PromptHost>
          <RouterProvider router={router} />
        </PromptHost>
      </BackendProvider>
    </QueryClientProvider>,
  );
  return { posted, router, ops: (name: string) => posted.filter((p) => p.op === name) };
}

const notice = vi.spyOn(sonnerToasts, "notice");
beforeEach(() => {
  notice.mockClear();
  vi.mocked(native.pickFile).mockReset();
});

describe("Mod Configs page", () => {
  test("lists the mods with settings files and opens the first file as a form", async () => {
    mount();
    expect(await screen.findByTestId("file_ersc_settings.ini")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Mod Configs" })).toBeInTheDocument();
    expect(screen.getByText("My")).toBeInTheDocument();
    expect(await screen.findByLabelText("Password")).toHaveValue("room");
    expect(screen.getByText("Parameters 1234")).toBeInTheDocument();
    expect(screen.getByTestId("file_ersc_settings.ini")).toHaveAttribute("aria-current", "true");
  });

  test("a profile with no settings files says so and links to Mods", async () => {
    const { router } = mount({ nodes: [] });
    expect(await screen.findByText("No settings files yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Go to Mods" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/mods"));
  });

  test("no profile asks for one", async () => {
    mount({ nodes: [], profile: "" });
    expect(await screen.findAllByText("Pick a profile first.")).not.toHaveLength(0);
  });

  test("a refused page shows the backend's message", async () => {
    server.use(http.get(`${BASE}/v1/pages/mod_configs`, () => HttpResponse.json({ code: "no_game", message: "No game here.", details: {} }, { status: 409 })));
    const root = createRootRoute({ component: ModConfigsPage });
    const router = createRouter({ routeTree: root.addChildren([createRoute({ getParentRoute: () => root, path: "/" })]), history: createMemoryHistory() });
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <BackendProvider backend={backend}>
          <PromptHost>
            <RouterProvider router={router} />
          </PromptHost>
        </BackendProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("No game here.");
  });

  test("editing a setting counts the change; Save writes only that value with the sha it was read with", async () => {
    const user = userEvent.setup();
    const { ops } = mount({ nodes: [NATIVE] });
    const speed = await screen.findByLabelText("speed");
    expect(screen.getByRole("status", { name: "" })).toHaveTextContent("No changes");
    await user.clear(speed);
    await user.type(speed, "7");
    expect(screen.getByText("1 change not saved")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(ops("mod_configs.save")).toHaveLength(1));
    expect(ops("mod_configs.save")[0]!.body).toEqual({ path: "C:/m/mod.toml", expect: "sha1", kind: "values", edits: [{ section: "", key: "speed", value: "7" }] });
    await waitFor(() => expect(notice).toHaveBeenCalledWith("1 setting saved."));
  });

  test("Reset puts a stated default back, and Reset all does it for every setting", async () => {
    const user = userEvent.setup();
    mount({ nodes: [NATIVE] });
    const speed = await screen.findByLabelText("speed");
    await user.click(screen.getByRole("button", { name: "Reset to default" }));
    expect(speed).toHaveValue(1);
    expect(screen.getByText("1 change not saved")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Discard" }));
    await waitFor(() => expect(screen.getByLabelText("speed")).toHaveValue(3));
    await user.click(screen.getByRole("button", { name: "Reset all" }));
    expect(screen.getByLabelText("speed")).toHaveValue(1);
  });

  test("moving to another file with unsaved changes asks first; Cancel stays, Discard goes on", async () => {
    const user = userEvent.setup();
    mount({ nodes: [NATIVE] });
    await user.type(await screen.findByLabelText("speed"), "5");
    await user.click(screen.getByTestId("file_notes.txt"));
    const dialog = await screen.findByRole("alertdialog", { name: "Unsaved changes" });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.getByLabelText("speed")).toBeInTheDocument();
    await user.click(screen.getByTestId("file_notes.txt"));
    await user.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Discard" }));
    expect(await screen.findByLabelText("Mod / notes.txt")).toHaveValue("hello");
  });

  test("leaving the page with unsaved changes asks first", async () => {
    const user = userEvent.setup();
    const { router } = mount({ nodes: [NATIVE] });
    await user.type(await screen.findByLabelText("speed"), "5");
    void router.navigate({ to: "/mods" });
    const dialog = await screen.findByRole("alertdialog", { name: "Unsaved changes" });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(router.state.location.pathname).toBe("/");
    void router.navigate({ to: "/mods" });
    await user.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Discard" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/mods"));
  });

  test("a text file opens in the editor; Save sends all of the text", async () => {
    const user = userEvent.setup();
    const { ops } = mount({ nodes: [NATIVE] });
    await user.click(await screen.findByTestId("file_notes.txt"));
    const editor = await screen.findByLabelText("Mod / notes.txt");
    await user.type(editor, "!");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(ops("mod_configs.save")).toHaveLength(1));
    expect(ops("mod_configs.save")[0]!.body).toMatchObject({ path: "C:/m/notes.txt", kind: "text", text: "hello!" });
  });

  test("Edit as text switches a form file to its text", async () => {
    const user = userEvent.setup();
    mount({ nodes: [NATIVE] });
    await user.click(await screen.findByRole("switch", { name: "Edit as text" }));
    expect(await screen.findByLabelText("Mod / mod.toml")).toHaveValue("speed = 3\nfast = true\n");
  });

  test("Seamless Co-op: an empty password is refused in the backend's words and nothing is lost", async () => {
    const user = userEvent.setup();
    mount({
      nodes: [SEAMLESS],
      ops: { "mod_configs.save": () => HttpResponse.json({ code: "password_empty", message: "The Seamless Co-op password cannot be empty.", details: {} }, { status: 422 }) },
    });
    const pw = await screen.findByLabelText("Password");
    expect(pw).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: "Show" }));
    expect(pw).toHaveAttribute("type", "text");
    await user.clear(pw);
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(notice).toHaveBeenCalledWith("Password needed. The Seamless Co-op password cannot be empty.", { error: true }));
    expect(screen.getByText("1 change not saved")).toBeInTheDocument();
  });

  test("Seamless Co-op: a preset fills the difficulty numbers and a number makes it Custom", async () => {
    const user = userEvent.setup();
    const { ops } = mount({ nodes: [SEAMLESS] });
    const preset = await screen.findByLabelText("Party size");
    await user.selectOptions(preset, "Duo");
    expect(screen.getByLabelText("Enemy health")).toHaveValue(180);
    await user.clear(screen.getByLabelText("Enemy health"));
    await user.type(screen.getByLabelText("Enemy health"), "150");
    expect(screen.getByLabelText("Party size")).toHaveValue("Custom");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(ops("mod_configs.save")).toHaveLength(1));
    expect(ops("mod_configs.save")[0]!.body).toMatchObject({ kind: "seamless", edits: [{ section: "SCALING", key: "enemy_health", value: "150" }] });
  });

  test("Copy settings puts the shared text on the clipboard", async () => {
    const user = userEvent.setup();
    const { ops } = mount({ nodes: [SEAMLESS], ops: { "mod_configs.share": () => ({ text: "[PASSWORD]\ncooppassword = room\n" }) } });
    const write = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    await user.click(await screen.findByRole("button", { name: "Copy settings" }));
    await waitFor(() => expect(write).toHaveBeenCalledWith("[PASSWORD]\ncooppassword = room\n"));
    expect(ops("mod_configs.share")[0]!.body).toEqual({ ini: "C:/g/ersc_settings.ini" });
    expect(notice).toHaveBeenCalledWith("Settings copied.");
  });

  test("Paste settings shows what would change, and Apply answers the plan", async () => {
    const user = userEvent.setup();
    const { posted } = mount({
      nodes: [SEAMLESS],
      ops: {
        "mod_configs.paste": () => ({
          plan_id: "pl1",
          prompt: { kind: "confirm", title: "Apply 1 setting from your friend", changes: ["Password:  room  →  castle"], apply: "Apply" },
        }),
      },
    });
    vi.spyOn(navigator.clipboard, "readText").mockResolvedValue("cooppassword = castle");
    await user.click(await screen.findByRole("button", { name: "Paste settings" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Apply 1 setting from your friend" });
    expect(posted.find((p) => p.op === "mod_configs.paste")!.body).toEqual({ ini: "C:/g/ersc_settings.ini", text: "cooppassword = castle" });
    await user.click(within(dialog).getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(posted.find((p) => p.op === "plan:pl1")!.body).toMatchObject({ ok: true }));
    await waitFor(() => expect(notice).toHaveBeenCalledWith("1 setting saved."));
  });

  test("Attach asks for a file, then ties it to the mod", async () => {
    const user = userEvent.setup();
    vi.mocked(native.pickFile).mockResolvedValue("C:/m/extra.ini");
    const { ops } = mount({ nodes: [NATIVE] });
    await user.click(await screen.findByRole("button", { name: "Attach a file..." }));
    await waitFor(() => expect(ops("mod_configs.attach")).toHaveLength(1));
    expect(ops("mod_configs.attach")[0]!.body).toEqual({ target: "C:/m/Mod.dll", file: "C:/m/extra.ini" });
  });

  test("a file changed on disk shows the Reload bar", async () => {
    const user = userEvent.setup();
    const { ops } = mount({ nodes: [NATIVE], ops: { "mod_configs.stamp": () => ({ stamp: [9, 9] }) } });
    expect(await screen.findByTestId("diskChangedBar")).toHaveTextContent("changed outside");
    const opened = ops("mod_configs.open").length;
    await user.click(screen.getByRole("button", { name: "Reload" }));
    await waitFor(() => expect(ops("mod_configs.open").length).toBeGreaterThan(opened));
  });

  test("a file that cannot be read says why", async () => {
    mount({
      nodes: [NATIVE],
      ops: { "mod_configs.open": () => HttpResponse.json({ code: "unreadable", message: "Too big.", details: {} }, { status: 422 }) },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Can't open mod.toml");
    expect(screen.getByRole("alert")).toHaveTextContent("Too big.");
  });
});

// ---- the Overhaul setup
const OVERHAUL_NODE = {
  key: "overhaul",
  name: "Big Overhaul",
  kind: "overhaul",
  target: null,
  setup: { path: "C:/o/big.toml", sha: "osha", verified: false, level: "basic", folder: "C:/o", config: { id: "big", label: "Big Overhaul", short_label: "Big" } },
  files: [{ path: "C:/o/big.toml", how: "overhaul", exists: true, kind: "overhaul" }],
};
const ovView = (placed: boolean) => ({
  label: "Big Overhaul",
  status: "your config, not verified",
  loadsLast: "Loads after all the other mods.",
  note: "",
  sections: [
    {
      title: "Big.dll",
      rows: [row("early:Big.dll", "false", { section: "Big.dll", kind: "bool", onValue: "true", offValue: "false", label: "Start early" })],
    },
    {
      title: "Files",
      rows: [
        row("file:a.bin", placed ? "place" : "merge", { section: "file", kind: "choice", label: "a.bin", choices: [{ value: "merge", label: "Merge" }, { value: "place", label: "Place it" }] }),
        ...(placed ? [row("target:a.bin", "", { section: "file", label: "Game path" })] : []),
      ],
    },
  ],
  steps: [],
  stepsTitle: "What it does",
  isNew: false,
  editable: true,
});
const OV_FORM = {
  setup: OVERHAUL_NODE.setup,
  choices: { natives: [], files: [], texts: [] },
  values: { natives: [{ file: "Big.dll", load_early: false, after_others: false, initializer: null }], files: { "a.bin": "merge" }, tables: {}, health: { log: "", fail: "", ok: "" } },
  new: false,
  view: ovView(false),
};
const OV_READ = { ...READ_BASE, path: "C:/o/big.toml", text: 'id = "big"\n', has_form: false, sections: [], sha: "osha" };

describe("Overhaul setup", () => {
  const ovNode = { ...OVERHAUL_NODE };
  const base = (extra: Record<string, (b: Json) => Response | Json> = {}) => ({
    nodes: [ovNode, NATIVE],
    reads: { "C:/o/big.toml": OV_READ },
    ops: { "mod_configs.overhaul_form": () => OV_FORM, "mod_configs.overhaul_view": () => ({ view: ovView(true) }), ...extra },
  });
  test("shows the setup's rows; choosing to place a file shows its game path; Save saves the setup and applies it to the profiles", async () => {
    const user = userEvent.setup();
    const { ops } = mount(base({ "mod_configs.save_setup": () => ({ name: "big.toml", overhaul_id: "big", said: "big.toml saved." }), "mod_configs.apply_setup": () => ({ job_id: "j1" }) }));
    expect(await screen.findByText("Big Overhaul · your config, not verified")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("a.bin"), "place");
    expect(await screen.findByLabelText("Game path")).toBeInTheDocument();
    expect(ops("mod_configs.overhaul_view")[0]!.body).toMatchObject({ profile: "C:/p/My.me3", values: { files: { "a.bin": "place:" } } });
    await user.type(screen.getByLabelText("Game path"), "mod/a.bin");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(ops("mod_configs.save_setup")).toHaveLength(1));
    expect(ops("mod_configs.save_setup")[0]!.body).toMatchObject({ profile: "C:/p/My.me3", path: "C:/o/big.toml", expect: "osha", form: { files: { "a.bin": "place:mod/a.bin" }, health: null } });
    await waitFor(() => expect(ops("mod_configs.apply_setup")).toHaveLength(1));
    expect(ops("mod_configs.apply_setup")[0]!.body).toEqual({ profile: "C:/p/My.me3", overhaul_id: "big" });
    expect(notice).toHaveBeenCalledWith("big.toml saved.");
  });

  test("Edit as text saves the setup's TOML", async () => {
    const user = userEvent.setup();
    const { ops } = mount(base({ "mod_configs.save_setup": () => ({ name: "big.toml", overhaul_id: "big", said: "saved" }), "mod_configs.apply_setup": () => ({ job_id: "j1" }) }));
    await user.click(await screen.findByRole("switch", { name: "Edit as text" }));
    await user.type(await screen.findByRole("textbox", { name: "Overhaul setup: Big Overhaul" }), "#");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(ops("mod_configs.save_setup")).toHaveLength(1));
    expect(ops("mod_configs.save_setup")[0]!.body).toEqual({ profile: "C:/p/My.me3", path: "C:/o/big.toml", expect: "osha", text: 'id = "big"\n#' });
  });

  test("turning the setup off is a plan: the dialog lists what happens and Apply answers it", async () => {
    const user = userEvent.setup();
    const { posted } = mount(
      base({ "mod_configs.turn_off": () => ({ plan_id: "t1", prompt: { kind: "confirm", title: "Turn off the overhaul setup of Big", changes: ["Remove Big.dll"], apply: "Turn off", safety: "Undo in Activity puts it all back." } }) }),
    );
    await user.click(await screen.findByRole("button", { name: "More" }));
    await user.click(await screen.findByRole("menuitem", { name: "Turn off overhaul setup..." }));
    const dialog = await screen.findByRole("alertdialog", { name: "Turn off the overhaul setup of Big" });
    expect(within(dialog).getByText("Remove Big.dll")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Turn off" }));
    await waitFor(() => expect(posted.find((p) => p.op === "plan:t1")!.body).toMatchObject({ ok: true }));
  });

  test("a refusal from the backend is only told", async () => {
    const user = userEvent.setup();
    mount(base({ "mod_configs.turn_off": () => ({ plan_id: null, prompt: { kind: "refusal", title: "Can't turn it off", body: "A job is running." } }) }));
    await user.click(await screen.findByRole("button", { name: "More" }));
    await user.click(await screen.findByRole("menuitem", { name: "Turn off overhaul setup..." }));
    expect(await screen.findByRole("alertdialog", { name: "Can't turn it off" })).toHaveTextContent("A job is running.");
  });

  test("setting a mod up as an overhaul shows the proposal; Save offers the install plan and its answer starts the job", async () => {
    const user = userEvent.setup();
    const proposal = { ...OV_FORM, new: true, setup: { ...OVERHAUL_NODE.setup, path: null, sha: null, config: { id: "mod", label: "Mod", short_label: "Mod" } }, view: { ...ovView(false), label: "Mod", isNew: true, note: "Check the settings, then Save." } };
    const { ops, posted } = mount({
      nodes: [NATIVE],
      ops: {
        "mod_configs.setup_candidates": () => ({ mods: [{ name: "Mod", id: "", folder: "C:/m" }] }),
        "mod_configs.overhaul_form": () => proposal,
        "mod_configs.install_setup": () => ({ plan_id: "i1", prompt: { kind: "confirm", title: "Set up Mod as an overhaul", changes: ["Copy files"], apply: "Set up" } }),
      },
    });
    await user.click(await screen.findByRole("button", { name: "More" }));
    await user.click(await screen.findByRole("menuitem", { name: "Set up as an overhaul..." }));
    expect(await screen.findByTestId("overhaulNote")).toHaveTextContent("Check the settings");
    expect(ops("mod_configs.overhaul_form")[0]!.body).toEqual({ profile: "C:/p/My.me3", folder: "C:/m", name: "Mod", overhaul_id: "" });
    await user.click(screen.getByRole("button", { name: "Save" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Set up Mod as an overhaul" });
    expect(ops("mod_configs.install_setup")[0]!.body).toMatchObject({ profile: "C:/p/My.me3", folder: "C:/m", name: "Mod" });
    await user.click(within(dialog).getByRole("button", { name: "Set up" }));
    await waitFor(() => expect(posted.find((p) => p.op === "plan:i1")!.body).toMatchObject({ ok: true }));
  });

  test("with several mods to choose from, a tick list asks which one", async () => {
    const user = userEvent.setup();
    const { ops } = mount({
      nodes: [],
      ops: {
        "mod_configs.setup_candidates": () => ({ mods: [{ name: "One", id: "", folder: "C:/one" }, { name: "Two", id: "2", folder: "C:/two" }] }),
        "mod_configs.overhaul_form": () => ({ ...OV_FORM, new: true, setup: { ...OVERHAUL_NODE.setup, path: null, sha: null } }),
      },
    });
    await user.click(await screen.findByRole("button", { name: "Set up a mod as an overhaul..." }));
    const dialog = await screen.findByRole("alertdialog", { name: "Set up which mod as an overhaul?" });
    await user.click(within(dialog).getByLabelText("Two"));
    await user.click(within(dialog).getByRole("button", { name: "Next" }));
    await waitFor(() => expect(ops("mod_configs.overhaul_form")).toHaveLength(1));
    expect(ops("mod_configs.overhaul_form")[0]!.body).toEqual({ profile: "C:/p/My.me3", folder: "C:/two", name: "Two", overhaul_id: "2" });
  });
});
