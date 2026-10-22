import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeAll, beforeEach, describe, expect, test, vi } from "vitest";
import { BackendProvider } from "@/api/backend";
import { handleEvent } from "@/api/events";
import { PromptHost } from "@/components/PromptHost";
import { sonnerToasts, type Toasts } from "@/components/toasts";
import { openPath } from "@/lib/desktop";
import { backend, BASE, server } from "@/test/server";
import { ActivityPage } from "./ActivityPage";

vi.mock("@/lib/desktop", () => ({ openPath: vi.fn(() => Promise.resolve()) }));

// the virtual list needs a measurable scroller; jsdom has no layout
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, value: 900 });
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 900 });
});

const words = {
  showDetails: "Show details",
  showDetailsTip: "tip",
  copy: "Copy",
  copyTip: "tip",
  copySupport: "Copy for support",
  copySupportTip: "tip",
  openFile: "Open file",
  showLog: "Show this job's log",
  hideLog: "Hide this job's log",
  copied: "Copied",
  copiedSupport: "Copied with your user name and Steam IDs masked",
  fileGone: "That file is no longer there.",
  failedOnly: "Failed only",
  gameFilter: "Game",
  kindFilter: "Kind",
};

const job = (over: Record<string, unknown> = {}) => ({
  id: "j1",
  when: "14:02",
  title: "Install Foo",
  outcome: "Done",
  level: "success",
  meta: "12s, Elden Ring",
  line: "",
  failed: false,
  undo_label: "Undo",
  undo_tip: "Take this install back",
  sources: [
    { key: "j1.log", label: "Job log" },
    { key: "j1.me3.log", label: "me3 output" },
  ],
  ...over,
});

const state = (over: Record<string, unknown> = {}) => ({
  summary: [
    { label: "Last Play", value: "Never", level: "muted" },
    { label: "Last install", value: "Today", level: "success" },
    { label: "Last failure", value: "Yesterday", level: "danger" },
  ],
  days: [
    { label: "Today", jobs: [job(), job({ id: "j2", title: "Repair save", failed: true, level: "danger", outcome: "Failed", line: "A file was in use.", undo_label: "", sources: [{ key: "j2.log", label: "Job log" }] })] },
    { label: "Yesterday", jobs: [job({ id: "j3", title: "Play" , undo_label: "" })] },
  ],
  empty: "",
  unseen: 1,
  games: [
    { key: "", label: "All games" },
    { key: "eldenring", label: "Elden Ring" },
  ],
  kinds: [
    { key: "", label: "All kinds" },
    { key: "Mods", label: "Mods" },
  ],
  words,
  ...over,
});

interface Posted {
  path: string;
  body: unknown;
}

function setup(page: unknown = state(), toasts?: Toasts) {
  const posted: Posted[] = [];
  const pageUrls: string[] = [];
  server.use(
    http.get(`${BASE}/v1/pages/activity`, ({ request }) => {
      pageUrls.push(new URL(request.url).search);
      return HttpResponse.json(page as object);
    }),
    http.post(`${BASE}/v1/ops/:name`, async ({ request, params }) => {
      const body = await request.json();
      posted.push({ path: String(params.name), body });
      switch (params.name) {
        case "activity.mark_seen":
          return HttpResponse.json({ at: 1 });
        case "activity.log":
          return HttpResponse.json({ rows: [], plain: "line one\nline two", note: "Only the end is shown.", missing: false });
        case "activity.copy":
          return HttpResponse.json({ text: "copied text" });
        case "activity.log_file":
          return HttpResponse.json({ path: "C:/logs/jobs/j1.log" });
        case "activity.undo":
          return HttpResponse.json({
            plan_id: "p1",
            prompt: { kind: "confirm", title: "Take Install Foo back?", changes: ["Remove Foo"], apply: "Undo install" },
          });
      }
      return HttpResponse.json({});
    }),
    http.post(`${BASE}/v1/plans/:id`, async ({ request, params }) => {
      posted.push({ path: `plans/${String(params.id)}`, body: await request.json() });
      return HttpResponse.json({ job_id: "u1" }, { status: 202 });
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={qc}>
      <BackendProvider backend={backend}>
        <PromptHost toasts={toasts}>
          <div id="main">
            <ActivityPage />
          </div>
        </PromptHost>
      </BackendProvider>
    </QueryClientProvider>,
  );
  return { posted, pageUrls, qc, user };
}

const ops = (posted: Posted[], name: string) => posted.filter((p) => p.path === name);

let notice: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  notice = vi.spyOn(sonnerToasts, "notice").mockImplementation(() => {});
});
afterEach(() => vi.restoreAllMocks());

