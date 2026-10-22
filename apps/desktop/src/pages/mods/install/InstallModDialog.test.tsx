import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { createRef } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { BackendProvider } from "@/api/backend";
import { jobKey } from "@/api/events";
import type { Toasts } from "@/components/toasts";
import { backend, BASE, server } from "@/test/server";
import { InstallModDialog, type InstallModHandle } from "./InstallModDialog";
import type { InstallView } from "./types";

const picked = vi.hoisted(() => ({ value: null as string | null }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn(() => Promise.resolve(picked.value)) }));
vi.mock("@tauri-apps/api/webview", () => ({ getCurrentWebview: () => ({ onDragDropEvent: () => Promise.reject(new Error("no tauri")) }) }));

const words = {
  working: "Working...",
  install: "Install",
  cancel: "Cancel",
  whatToInstall: "What to install",
  itemsNote: "Unticked files are left out.",
  dllEarly: "Start before the game sets itself up",
  dllAfter: "Load after the other DLLs",
  dllInit: "Run a function when it loads",
  overhaulOption: "Set up as an overhaul",
  id: "Id",
  regulation: "regulation.bin",
  importInstead: "Import its profile instead...",
};

function view(over: Partial<InstallView> = {}): InstallView {
  return {
    title: "Install Grass",
    what: "Package  ·  parts  ·  1 KB",
    variants: [],
    variant: "",
    name: "Grass",
    id: "Grass",
    nameLabel: "Folder name",
    where: "Goes into this profile's folder: p/Grass",
    idShown: true,
    idNote: "What other entries use to load before or after it.",
    idError: false,
    nameError: false,
    items: [{ name: "parts", what: "its files", size: "1 KB", on: true, tip: "" }],
    regulation: { shown: false },
    last: { shown: false },
    note: "Options changes its load order.",
    noteLevel: "muted",
    option: { shown: false },
    library: { shown: false },
    overhaul: { shown: false },
    natives: [],
    files: [],
    texts: [],
    mode: "",
    profilesInside: false,
    canInstall: true,
    busy: false,
    installText: "Install",
    error: "",
    words,
    ...over,
  };
}

const overhaul = (extra: Partial<InstallView> = {}) =>
  view({
    mode: "setup",
    installText: "Install as overhaul",
    option: { shown: true, ticked: true, text: "Ticked because it looks like one." },
    overhaul: { shown: true, ready: true, lines: ["Sets up Grass"], notes: [], refusals: [] },
    natives: [{ file: "mod.dll", load_early: false, after_others: false, initializer: null }],
    files: [
      {
        file: "mod/a.bin",
        action: "place",
        target: "map/a.bin",
        choices: [
          { value: "copy", label: "Copy" },
          { value: "place:map/a.bin", label: "Place at a game path" },
        ],
      },
    ],
    texts: [{ file: "msg/engus/menu.msgbnd.dcx", label: "Texts added to menu", table: "", choices: [{ value: "", label: "(choose a table)" }, { value: "Menu", label: "Menu" }], chosen: "(choose a table)" }],
    ...extra,
  });

const toasts = { notice: vi.fn(), error: vi.fn() } as unknown as Toasts;
let calls: { name: string; body: Record<string, unknown> }[];
let qc: QueryClient;

/** The backend: every /v1/ops/<name> call is recorded; `answers` gives the reply per op (a function sees the body). */
function backendFor(answers: Record<string, (body: Record<string, unknown>) => Response | object>) {
  server.use(
    http.post(`${BASE}/v1/ops/:name`, async ({ request, params }) => {
      const name = String(params.name);
      const body = (await request.json()) as Record<string, unknown>;
      calls.push({ name, body });
      const out = answers[name]?.(body);
      if (out instanceof Response) return out;
      return HttpResponse.json(out ?? {});
    }),
  );
}
const reply = (v: InstallView, pending = false) => ({ draft_id: "d1", view: v, pending });
const refusal = (code: string, message: string) => HttpResponse.json({ code, message, details: {} }, { status: 400 });
const sources = (body: Record<string, unknown>) => ({ usable: body.paths, skipped: [] });
const names = () => calls.map((c) => c.name);

function mount(profile = "C:/p/prof.me3") {
  const ref = createRef<InstallModHandle>();
  render(
    <QueryClientProvider client={qc}>
      <BackendProvider backend={backend}>
        <InstallModDialog ref={ref} profile={profile} toasts={toasts} />
      </BackendProvider>
    </QueryClientProvider>,
  );
  return ref;
}

