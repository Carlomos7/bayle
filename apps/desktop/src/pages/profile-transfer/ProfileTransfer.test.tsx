import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeAll, beforeEach, describe, expect, test, vi } from "vitest";
import { BackendProvider } from "@/api/backend";
import { handleEvent } from "@/api/events";
import type { ApiEvent } from "@/api/types";
import { PromptHost, usePrompts } from "@/components/PromptHost";
import { sonnerToasts, type Toasts } from "@/components/toasts";
import { backend, BASE, server } from "@/test/server";
import { handOverBundled } from "./bundled";
import * as pickers from "@/lib/native";
import { ProfileTransfer } from "./ProfileTransferPage";

vi.mock("@/lib/native", () => ({ pickFolder: vi.fn(), pickFile: vi.fn(), openFolder: vi.fn(), openLink: vi.fn() }));

const GB = 1024 ** 3;
const PROFILE = "C:\\game\\profiles\\Mine.me3";

// jsdom has no layout: give the virtual list a viewport
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, value: 320 });
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 600 });
});

let qc: QueryClient;
const finished: Record<string, boolean> = {}; // which mocked jobs the backend reports as done
let seq = 0;
const toasts = { progress: vi.fn(), done: vi.fn(), failed: vi.fn(), cancelled: vi.fn(), notice: vi.fn(), error: vi.fn() } as unknown as Toasts;
const emit = (type: string, job_id: string, data: unknown) =>
  act(() =>
    handleEvent({ type, job_id, seq: ++seq, data } as unknown as ApiEvent, {
      queryClient: qc,
      toasts,
      ask: () => undefined,
      navigate: () => undefined,
    }),
  );

function Asker() {
  usePrompts();
  return null;
}

function mount(props: Partial<Parameters<typeof ProfileTransfer>[0]> = {}) {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onLeave = vi.fn();
  const view = render(
    <QueryClientProvider client={qc}>
      <BackendProvider backend={backend}>
        <PromptHost toasts={toasts}>
          <Asker />
          <ProfileTransfer profilePath={PROFILE} profileName="Mine" busy={false} gameRunning={false} onLeave={onLeave} {...props} />
        </PromptHost>
      </BackendProvider>
    </QueryClientProvider>,
  );
  return { ...view, onLeave };
}

/** Record every POST body by path. */
function record(handlers: Record<string, unknown> = {}) {
  const posted: { path: string; body: unknown }[] = [];
  server.use(
    http.post(`${BASE}/v1/*`, async ({ request }) => {
      const path = new URL(request.url).pathname;
      posted.push({ path, body: await request.json().catch(() => null) });
      const answer = handlers[path];
      return answer instanceof Response ? answer : HttpResponse.json(answer ?? {});
    }),
  );
  return posted;
}

const listing = (mods: { key: string; name: string; enabled?: boolean; size: number }[], save_name = "") =>
  server.use(
    http.get(`${BASE}/v1/pages/profile_transfer`, () =>
      HttpResponse.json({ mods: mods.map((m) => ({ enabled: true, ...m })), save_name }),
    ),
  );

beforeEach(() => {
  seq = 0;
  vi.mocked(pickers.pickFolder).mockReset();
  vi.mocked(pickers.pickFile).mockReset();
});