describe("Activity page", () => {
  test("lists the jobs by day with the backend's words, and marks Activity seen", async () => {
    const { posted, qc } = setup();
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    expect(await screen.findByRole("heading", { name: "Today" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Yesterday" })).toBeInTheDocument();
    expect(screen.getByText("Install Foo")).toBeInTheDocument();
    expect(screen.getByText("A file was in use.")).toBeInTheDocument();
    expect(screen.getByText("Last failure")).toBeInTheDocument();
    expect(screen.getByLabelText("Game")).toHaveValue("");
    expect(screen.getAllByRole("button", { name: /Undo/ })).toHaveLength(1);
    await vi.waitFor(() => expect(ops(posted, "activity.mark_seen")).toHaveLength(1));
    expect(qc.getQueryState(["page", "shell"])).toBeUndefined(); // nothing cached to refresh here
  });

  test("shows the backend's empty text", async () => {
    setup(state({ days: [], empty: "Nothing has happened yet." }));
    expect(await screen.findByText("Nothing has happened yet.")).toBeInTheDocument();
  });

  test("shows the error and tries again", async () => {
    setup();
    server.use(
      http.get(`${BASE}/v1/pages/activity`, () =>
        HttpResponse.json({ code: "no_game", message: "No game is set up.", details: {} }, { status: 409 }),
      ),
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("No game is set up.");
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  test("the filters go to the page as its query", async () => {
    const { pageUrls, user } = setup();
    await screen.findByText("Install Foo");
    await user.selectOptions(screen.getByLabelText("Game"), "eldenring");
    await user.selectOptions(screen.getByLabelText("Kind"), "Mods");
    await user.click(screen.getByRole("checkbox", { name: "Failed only" }));
    await vi.waitFor(() => expect(pageUrls.at(-1)).toBe("?game=eldenring&group=Mods&failed_only=true"));
  });

  test("opening a job reads its log; details and the attachment re-read it", async () => {
    const { posted, user } = setup();
    await user.click(await screen.findByRole("button", { name: /Install Foo/ }));
    const region = await screen.findByRole("region", { name: "Install Foo log" });
    expect(await within(region).findByLabelText("Log text")).toHaveTextContent("line one line two");
    expect(within(region).getByText("Only the end is shown.")).toBeInTheDocument();
    expect(ops(posted, "activity.log")[0]?.body).toEqual({ job_id: "j1", source: "", detail: false });

    await user.click(within(region).getByRole("checkbox", { name: "Show details" }));
    await vi.waitFor(() => expect(ops(posted, "activity.log").at(-1)?.body).toEqual({ job_id: "j1", source: "", detail: true }));

    await user.selectOptions(within(region).getByLabelText("Log source"), "j1.me3.log");
    await vi.waitFor(() => expect(ops(posted, "activity.log").at(-1)?.body).toEqual({ job_id: "j1", source: "j1.me3.log", detail: true }));
    expect(within(region).queryByRole("checkbox", { name: "Show details" })).toBeNull(); // details are the job log's only

    await user.click(screen.getByRole("button", { name: /Install Foo/ }));
    expect(screen.queryByRole("region", { name: "Install Foo log" })).toBeNull();
  });

  test("Copy and Copy for support put the text on the clipboard and say so", async () => {
    const { posted, user } = setup();
    const write = vi.spyOn(navigator.clipboard, "writeText"); // user-event installs its own clipboard in setup()
    await user.click(await screen.findByRole("button", { name: /Install Foo/ }));
    await user.click(await screen.findByRole("button", { name: "Copy for support" }));
    await vi.waitFor(() => expect(write).toHaveBeenCalledWith("copied text"));
    expect(ops(posted, "activity.copy")[0]?.body).toEqual({ job_id: "j1", source: "", detail: false, for_support: true });
    await vi.waitFor(() => expect(notice).toHaveBeenCalledWith(words.copiedSupport));

    await user.click(screen.getByRole("button", { name: "Copy" }));
    await vi.waitFor(() => expect(notice).toHaveBeenCalledWith(words.copied));
    expect(ops(posted, "activity.copy")[1]?.body).toMatchObject({ for_support: false });
  });

  test("Open file opens the log through the desktop, or says it is gone", async () => {
    const { user } = setup();
    await user.click(await screen.findByRole("button", { name: /Install Foo/ }));
    await user.click(await screen.findByRole("button", { name: "Open file" }));
    await vi.waitFor(() => expect(openPath).toHaveBeenCalledWith("C:/logs/jobs/j1.log"));

    server.use(http.post(`${BASE}/v1/ops/activity.log_file`, () => HttpResponse.json({ path: null })));
    await user.click(screen.getByRole("button", { name: "Open file" }));
    await vi.waitFor(() => expect(notice).toHaveBeenCalledWith(words.fileGone, { error: true }));
  });

  test("Undo opens the plan's confirm and answering posts it", async () => {
    const { posted, user } = setup();
    await user.click(await screen.findByRole("button", { name: /Undo/ }));
    expect(ops(posted, "activity.undo")[0]?.body).toEqual({ job_id: "j1" });
    expect(await screen.findByRole("alertdialog", { name: "Take Install Foo back?" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo install" }));
    await vi.waitFor(() => expect(posted.at(-1)).toEqual({ path: "plans/p1", body: { ok: true, option: false, choice: "", ticked: [] } }));
  });

  test("a refused Undo is told and the list is read again", async () => {
    const { posted, pageUrls, user } = setup();
    server.use(
      http.post(`${BASE}/v1/ops/activity.undo`, () =>
        HttpResponse.json({ plan_id: null, prompt: { kind: "refusal", title: "It cannot be taken back", body: "The game is running." } }),
      ),
    );
    await screen.findByText("Install Foo");
    const before = pageUrls.length;
    await user.click(screen.getByRole("button", { name: /Undo/ }));
    expect(await screen.findByText("The game is running.")).toBeInTheDocument();
    await vi.waitFor(() => expect(pageUrls.length).toBeGreaterThan(before));
    expect(posted.some((p) => p.path.startsWith("plans/"))).toBe(false);
  });

  test("a finished job (event) reads the page again", async () => {
    const { pageUrls, qc } = setup();
    await screen.findByText("Install Foo");
    const before = pageUrls.length;
    const toasts = { progress() {}, done: vi.fn(), failed() {}, cancelled() {}, notice() {}, error() {} } as unknown as Toasts;
    handleEvent(
      { seq: 1, type: "finished", job_id: "u1", data: {} } as never,
      { queryClient: qc, toasts, ask() {}, navigate() {} },
    );
    await vi.waitFor(() => expect(pageUrls.length).toBeGreaterThan(before));
    expect(toasts.done).toHaveBeenCalled();
  });
});