beforeEach(() => {
  calls = [];
  picked.value = null;
  vi.mocked(toasts.notice).mockClear();
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

describe("InstallModDialog", () => {
  test("a path is checked, opened as a draft and shown with the backend's words", async () => {
    backendFor({ "mods.install_sources": sources, "mods.install_open": () => reply(view()) });
    const ref = mount();
    act(() => ref.current!.openInstall("C:/dl/grass.zip"));
    expect(await screen.findByRole("heading", { name: "Install Grass" })).toBeInTheDocument();
    expect(calls[1]).toEqual({ name: "mods.install_open", body: { profile: "C:/p/prof.me3", source: "C:/dl/grass.zip" } });
    expect(screen.getByLabelText("Folder name")).toHaveValue("Grass");
    expect(screen.getByText("What to install")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Install" })).toBeEnabled();
  });

  test("without a path the Tauri picker is used; cancelling it does nothing", async () => {
    backendFor({ "mods.install_sources": sources, "mods.install_open": () => reply(view()) });
    const ref = mount();
    act(() => ref.current!.openInstall());
    await new Promise((r) => setTimeout(r, 20));
    expect(calls).toEqual([]);
    picked.value = "C:/dl/folder";
    act(() => ref.current!.openInstall(undefined, { folder: true }));
    await screen.findByRole("heading", { name: "Install Grass" });
    expect(calls[0]?.body).toEqual({ paths: ["C:/dl/folder"] });
  });

  test("what is not installable is skipped with a toast, and an open that is refused says why", async () => {
    backendFor({
      "mods.install_sources": () => ({ usable: ["C:/dl/a.zip"], skipped: ["C:/dl/notes.txt"] }),
      "mods.install_open": () => refusal("not_installable", "nothing to install"),
    });
    const ref = mount();
    act(() => ref.current!.openInstall("C:/dl/a.zip"));
    await waitFor(() => expect(toasts.notice).toHaveBeenCalledWith("a.zip is not a mod Bayle can install: nothing to install", { error: true }));
    expect(toasts.notice).toHaveBeenCalledWith("Skipped notes.txt: not an archive (.zip, .7z, .rar), a .dll or a folder.");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  test("no profile: nothing is asked of the backend", async () => {
    backendFor({});
    const ref = mount("");
    act(() => ref.current!.openInstall("C:/dl/a.zip"));
    expect(toasts.notice).toHaveBeenCalledWith("Pick a profile first.", { error: true });
    expect(calls).toEqual([]);
  });

  test("typing the name edits at once, then replans and previews after the pause", async () => {
    const user = userEvent.setup();
    backendFor({
      "mods.install_sources": sources,
      "mods.install_open": () => reply(view()),
      "mods.install_edit": (b) => reply(view({ name: String(b.text) }), true),
      "mods.install_replan": () => reply(view()),
      "mods.install_preview": () => reply(view({ title: "Install Moss" })),
    });
    const ref = mount();
    act(() => ref.current!.openInstall("C:/dl/g.zip"));
    const name = await screen.findByLabelText("Folder name");
    await user.type(name, "X");
    expect(name).toHaveValue("GrassX"); // not overwritten by the view while it has focus
    expect(calls.filter((c) => c.name === "mods.install_edit").at(-1)?.body).toMatchObject({ draft_id: "d1", field: "name", text: "GrassX" });
    await screen.findByRole("heading", { name: "Install Moss" });
    expect(names().slice(-2)).toEqual(["mods.install_replan", "mods.install_preview"]);
  });

  test("an edit while the preview runs asks once more, and the edits keep their order", async () => {
    const user = userEvent.setup();
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => (release = r));
    let previews = 0;
    backendFor({
      "mods.install_sources": sources,
      "mods.install_open": () => reply(view()),
      "mods.install_edit": (b) => reply(view({ name: String(b.text) }), true),
      "mods.install_replan": () => reply(view()),
    });
    server.use(
      http.post(`${BASE}/v1/ops/mods.install_preview`, async () => {
        calls.push({ name: "mods.install_preview", body: {} });
        if (++previews === 1) await gate;
        return HttpResponse.json(reply(view({ title: `Install ${previews}` })));
      }),
    );
    const ref = mount();
    act(() => ref.current!.openInstall("C:/dl/g.zip"));
    const name = await screen.findByLabelText("Folder name");
    await user.type(name, "1");
    await waitFor(() => expect(previews).toBe(1)); // the first preview is running
    await user.type(name, "2"); // an edit meanwhile
    await waitFor(() => expect(names().filter((n) => n === "mods.install_edit")).toHaveLength(2));
    await new Promise((r) => setTimeout(r, 300));
    release();
    await screen.findByRole("heading", { name: "Install 2" });
    expect(previews).toBe(2);
    expect(calls.filter((c) => c.name === "mods.install_edit").map((c) => c.body.text)).toEqual(["Grass1", "Grass12"]);
  });

  test("the overhaul review: DLL options, the Files table, the place path and the choose-a-table refusal", async () => {
    const user = userEvent.setup();
    const refused = overhaul({
      canInstall: false,
      overhaul: { shown: true, ready: true, lines: [], notes: [], refusals: ["Choose the table for the texts added to menu before installing."] },
    });
    backendFor({
      "mods.install_sources": sources,
      "mods.install_open": () => reply(refused),
      "mods.install_edit": () => reply(refused),
    });
    const ref = mount();
    act(() => ref.current!.openInstall("C:/dl/g.zip"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose the table for the texts added to menu before installing.");
    expect(screen.getByRole("button", { name: "Install as overhaul" })).toBeDisabled();
    const edits = () => calls.filter((c) => c.name === "mods.install_edit").map((c) => c.body);

    await user.click(screen.getByRole("checkbox", { name: "Start before the game sets itself up" }));
    expect(edits().at(-1)).toMatchObject({ field: "native", key: "mod.dll", kind: "early", text: "true" });
    await user.click(screen.getByRole("checkbox", { name: "Load after the other DLLs" }));
    expect(edits().at(-1)).toMatchObject({ kind: "after", text: "true" });
    await user.type(screen.getByLabelText("mod.dll: Run a function when it loads"), "Init{Enter}");
    expect(edits().at(-1)).toMatchObject({ kind: "init", text: "Init" });

    await user.selectOptions(screen.getByLabelText("Texts added to menu"), "Menu");
    expect(edits().at(-1)).toMatchObject({ field: "table", key: "msg/engus/menu.msgbnd.dcx", text: "Menu" });

    await user.selectOptions(screen.getByLabelText("mod/a.bin"), "copy");
    expect(edits().at(-1)).toMatchObject({ field: "file", key: "mod/a.bin", text: "copy" });
    const target = screen.getByLabelText("mod/a.bin: game path"); // the place field is its own line
    await user.clear(target);
    await user.type(target, "map/b.bin");
    await user.tab();
    expect(edits().at(-1)).toMatchObject({ field: "file", key: "mod/a.bin", text: "place:map/b.bin" });
  });

  test("Install starts the job and closes; the next source opens once the job is over", async () => {
    const user = userEvent.setup();
    let opened = 0;
    backendFor({
      "mods.install_sources": () => ({ usable: ["C:/dl/a.zip", "C:/dl/b.zip"], skipped: [] }),
      "mods.install_open": () => reply(view({ title: `Install ${++opened}` })),
      "mods.install_finish": () => HttpResponse.json({ job_id: "j1" }, { status: 202 }),
    });
    const ref = mount();
    act(() => ref.current!.openInstall("C:/dl/a.zip"));
    await user.click(await screen.findByRole("button", { name: "Install" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(calls.find((c) => c.name === "mods.install_finish")?.body).toEqual({ draft_id: "d1", name: "Grass" });
    await new Promise((r) => setTimeout(r, 50));
    expect(opened).toBe(1); // the second waits for the job
    act(() => qc.setQueryData(jobKey("j1"), { id: "j1", title: "Installing Grass...", state: "running", progress: null, log: [], error: null }));
    act(() => qc.setQueryData(jobKey("j1"), { id: "j1", title: "Installing Grass...", state: "done", progress: null, log: [], error: null }));
    expect(await screen.findByRole("heading", { name: "Install 2" })).toBeInTheDocument();
  });

  test("Cancel drops the draft", async () => {
    const user = userEvent.setup();
    backendFor({ "mods.install_sources": sources, "mods.install_open": () => reply(view()), "mods.install_close": () => ({ draft_id: "d1" }) });
    const ref = mount();
    act(() => ref.current!.openInstall("C:/dl/g.zip"));
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(names()).toContain("mods.install_close"));
    expect(calls.at(-1)?.body).toEqual({ draft_id: "d1" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