describe("export", () => {
  test("no profile says so; a failing listing shows the backend's words", async () => {
    mount({ profilePath: "" });
    expect(screen.getByText("Pick a profile first.")).toBeInTheDocument();
  });

  test("a listing error is shown", async () => {
    server.use(
      http.get(`${BASE}/v1/pages/profile_transfer`, () =>
        HttpResponse.json({ code: "boom", message: "Could not read the profile.", details: {} }, { status: 500 }),
      ),
    );
    mount();
    expect(await screen.findByText("Could not read the profile.")).toBeInTheDocument();
  });

  test("a share list needs a folder, then posts the export job and follows its progress to the result", async () => {
    listing([{ key: "a", name: "Alpha", size: 5 * 1024 ** 2 }]);
    const posted = record({ "/v1/ops/profile_transfer.export": { job_id: "j1" } });
    server.use(
      http.get(`${BASE}/v1/jobs/j1`, () =>
        HttpResponse.json({ id: "j1", title: "Exporting a profile...", state: "done", result: { path: "C:\\out\\Mine.json", size: 2048 } }),
      ),
    );
    vi.mocked(pickers.pickFolder).mockResolvedValue("C:\\out");
    const user = userEvent.setup();
    mount();

    const exportBtn = await screen.findByRole("button", { name: "Export" });
    expect(exportBtn).toBeDisabled();
    expect(screen.getByText("Choose an output folder.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Choose output folder..." }));
    expect(await screen.findByText("C:\\out")).toBeInTheDocument();
    await user.click(exportBtn);

    await vi.waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toMatchObject({
      path: "/v1/ops/profile_transfer.export",
      body: { profile: PROFILE, kind: "list", name: "Mine", folder: "C:\\out", with_configs: true, with_save: false, password: false },
    });

    await emit("started", "j1", { title: "Exporting a profile..." });
    await emit("progress", "j1", { done: 50, total: 100, label: "mods/Alpha/a.dll", detail: { n: 2, count: 4 } });
    expect(await screen.findByText(/50%\s+·\s+file 2 of 4/)).toBeInTheDocument();
    expect(screen.getByLabelText("Exporting...")).toHaveAttribute("value", "50");
    expect(screen.getByText("a.dll")).toBeInTheDocument();

    finished.j1 = true;
    await emit("finished", "j1", { result: {} });
    expect(await screen.findByText(/Done: Mine\.json \(2 KB, took/)).toBeInTheDocument();
    expect(screen.getByText("C:\\out\\Mine.json")).toBeInTheDocument();
  });

  test("Cancel export posts the job cancel and a cancelled job says nothing was written", async () => {
    listing([{ key: "a", name: "Alpha", size: 10 }]);
    const posted = record({ "/v1/ops/profile_transfer.export": { job_id: "j2" } });
    server.use(http.get(`${BASE}/v1/jobs/j2`, () => HttpResponse.json({ id: "j2", title: "Exporting a profile...", state: "running" })));
    vi.mocked(pickers.pickFolder).mockResolvedValue("D:\\x");
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: "Choose output folder..." }));
    await user.click(await screen.findByRole("button", { name: "Export" }));
    await user.click(await screen.findByRole("button", { name: "Cancel export" }));
    await vi.waitFor(() => expect(posted.at(-1)?.path).toBe("/v1/jobs/j2/cancel"));
    expect(await screen.findByRole("button", { name: "Cancelling..." })).toBeDisabled();
    await emit("cancelled", "j2", { error: null });
    expect(await screen.findByText("Export cancelled. Nothing was written.")).toBeInTheDocument();
  });

  test("a big full export warns, asks once through the plan dialog and then follows the job it started", async () => {
    listing(
      [
        { key: "a", name: "Huge", size: 2 * GB },
        { key: "b", name: "Small", size: 1024 ** 2 },
      ],
      "ER0000.sl2",
    );
    const posted = record({
      "/v1/ops/profile_transfer.confirm_export": {
        plan_id: "p1",
        prompt: { kind: "confirm", title: "Export a big file?", changes: ["The zip will be about 2.0 GB. This may take around 14 s."], apply: "Export" },
      },
      "/v1/plans/p1": { job_id: "j3" },
    });
    server.use(http.get(`${BASE}/v1/jobs/j3`, () => HttpResponse.json({ id: "j3", title: "Exporting a profile...", state: "running" })));
    vi.mocked(pickers.pickFolder).mockResolvedValue("D:\\big");
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByRole("radio", { name: /Full export/ }));
    expect(await screen.findByText(/The biggest: Huge \(2\.0 GB\), Small \(1\.0 MB\)/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Huge" })).toBeChecked();
    expect(screen.getByText("2 mods · 2.0 GB")).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: /My save file/ }));
    await user.click(screen.getByRole("button", { name: "Choose output folder..." }));
    await user.click(await screen.findByText("D:\\big"));
    await user.click(screen.getByRole("button", { name: "Export" }));

    const dialog = await screen.findByRole("alertdialog", { name: "Export a big file?" });
    expect(posted[0]).toMatchObject({
      path: "/v1/ops/profile_transfer.confirm_export",
      body: { kind: "full", size: 2 * GB + 1024 ** 2, with_save: true, chosen: ["a", "b"] },
    });
    await user.click(within(dialog).getByRole("button", { name: "Export" }));
    await vi.waitFor(() => expect(posted.at(-1)?.path).toBe("/v1/plans/p1"));
    await emit("progress", "j3", { done: 1, total: 4, label: "x/y.pak", detail: { n: 1, count: 2 } });
    expect(await screen.findByText(/25%\s+·\s+file 1 of 2/)).toBeInTheDocument();
  });

  test("another running job turns Export off and says why", async () => {
    listing([]);
    mount({ busy: true });
    expect(await screen.findByText("Another job is running. Wait for it to finish.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export" })).toBeDisabled();
  });
});

