import { expect, test, vi } from "vitest";
import { streamEvents, type ApiEvent } from "./events";

const frame = (e: ApiEvent) => `id: ${e.seq}\nevent: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`;
const resync: ApiEvent = { seq: 9, type: "resync", data: { requested: 2, oldest: 7, seq: 9 } };
const notice: ApiEvent = { seq: 10, type: "notice", data: { text: "hi", error: false, details: false } };

function mockFetch(...chunks: string[]) {
  const enc = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      chunks.forEach((s) => c.enqueue(enc.encode(s)));
      c.close();
    },
  });
  return vi.fn().mockResolvedValue(new Response(body));
}

async function collect(it: AsyncIterable<ApiEvent>) {
  const out: ApiEvent[] = [];
  for await (const e of it) out.push(e);
  return out;
}

test("yields events in order across split chunks, skipping keepalive comments", async () => {
  const text = frame(resync) + ": ping\n\n" + frame(notice);
  const fetch = mockFetch(text.slice(0, 20), text.slice(20, 90), text.slice(90));
  const events = await collect(streamEvents({ baseUrl: "http://h", token: "t", fetch }));
  expect(events.map((e) => e.seq)).toEqual([9, 10]);
  const last = events[1]!;
  if (last.type === "notice") expect(last.data.text).toBe("hi"); // the union narrows on `type`
});

test("sends the bearer token and resumes with Last-Event-ID", async () => {
  const fetch = mockFetch();
  await collect(streamEvents({ baseUrl: "http://h", token: "t", lastEventId: 2, fetch }));
  const [url, init] = fetch.mock.calls[0]!;
  expect(url).toBe("http://h/v1/events");
  expect(init.headers).toMatchObject({ Authorization: "Bearer t", "Last-Event-ID": "2" });
});

test("omits Last-Event-ID on a first connection and surfaces resync", async () => {
  const fetch = mockFetch(frame(resync));
  const [e] = await collect(streamEvents({ baseUrl: "http://h", token: "t", fetch }));
  expect(fetch.mock.calls[0]![1].headers).not.toHaveProperty("Last-Event-ID");
  expect(e?.type).toBe("resync");
});

test("rejects on a non-2xx answer", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response("no", { status: 401 }));
  await expect(collect(streamEvents({ baseUrl: "http://h", token: "t", fetch }))).rejects.toThrow("HTTP 401");
});
