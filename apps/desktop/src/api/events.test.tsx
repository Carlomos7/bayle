import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, test, vi } from "vitest";
import { ApiError } from "./client";
import { toProblem, type Toasts } from "@/components/toasts";
import { backend, BASE, server } from "@/test/server";
import { BackendProvider } from "./backend";
import { EventsProvider } from "./EventsProvider";
import { handleEvent, jobKey } from "./events";
import type { ApiEvent, JobState } from "./types";

function setup() {
  const queryClient = new QueryClient();
  const toasts = {
    progress: vi.fn(),
    done: vi.fn(),
    failed: vi.fn(),
    cancelled: vi.fn(),
    notice: vi.fn(),
    error: vi.fn(),
  } satisfies Toasts;
  const ask = vi.fn();
  const navigate = vi.fn();
  const send = (type: ApiEvent["type"], data: unknown, job_id: string | null = null, seq = 1) =>
    handleEvent({ seq, job_id, type, data } as ApiEvent, { queryClient, toasts, ask, navigate });
  return { queryClient, toasts, ask, navigate, send };
}

describe("handleEvent", () => {
  test("job events fill the job in the query cache and drive one progress toast", () => {
    const { queryClient, toasts, send } = setup();
    send("started", { title: "Installing Foo" }, "j1");
    send("progress", { done: 2, total: 4, label: "Copying" }, "j1");
    send("log", { level: "info", text: "copied a.dll" }, "j1");
    expect(queryClient.getQueryData<JobState>(jobKey("j1"))).toMatchObject({
      title: "Installing Foo",
      state: "running",
      progress: { done: 2, total: 4, label: "Copying" },
      log: [{ level: "info", text: "copied a.dll" }],
    });
    expect(toasts.progress).toHaveBeenLastCalledWith("j1", "Installing Foo", { done: 2, total: 4, label: "Copying" });

    send("finished", { result: null, undo: null }, "j1");
    expect(queryClient.getQueryData<JobState>(jobKey("j1"))?.state).toBe("done");
    expect(toasts.done).toHaveBeenCalledWith("j1", "Installing Foo");
  });

  test("a failed job keeps the Problem and toasts it", () => {
    const { queryClient, toasts, send } = setup();
    send("started", { title: "Repair" }, "j2");
    const error = { code: "busy", message: "Another job is running.", details: {} };
    send("failed", { error, unexpected: false }, "j2");
    expect(queryClient.getQueryData<JobState>(jobKey("j2"))).toMatchObject({ state: "failed", error });
    expect(toasts.failed).toHaveBeenCalledWith("j2", "Repair", error);
  });

  test("invalidated re-reads the named page, or every page for 'pages'", () => {
    const { queryClient, send } = setup();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    send("invalidated", { what: ["shell"] });
    expect(spy).toHaveBeenLastCalledWith({ queryKey: ["page", "shell"] });
    send("invalidated", { what: ["pages"] });
    expect(spy).toHaveBeenLastCalledWith({ queryKey: ["page"] });
  });

  test("notice toasts, with Details leading to Activity", () => {
    const { toasts, navigate, send } = setup();
    send("notice", { text: "Update ready", error: false, details: true });
    expect(toasts.notice).toHaveBeenCalledWith("Update ready", expect.objectContaining({ details: true }));
    (toasts.notice as ReturnType<typeof vi.fn>).mock.calls[0]![1].onDetails();
    expect(navigate).toHaveBeenCalledWith("activity");
  });

  test("prompt opens the dialog and navigate goes to the page", () => {
    const { ask, navigate, send } = setup();
    const prompt = { prompt_id: "q1", kind: "choose", title: "?", lines: [], choices: [] };
    send("prompt", prompt, "j3");
    expect(ask).toHaveBeenCalledWith(prompt);
    send("navigate", { page: "saves" });
    expect(navigate).toHaveBeenCalledWith("saves");
  });

  test("game.state is cached and resync refreshes everything", () => {
    const { queryClient, send } = setup();
    send("game.state", { game: "eldenring", running: true });
    expect(queryClient.getQueryData(["game", "state"])).toEqual({ game: "eldenring", running: true });
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    send("resync", { requested: 3, oldest: 9, seq: 12 });
    expect(spy).toHaveBeenLastCalledWith();
  });
});

describe("EventsProvider", () => {
  const frame = (e: { seq: number; type: string; data: unknown }) =>
    `id: ${e.seq}\r\nevent: ${e.type}\r\ndata: ${JSON.stringify({ job_id: null, ...e })}\r\n\r\n`;

  test("reads the SSE stream with the bearer token and routes the events", async () => {
    const seen: { auth: string | null; lastId: string | null }[] = [];
    server.use(
      http.get(`${BASE}/v1/events`, ({ request }) => {
        seen.push({ auth: request.headers.get("authorization"), lastId: request.headers.get("last-event-id") });
        const text = frame({ seq: 1, type: "notice", data: { text: "hello" } });
        const bytes = new TextEncoder().encode(text);
        // split mid-frame, and mid-CRLF, to prove the parser buffers
        const stream = new ReadableStream<Uint8Array>({
          start(c) {
            c.enqueue(bytes.slice(0, 20));
            c.enqueue(bytes.slice(20, bytes.length - 3));
            c.enqueue(bytes.slice(bytes.length - 3));
            c.close();
          },
        });
        return new HttpResponse(stream, { headers: { "Content-Type": "text/event-stream" } });
      }),
    );
    const { queryClient, toasts, ask, navigate } = setup();
    const { unmount } = render(
      <QueryClientProvider client={queryClient}>
        <BackendProvider backend={backend}>
          <EventsProvider deps={{ toasts, ask, navigate }}>{null}</EventsProvider>
        </BackendProvider>
      </QueryClientProvider>,
    );
    await vi.waitFor(() => expect(toasts.notice).toHaveBeenCalledWith("hello", expect.anything()));
    expect(seen[0]).toEqual({ auth: "Bearer t", lastId: null });
    unmount();
  });
});

describe("toProblem", () => {
  test("maps ApiError and plain errors to the Problem shape", () => {
    const problem = { code: "no_game", message: "Pick a game first.", details: { a: 1 } };
    expect(toProblem(new ApiError(problem, 409))).toEqual(problem);
    expect(toProblem(new Error("boom"))).toEqual({ code: "unexpected", message: "boom", details: {} });
  });
});