const card = (key: string, title: string) => ({ key, title, path: `C:\\g\\${key}`, lines: [`${title} changes`], leftOut: [], isNew: key === "n" });

test("the menu's Import profile opens the Import tab", async () => {
  listing([]);
  mount({ tab: "import" });
  expect(await screen.findByRole("radio", { name: "Import", checked: true })).toBeInTheDocument();
});

describe("import", () => {
  async function openImport() {
    const user = userEvent.setup();
    listing([]);
    mount();
    await user.click(screen.getByRole("radio", { name: "Import" }));
    return user;
  }

  test("opens a file, previews with the choices, imports the ticked cards and follows the job", async () => {
    const notice = vi.spyOn(sonnerToasts, "notice").mockImplementation(() => undefined);
    vi.mocked(pickers.pickFile).mockResolvedValue("C:\\in\\Pack.zip");
    const prev = (choice: string) => ({
      cards: [card("p", "Profile"), card("n", "New thing")],
      clashes: [{ key: "Foo", name: "Foo", diff: "1 file changed (1 KB)", incoming: "Version 2", mine: "Version 1 · installed today", choice, suggested: true, canBoth: false }],
      notes: ["Good to know this"],
      skipped: [],
      refusals: [],
      undecided: choice === "",
      ok: true,
    });
    let calls = 0;
    const posted = record({
      "/v1/ops/profile_transfer.open_file": { resource: "t1", file: "Pack · version 2  (full export)", is_zip: true, readme: "# Hello", new_profile: true, new_name: "Pack" },
      "/v1/ops/profile_transfer.import": { job_id: "j4" },
    });
    server.use(
      http.post(`${BASE}/v1/ops/profile_transfer.preview`, async ({ request }) => {
        posted.push({ path: "/v1/ops/profile_transfer.preview", body: await request.json() });
        return HttpResponse.json(prev(calls++ === 0 ? "" : "mine"));
      }),
      http.get(`${BASE}/v1/jobs/j4`, () =>
        HttpResponse.json(
          finished.j4
            ? { id: "j4", title: "Importing a profile...", state: "done", result: { name: "Pack.me3" } }
            : { id: "j4", title: "Importing a profile...", state: "running" },
        ),
      ),
    );
    const user = await openImport();

    await user.click(screen.getByRole("button", { name: "Open file..." }));
    expect(await screen.findByText(/Pack · version 2\s+\(full export\)/)).toBeInTheDocument();
    expect(screen.getByText("# Hello")).toBeInTheDocument();
    expect(await screen.findByText("Pick one to continue.")).toBeInTheDocument();
    expect(screen.getByText("Good to know this")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import" })).toBeDisabled(); // a clash still waits for a pick

    await user.click(screen.getByRole("radio", { name: "Keep mine" }));
    await vi.waitFor(() => expect(screen.getByRole("button", { name: "Import" })).toBeEnabled());
    expect(posted.filter((p) => p.path.endsWith("preview")).at(-1)?.body).toMatchObject({
      resource: "t1",
      profile: PROFILE,
      new_profile: true,
      new_name: "Pack",
      choices: { foo: "mine" },
    });

    await user.click(screen.getByRole("checkbox", { name: /New thing/ })); // untick one card
    await user.click(screen.getByRole("button", { name: "Import" }));
    await vi.waitFor(() => expect(posted.at(-1)?.path).toBe("/v1/ops/profile_transfer.import"));
    expect(posted.at(-1)?.body).toEqual({ resource: "t1", skip: ["n"] });

    await emit("progress", "j4", { done: 10, total: 20, label: "" });
    await vi.waitFor(() => expect(screen.getByLabelText("Importing...")).toHaveAttribute("value", "50"));
    finished.j4 = true;
    await emit("finished", "j4", { result: {} });
    await vi.waitFor(() => expect(notice).toHaveBeenCalledWith("Imported into Pack.me3. Undo it from Activity."));
    expect(screen.queryByText(/Pack · version 2\s+\(full export\)/)).toBeNull();
  });

  test("a refused file shows the refusal and cannot be imported; an unreadable one shows why", async () => {
    vi.mocked(pickers.pickFile).mockResolvedValueOnce("C:\\in\\bad.zip").mockResolvedValueOnce("C:\\in\\worse.json");
    server.use(
      http.post(`${BASE}/v1/ops/profile_transfer.open_file`, async ({ request }) => {
        const { path } = (await request.json()) as { path: string };
        return path.endsWith("worse.json")
          ? HttpResponse.json({ code: "unreadable", message: "Not a profile.", details: {} }, { status: 422 })
          : HttpResponse.json({ resource: "t2", file: "bad (share list)", is_zip: false });
      }),
      http.post(`${BASE}/v1/ops/profile_transfer.preview`, () =>
        HttpResponse.json({ cards: [card("p", "Profile")], refusals: ["Needs a newer launcher."], ok: false }),
      ),
      http.post(`${BASE}/v1/ops/profile_transfer.discard`, () => HttpResponse.json({ found: true })),
    );
    const user = await openImport();
    await user.click(screen.getByRole("button", { name: "Open file..." }));
    expect(await screen.findByText("Needs a newer launcher.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Open file..." }));
    expect(await screen.findByText("Can't use that file. Not a profile.")).toBeInTheDocument();
  });

  test("switching to Export lets go of the open file", async () => {
    vi.mocked(pickers.pickFile).mockResolvedValue("C:\\in\\a.json");
    const posted = record({
      "/v1/ops/profile_transfer.open_file": { resource: "t3", file: "a (share list)" },
      "/v1/ops/profile_transfer.preview": { cards: [card("p", "Profile")], ok: true },
    });
    const user = await openImport();
    await user.click(screen.getByRole("button", { name: "Open file..." }));
    await screen.findByText("a (share list)");
    await user.click(screen.getByRole("radio", { name: "Export" }));
    await vi.waitFor(() => expect(posted.at(-1)).toMatchObject({ path: "/v1/ops/profile_transfer.discard", body: { resource: "t3" } }));
  });
});

describe("a download's bundled profile", () => {
  test("the shell's hand-over opens it, previews the picked profile and Cancel discards and leaves", async () => {
    handOverBundled({ unpacked: "C:\\tmp\\dl", profiles: ["C:\\tmp\\dl\\One.me3", "C:\\tmp\\dl\\Two.me3"], staging: "C:\\tmp\\st" });
    const posted = record({
      "/v1/ops/profile_transfer.open_bundled": { resource: "t9", names: ["C:\\tmp\\dl\\One.me3", "C:\\tmp\\dl\\Two.me3"], new_name: "One" },
      "/v1/ops/profile_transfer.preview": { lines: ["Copies 3 mods"], refusals: [], clashes: [], ok: true },
    });
    const user = userEvent.setup();
    const { onLeave } = mount();

    expect(await screen.findByRole("heading", { name: "This download has a profile" })).toBeInTheDocument();
    expect(await screen.findByText("Copies 3 mods")).toBeInTheDocument();
    expect(posted[0]).toMatchObject({
      path: "/v1/ops/profile_transfer.open_bundled",
      body: { unpacked: "C:\\tmp\\dl", staging: "C:\\tmp\\st" },
    });
    await user.selectOptions(screen.getByLabelText("Which profile to import"), "1");
    await vi.waitFor(() => expect(posted.at(-1)?.body).toMatchObject({ resource: "t9", which: 1, new_name: "Two" }));
    expect(screen.getByRole("button", { name: "Import" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await vi.waitFor(() => expect(posted.some((p) => p.path.endsWith("discard"))).toBe(true));
    expect(onLeave).toHaveBeenCalled();
  });
});
